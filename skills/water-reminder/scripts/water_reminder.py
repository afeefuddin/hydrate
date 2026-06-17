#!/usr/bin/env python3
"""SQLite-backed hydration reminder CLI for the water-reminder skill."""

from __future__ import annotations

import argparse
import json
import math
import os
import sqlite3
import sys
from dataclasses import dataclass
from datetime import datetime, time, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


DEFAULT_DB_PATH = Path("~/.local/share/water-reminder/water-reminder.sqlite3").expanduser()

DEFAULT_SETTINGS = {
    "work_start": "09:00",
    "work_end": "18:00",
    "timezone": "local",
    "daily_target_ml": "2500",
    "reminder_interval_minutes": "120",
}

CONFIRMATION_SOURCE = "agent-confirmation"


@dataclass(frozen=True)
class Window:
    start: datetime
    end: datetime
    active: bool


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Manage hydration reminders.")
    parser.add_argument(
        "--db",
        default=os.environ.get("WATER_REMINDER_DB", str(DEFAULT_DB_PATH)),
        help="SQLite database path. Defaults to ~/.local/share/water-reminder/water-reminder.sqlite3.",
    )

    subparsers = parser.add_subparsers(dest="command", required=True)

    init_parser = subparsers.add_parser("init", help="Initialize the database.")
    init_parser.add_argument("--json", action="store_true")

    check_parser = subparsers.add_parser("check", help="Check whether a reminder is due.")
    check_parser.add_argument("--json", action="store_true")

    drink_parser = subparsers.add_parser("drink", help="Record that water was consumed.")
    drink_parser.add_argument("--amount", type=int, help="Amount consumed in milliliters.")
    drink_parser.add_argument("--json", action="store_true")

    status_parser = subparsers.add_parser("status", help="Print hydration status.")
    status_parser.add_argument("--json", action="store_true")

    config_parser = subparsers.add_parser("config", help="Read or update configuration.")
    config_subparsers = config_parser.add_subparsers(dest="config_command", required=True)
    config_subparsers.add_parser("list", help="List settings.").add_argument("--json", action="store_true")
    get_parser = config_subparsers.add_parser("get", help="Get a setting.")
    get_parser.add_argument("key")
    get_parser.add_argument("--json", action="store_true")
    set_parser = config_subparsers.add_parser("set", help="Set a setting.")
    set_parser.add_argument("key")
    set_parser.add_argument("value")
    set_parser.add_argument("--json", action="store_true")

    return parser.parse_args()


def connect(db_path: str) -> sqlite3.Connection:
    path = Path(db_path).expanduser()
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path, timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA busy_timeout = 10000")
    conn.execute("PRAGMA journal_mode = WAL")
    initialize(conn)
    return conn


def initialize(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS settings (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS drink_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            drank_at TEXT NOT NULL,
            drank_at_epoch INTEGER NOT NULL,
            amount_ml INTEGER NOT NULL,
            source TEXT NOT NULL
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS reminder_state (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
        )
        """
    )
    migrate_drink_events(conn)
    migrate_settings(conn)
    conn.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_drink_events_drank_at_epoch
        ON drink_events (drank_at_epoch)
        """
    )
    for key, value in DEFAULT_SETTINGS.items():
        conn.execute(
            "INSERT OR IGNORE INTO settings (key, value) VALUES (?, ?)",
            (key, value),
        )
    conn.commit()


def migrate_settings(conn: sqlite3.Connection) -> None:
    old_interval = conn.execute(
        "SELECT value FROM settings WHERE key = 'minimum_interval_minutes'"
    ).fetchone()
    new_interval = conn.execute(
        "SELECT value FROM settings WHERE key = 'reminder_interval_minutes'"
    ).fetchone()
    if old_interval and not new_interval:
        conn.execute(
            "INSERT INTO settings (key, value) VALUES (?, ?)",
            ("reminder_interval_minutes", old_interval["value"]),
        )
    conn.execute("DELETE FROM settings WHERE key IN ('minimum_interval_minutes', 'serving_ml')")


def migrate_drink_events(conn: sqlite3.Connection) -> None:
    columns = {
        row["name"]
        for row in conn.execute("PRAGMA table_info(drink_events)")
    }
    if "drank_at_epoch" not in columns:
        conn.execute("ALTER TABLE drink_events ADD COLUMN drank_at_epoch INTEGER")

    rows = conn.execute(
        "SELECT id, drank_at FROM drink_events WHERE drank_at_epoch IS NULL"
    ).fetchall()
    for row in rows:
        dt = datetime.fromisoformat(row["drank_at"])
        conn.execute(
            "UPDATE drink_events SET drank_at_epoch = ? WHERE id = ?",
            (epoch(dt), row["id"]),
        )


def settings(conn: sqlite3.Connection) -> dict[str, str]:
    return {row["key"]: row["value"] for row in conn.execute("SELECT key, value FROM settings")}


def state(conn: sqlite3.Connection) -> dict[str, str]:
    return {row["key"]: row["value"] for row in conn.execute("SELECT key, value FROM reminder_state")}


def set_state(conn: sqlite3.Connection, key: str, value: str | None) -> None:
    if value is None:
        conn.execute("DELETE FROM reminder_state WHERE key = ?", (key,))
    else:
        conn.execute(
            "INSERT INTO reminder_state (key, value) VALUES (?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (key, value),
        )


def parse_local_time(value: str, key: str) -> time:
    try:
        hour, minute = value.split(":", 1)
        return time(int(hour), int(minute))
    except ValueError as exc:
        raise SystemExit(f"{key} must use HH:MM format") from exc


def parse_positive_int(raw: str, key: str) -> int:
    try:
        value = int(raw)
    except ValueError as exc:
        raise SystemExit(f"{key} must be an integer") from exc
    if value <= 0:
        raise SystemExit(f"{key} must be greater than zero")
    return value


def local_zone() -> timezone:
    return datetime.now().astimezone().tzinfo or timezone.utc


def configured_zone(raw: str):
    if raw == "local":
        return local_zone()
    try:
        return ZoneInfo(raw)
    except ZoneInfoNotFoundError as exc:
        raise SystemExit(f"Unknown timezone: {raw}") from exc


def parse_now(raw: str | None, tz) -> datetime:
    if not raw:
        return datetime.now(tz)
    parsed = datetime.fromisoformat(raw)
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=tz)
    return parsed.astimezone(tz)


def work_window(cfg: dict[str, str], now: datetime) -> Window:
    start_t = parse_local_time(cfg["work_start"], "work_start")
    end_t = parse_local_time(cfg["work_end"], "work_end")

    start = datetime.combine(now.date(), start_t, tzinfo=now.tzinfo)
    end = datetime.combine(now.date(), end_t, tzinfo=now.tzinfo)
    if end <= start:
        end += timedelta(days=1)
        if now < start:
            start -= timedelta(days=1)
            end -= timedelta(days=1)

    if now < start:
        previous_start = start - timedelta(days=1)
        previous_end = end - timedelta(days=1)
        if previous_start <= now < previous_end:
            return Window(previous_start, previous_end, True)
        return Window(start, end, False)

    return Window(start, end, start <= now < end)


def iso(dt: datetime) -> str:
    return dt.isoformat(timespec="seconds")


def epoch(dt: datetime) -> int:
    return int(dt.timestamp())


def event_sum(conn: sqlite3.Connection, start: datetime, end: datetime) -> int:
    row = conn.execute(
        "SELECT COALESCE(SUM(amount_ml), 0) AS total FROM drink_events WHERE drank_at_epoch >= ? AND drank_at_epoch <= ?",
        (epoch(start), epoch(end)),
    ).fetchone()
    return int(row["total"])


def last_drink_at(conn: sqlite3.Connection, start: datetime, end: datetime) -> datetime | None:
    row = conn.execute(
        "SELECT drank_at FROM drink_events WHERE drank_at_epoch >= ? AND drank_at_epoch <= ? ORDER BY drank_at_epoch DESC LIMIT 1",
        (epoch(start), epoch(end)),
    ).fetchone()
    if not row:
        return None
    return datetime.fromisoformat(row["drank_at"])


def clear_pending(conn: sqlite3.Connection) -> None:
    for key in (
        "pending",
        "pending_since",
        "suggested_amount_ml",
        "last_reminder_at",
        "pending_slot",
        "pending_due_at",
    ):
        set_state(conn, key, None)


def reset_if_new_window(conn: sqlite3.Connection, win: Window) -> None:
    current_window_id = iso(win.start)
    current = state(conn).get("window_start")
    if current != current_window_id:
        clear_pending(conn)
        set_state(conn, "window_start", current_window_id)
        conn.commit()


def reset_window_if_needed(conn: sqlite3.Connection, cfg: dict[str, str], now: datetime) -> Window:
    win = work_window(cfg, now)
    reset_if_new_window(conn, win)
    return win


def base_payload(conn: sqlite3.Connection, cfg: dict[str, str], now: datetime, win: Window | None = None) -> dict:
    if win is None:
        win = work_window(cfg, now)
    target = parse_positive_int(cfg["daily_target_ml"], "daily_target_ml")
    interval = parse_positive_int(cfg["reminder_interval_minutes"], "reminder_interval_minutes")
    actual = event_sum(conn, win.start, min(now, win.end))
    remaining = max(target - actual, 0)
    schedule = reminder_schedule(target, interval, win, now)

    return {
        "now": iso(now),
        "window": {
            "start": iso(win.start),
            "end": iso(win.end),
            "active": win.active,
        },
        "settings": {
            "daily_target_ml": target,
            "suggested_amount_ml": schedule["suggested_amount_ml"],
            "reminder_interval_minutes": interval,
            "work_start": cfg["work_start"],
            "work_end": cfg["work_end"],
            "timezone": cfg["timezone"],
        },
        "progress": {
            "actual_ml": actual,
            "target_ml": target,
            "remaining_ml": remaining,
            "expected_ml": schedule["expected_ml"],
            "gap_ml": max(schedule["expected_ml"] - actual, 0),
        },
        "schedule": {
            "slot_count": schedule["slot_count"],
            "current_slot": schedule["current_slot"],
            "suggested_amount_ml": schedule["suggested_amount_ml"],
            "current_slot_due_at": iso(schedule["current_slot_due_at"]) if schedule["current_slot_due_at"] else None,
            "next_slot_due_at": iso(schedule["next_slot_due_at"]) if schedule["next_slot_due_at"] else None,
        },
    }


def reminder_schedule(target_ml: int, interval_minutes: int, win: Window, now: datetime) -> dict:
    interval = timedelta(minutes=interval_minutes)
    due_times = slot_due_times(win, interval)
    slot_count = len(due_times)
    suggested_amount = max(1, math.ceil(target_ml / slot_count))

    current_slot = sum(1 for due_at in due_times if now >= due_at)
    if current_slot <= 0:
        current_due_at = None
    else:
        current_due_at = due_times[current_slot - 1]

    if current_slot < slot_count:
        next_due_at = due_times[current_slot]
    else:
        next_due_at = None

    return {
        "slot_count": slot_count,
        "current_slot": current_slot,
        "suggested_amount_ml": suggested_amount,
        "current_slot_due_at": current_due_at,
        "next_slot_due_at": next_due_at,
        "expected_ml": min(target_ml, suggested_amount * current_slot),
    }


def slot_due_times(win: Window, interval: timedelta) -> list[datetime]:
    due_times = []
    due_at = win.start + interval
    while due_at < win.end:
        due_times.append(due_at)
        due_at += interval

    if not due_times:
        due_times.append(win.start + ((win.end - win.start) / 2))

    return due_times


def slot_already_confirmed(conn: sqlite3.Connection, win: Window, now: datetime, due_at: datetime) -> bool:
    latest_drink = last_drink_at(conn, win.start, min(now, win.end))
    return latest_drink is not None and latest_drink >= due_at


def check(conn: sqlite3.Connection, now: datetime) -> dict:
    cfg = settings(conn)
    win = reset_window_if_needed(conn, cfg, now)
    payload = base_payload(conn, cfg, now, win)
    st = state(conn)

    if not payload["window"]["active"]:
        clear_pending(conn)
        conn.commit()
        payload.update(
            {
                "due": False,
                "reason": "outside_work_window",
                "suggested_amount_ml": 0,
                "message": "",
            }
        )
        return payload

    if st.get("pending") == "true":
        suggested = parse_positive_int(
            st.get("suggested_amount_ml", str(payload["schedule"]["suggested_amount_ml"])),
            "suggested_amount_ml",
        )
        set_state(conn, "last_reminder_at", iso(now))
        conn.commit()
        payload.update(
            {
                "due": True,
                "reason": "pending_until_confirmed",
                "suggested_amount_ml": suggested,
                "message": f"DRINK WATER NOW: {suggested}ml",
            }
        )
        return payload

    serving = payload["schedule"]["suggested_amount_ml"]
    remaining = payload["progress"]["remaining_ml"]
    due_at_raw = payload["schedule"]["current_slot_due_at"]
    due_at = datetime.fromisoformat(due_at_raw) if due_at_raw else None
    due = (
        remaining > 0
        and due_at is not None
        and now >= due_at
        and not slot_already_confirmed(conn, win, now, due_at)
    )

    if not due:
        payload.update(
            {
                "due": False,
                "reason": "waiting_for_next_slot",
                "suggested_amount_ml": 0,
                "message": "",
            }
        )
        return payload

    suggested = min(serving, remaining)
    set_state(conn, "pending", "true")
    set_state(conn, "pending_since", iso(now))
    set_state(conn, "last_reminder_at", iso(now))
    set_state(conn, "suggested_amount_ml", str(suggested))
    set_state(conn, "pending_slot", str(payload["schedule"]["current_slot"]))
    set_state(conn, "pending_due_at", due_at_raw)
    conn.commit()

    payload.update(
        {
            "due": True,
            "reason": "scheduled_interval_due",
            "suggested_amount_ml": suggested,
            "message": f"DRINK WATER NOW: {suggested}ml",
        }
    )
    return payload


def drink(conn: sqlite3.Connection, now: datetime, amount: int | None) -> dict:
    cfg = settings(conn)
    reset_window_if_needed(conn, cfg, now)
    st = state(conn)
    payload = base_payload(conn, cfg, now)
    suggested = int(st.get("suggested_amount_ml", payload["schedule"]["suggested_amount_ml"]))
    consumed = amount if amount is not None else suggested
    if consumed <= 0:
        raise SystemExit("amount must be greater than zero")

    conn.execute(
        "INSERT INTO drink_events (drank_at, drank_at_epoch, amount_ml, source) VALUES (?, ?, ?, ?)",
        (iso(now), epoch(now), consumed, CONFIRMATION_SOURCE),
    )
    clear_pending(conn)
    set_state(conn, "last_drink_at", iso(now))
    conn.commit()

    payload.update(
        {
            "recorded": True,
            "amount_ml": consumed,
            "message": f"Recorded {consumed}ml water.",
        }
    )
    return payload


def status(conn: sqlite3.Connection, now: datetime) -> dict:
    payload = base_payload(conn, settings(conn), now)
    st = state(conn)
    payload.update(
        {
            "pending": st.get("pending") == "true",
            "pending_since": st.get("pending_since"),
            "suggested_amount_ml": int(st.get("suggested_amount_ml", "0") or "0"),
        }
    )
    return payload


def normalize_setting_key(key: str) -> str:
    if key == "minimum_interval_minutes":
        return "reminder_interval_minutes"
    return key


def validate_setting(key: str, value: str) -> tuple[str, str]:
    key = normalize_setting_key(key)
    if key not in DEFAULT_SETTINGS:
        allowed = ", ".join(sorted(DEFAULT_SETTINGS))
        raise SystemExit(f"Unknown setting '{key}'. Allowed: {allowed}")
    if key in ("work_start", "work_end"):
        parse_local_time(value, key)
    if key in ("daily_target_ml", "reminder_interval_minutes"):
        parse_positive_int(value, key)
    if key == "timezone" and value != "local":
        configured_zone(value)
    return key, value


def write_json(payload: dict) -> None:
    print(json.dumps(payload, indent=2, sort_keys=True))


def print_check(payload: dict) -> None:
    if payload["due"]:
        progress = payload["progress"]
        print(f"DRINK WATER NOW: {payload['suggested_amount_ml']}ml")
        print(f"Progress: {progress['actual_ml']}ml / {progress['target_ml']}ml today")
    else:
        print(f"No reminder due ({payload['reason']}).")


def print_status(payload: dict) -> None:
    progress = payload["progress"]
    win = payload["window"]
    pending = "yes" if payload["pending"] else "no"
    print(f"Progress: {progress['actual_ml']}ml / {progress['target_ml']}ml today")
    print(f"Expected now: {progress['expected_ml']}ml")
    print(f"Remaining: {progress['remaining_ml']}ml")
    print(f"Work window: {win['start']} to {win['end']} (active: {win['active']})")
    print(f"Pending reminder: {pending}")


def main() -> int:
    args = parse_args()

    conn = connect(args.db)
    cfg = settings(conn)
    tz = configured_zone(cfg["timezone"])
    now = parse_now(None, tz)

    if args.command == "init":
        payload = {"initialized": True, "db": str(Path(args.db).expanduser())}
        write_json(payload) if args.json else print(f"Initialized {payload['db']}")
        return 0

    if args.command == "check":
        payload = check(conn, now)
        write_json(payload) if args.json else print_check(payload)
        return 0

    if args.command == "drink":
        payload = drink(conn, now, args.amount)
        write_json(payload) if args.json else print(payload["message"])
        return 0

    if args.command == "status":
        payload = status(conn, now)
        write_json(payload) if args.json else print_status(payload)
        return 0

    if args.command == "config":
        if args.config_command == "list":
            payload = settings(conn)
            write_json(payload) if args.json else print("\n".join(f"{k}={v}" for k, v in sorted(payload.items())))
            return 0
        if args.config_command == "get":
            payload = settings(conn)
            key = normalize_setting_key(args.key)
            value = payload.get(key)
            if value is None:
                raise SystemExit(f"Unknown setting: {args.key}")
            write_json({key: value}) if args.json else print(value)
            return 0
        if args.config_command == "set":
            key, value = validate_setting(args.key, args.value)
            conn.execute(
                "INSERT INTO settings (key, value) VALUES (?, ?) "
                "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                (key, value),
            )
            clear_pending(conn)
            conn.commit()
            payload = {"updated": True, "key": key, "value": value}
            write_json(payload) if args.json else print(f"{key}={value}")
            return 0

    raise SystemExit(f"Unhandled command: {args.command}")


if __name__ == "__main__":
    sys.exit(main())
