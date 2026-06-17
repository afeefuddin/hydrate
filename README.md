# Water Reminder Skill

An installable Codex skill that reminds you to drink water during your configured work window.

The skill runs a small SQLite-backed CLI at the start of agent generations. When hydration is due, the agent prepends a short reminder block before continuing the user's actual task. Once the user confirms they drank water, the CLI records it and suppresses reminders until the next due window.

## Install

After pushing this repo to GitHub, install with:

```bash
python3 ~/.codex/skills/.system/skill-installer/scripts/install-skill-from-github.py \
  --repo OWNER/REPO \
  --path skills/water-reminder
```

Then restart Codex so the skill is picked up.

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
python3 ~/.codex/skills/water-reminder/scripts/water_reminder.py config set serving_ml 400
python3 ~/.codex/skills/water-reminder/scripts/water_reminder.py config set minimum_interval_minutes 120
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

The reminder logic uses a sliding work-window target:

```text
expected_ml_by_now = daily_target_ml * elapsed_work_window_fraction
hydration_gap = expected_ml_by_now - actual_ml_today
```

A reminder becomes due when the user is behind by at least `serving_ml` and the configured minimum interval has passed. Once due, the reminder remains pending and repeats until the user confirms they drank water.

## Validate Before Release

From the repo root:

```bash
python3 -m py_compile skills/water-reminder/scripts/water_reminder.py
python3 ~/.codex/skills/.system/skill-creator/scripts/quick_validate.py skills/water-reminder
```

The validator requires `PyYAML` in the Python environment.
