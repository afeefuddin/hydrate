#!/usr/bin/env python3
"""SQLite-backed hydration reminder CLI for the water-reminder skill."""

from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


DEFAULT_DB_PATH = Path("~/.local/share/water-reminder/water-reminder.sqlite3").expanduser()

DEFAULT_SETTINGS = {
    "timezone": "local",
    "reminder_interval_minutes": "120",
    "default_drink_ml": "400",
}

LEGACY_SETTING_ALIASES = {
    "minimum_interval_minutes": "reminder_interval_minutes",
    "serving_ml": "default_drink_ml",
}

CONFIRMATION_SOURCE = "agent-confirmation"


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
    for legacy_key, canonical_key in LEGACY_SETTING_ALIASES.items():
        legacy = conn.execute(
            "SELECT value FROM settings WHERE key = ?",
            (legacy_key,),
        ).fetchone()
        canonical = conn.execute(
            "SELECT value FROM settings WHERE key = ?",
            (canonical_key,),
        ).fetchone()
        if legacy and not canonical:
            conn.execute(
                "INSERT INTO settings (key, value) VALUES (?, ?)",
                (canonical_key, legacy["value"]),
            )

    obsolete_keys = tuple(LEGACY_SETTING_ALIASES.keys()) + ("work_start", "work_end", "daily_target_ml")
    placeholders = ", ".join("?" for _ in obsolete_keys)
    conn.execute(f"DELETE FROM settings WHERE key IN ({placeholders})", obsolete_keys)


def migrate_drink_events(conn: sqlite3.Connection) -> None:
    columns = {row["name"] for row in conn.execute("PRAGMA table_info(drink_events)")}
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


def now_in_zone(cfg: dict[str, str]) -> datetime:
    return datetime.now(configured_zone(cfg["timezone"]))


def iso(dt: datetime) -> str:
    return dt.isoformat(timespec="seconds")


def epoch(dt: datetime) -> int:
    return int(dt.timestamp())


def last_drink(conn: sqlite3.Connection) -> sqlite3.Row | None:
    return conn.execute(
        "SELECT drank_at, drank_at_epoch, amount_ml FROM drink_events ORDER BY drank_at_epoch DESC LIMIT 1"
    ).fetchone()


def clear_pending(conn: sqlite3.Connection) -> None:
    for key in ("pending", "pending_since", "suggested_amount_ml", "last_reminder_at"):
        set_state(conn, key, None)


def base_payload(conn: sqlite3.Connection, cfg: dict[str, str], now: datetime) -> dict:
    interval_minutes = parse_positive_int(
        cfg["reminder_interval_minutes"],
        "reminder_interval_minutes",
    )
    default_amount = parse_positive_int(cfg["default_drink_ml"], "default_drink_ml")
    last = last_drink(conn)
    last_drank_at = datetime.fromisoformat(last["drank_at"]) if last else None
    next_due_at = (last_drank_at + timedelta(minutes=interval_minutes)) if last_drank_at else now
    seconds_until_due = int((next_due_at - now).total_seconds())

    return {
        "now": iso(now),
        "settings": {
            "timezone": cfg["timezone"],
            "reminder_interval_minutes": interval_minutes,
            "default_drink_ml": default_amount,
        },
        "last_drink": {
            "drank_at": iso(last_drank_at) if last_drank_at else None,
            "amount_ml": int(last["amount_ml"]) if last else None,
        },
        "next_due_at": iso(next_due_at),
        "seconds_until_due": max(seconds_until_due, 0),
    }


def check(conn: sqlite3.Connection, now: datetime) -> dict:
    cfg = settings(conn)
    payload = base_payload(conn, cfg, now)
    st = state(conn)

    if st.get("pending") == "true":
        suggested = parse_positive_int(
            st.get("suggested_amount_ml", str(payload["settings"]["default_drink_ml"])),
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

    due = payload["seconds_until_due"] <= 0
    if not due:
        payload.update(
            {
                "due": False,
                "reason": "waiting_for_interval",
                "suggested_amount_ml": 0,
                "message": "",
            }
        )
        return payload

    suggested = payload["settings"]["default_drink_ml"]
    set_state(conn, "pending", "true")
    set_state(conn, "pending_since", iso(now))
    set_state(conn, "last_reminder_at", iso(now))
    set_state(conn, "suggested_amount_ml", str(suggested))
    conn.commit()

    payload.update(
        {
            "due": True,
            "reason": "interval_elapsed",
            "suggested_amount_ml": suggested,
            "message": f"DRINK WATER NOW: {suggested}ml",
        }
    )
    return payload


def drink(conn: sqlite3.Connection, now: datetime, amount: int | None) -> dict:
    cfg = settings(conn)
    st = state(conn)
    fallback_amount = parse_positive_int(cfg["default_drink_ml"], "default_drink_ml")
    suggested = int(st.get("suggested_amount_ml", fallback_amount))
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

    payload = base_payload(conn, cfg, now)
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
    return LEGACY_SETTING_ALIASES.get(key, key)


def validate_setting(key: str, value: str) -> tuple[str, str]:
    key = normalize_setting_key(key)
    if key not in DEFAULT_SETTINGS:
        allowed = ", ".join(sorted(DEFAULT_SETTINGS))
        raise SystemExit(f"Unknown setting '{key}'. Allowed: {allowed}")
    if key in ("reminder_interval_minutes", "default_drink_ml"):
        parse_positive_int(value, key)
    if key == "timezone" and value != "local":
        configured_zone(value)
    return key, value


def write_json(payload: dict) -> None:
    print(json.dumps(payload, indent=2, sort_keys=True))


def print_check(payload: dict) -> None:
    if payload["due"]:
        print(f"DRINK WATER NOW: {payload['suggested_amount_ml']}ml")
    else:
        minutes = max(1, payload["seconds_until_due"] // 60)
        print(f"No reminder due. Next reminder in about {minutes} minute(s).")


def print_status(payload: dict) -> None:
    last = payload["last_drink"]
    pending = "yes" if payload["pending"] else "no"
    last_text = last["drank_at"] or "never"
    print(f"Last drink: {last_text}")
    print(f"Next reminder: {payload['next_due_at']}")
    print(f"Pending reminder: {pending}")


def main() -> int:
    args = parse_args()

    conn = connect(args.db)
    cfg = settings(conn)
    now = now_in_zone(cfg)

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
