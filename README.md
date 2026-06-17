# Water Reminder Skill

An installable agent skill that reminds you to drink water during your configured work window.

The skill runs a small SQLite-backed CLI at the start of agent generations. When a reminder slot is due, the agent prepends a short reminder block before continuing the user's actual task. Once the user confirms they drank water, the CLI records it and suppresses reminders until the next slot.

## Install With skills.sh

After pushing this repo to GitHub:

```bash
npx skills add OWNER/REPO --skill water-reminder -g -a codex
```

Or install from the direct GitHub path:

```bash
npx skills add https://github.com/OWNER/REPO/tree/main/skills/water-reminder -g -a codex
```

For other supported agents, replace `codex` with the target agent or omit `-a codex` and let the CLI prompt.

## Install With Codex Skill Installer

After pushing this repo to GitHub, install with:

```bash
python3 ~/.codex/skills/.system/skill-installer/scripts/install-skill-from-github.py \
  --repo OWNER/REPO \
  --path skills/water-reminder
```

Then restart Codex so the skill is picked up.

## Discoverability

The repo uses the standard `skills/<name>/SKILL.md` layout, so `skills.sh` can discover it:

```bash
npx skills add OWNER/REPO --list
```

## Configure

The skill stores local state in:

```text
~/.local/share/water-reminder/water-reminder.sqlite3
```

Common settings:

```bash
python3 ~/.codex/skills/water-reminder/scripts/water_reminder.py config set timezone Asia/Kolkata
python3 ~/.codex/skills/water-reminder/scripts/water_reminder.py config set work_start 09:00
python3 ~/.codex/skills/water-reminder/scripts/water_reminder.py config set work_end 18:00
python3 ~/.codex/skills/water-reminder/scripts/water_reminder.py config set daily_target_ml 2500
python3 ~/.codex/skills/water-reminder/scripts/water_reminder.py config set reminder_interval_minutes 120
```

## CLI

Runtime commands:

```bash
python3 ~/.codex/skills/water-reminder/scripts/water_reminder.py init
python3 ~/.codex/skills/water-reminder/scripts/water_reminder.py check --json
python3 ~/.codex/skills/water-reminder/scripts/water_reminder.py drink --json
python3 ~/.codex/skills/water-reminder/scripts/water_reminder.py drink --amount 500 --json
python3 ~/.codex/skills/water-reminder/scripts/water_reminder.py status
python3 ~/.codex/skills/water-reminder/scripts/water_reminder.py config list
```

## How It Works

The reminder logic uses fixed interval slots inside the configured work window. By default, the interval is 120 minutes.

```text
slot_count = count of interval boundaries strictly inside work window
suggested_amount_ml = ceil(daily_target_ml / slot_count)
```

A reminder becomes due on each interval boundary, for example 11:00, 13:00, 15:00, and 17:00 for a 09:00-18:00 work window with a 120-minute interval. Once due, the reminder remains pending and repeats until the user confirms they drank water.

`minimum_interval_minutes` is accepted as a legacy alias for `reminder_interval_minutes`.

## Validate Before Release

From the repo root:

```bash
python3 -m py_compile skills/water-reminder/scripts/water_reminder.py
python3 ~/.codex/skills/.system/skill-creator/scripts/quick_validate.py skills/water-reminder
```

The validator requires `PyYAML` in the Python environment.
