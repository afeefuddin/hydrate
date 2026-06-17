# Water Reminder Skill

An installable agent skill that reminds you to drink water while working with agents.

The skill runs a small SQLite-backed CLI at the start of agent generations. When the configured interval has elapsed since the last time the user acknowledged drinking water, the agent prepends a short reminder block before continuing the user's actual task. Once the user confirms they drank water, the CLI records it and suppresses reminders until the interval elapses again.

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

## Enforce On Every Codex Prompt

Skill installation makes the skill available. To make Codex run the check at the start of every prompt, add this to your global Codex instructions file:

```text
~/.codex/AGENTS.md
```

````markdown
# Global Hydration Check

At the start of every assistant turn, before working on the user's task, run:

```bash
python3 "$HOME/.codex/skills/water-reminder/scripts/water_reminder.py" check --json
```

If the command returns `"due": true`, prepend this exact short block to the user-facing response, then continue with the user's actual task:

```markdown
# DRINK WATER NOW

**Drink <suggested_amount_ml>ml water.**

---
```

If the command returns `"due": false`, do not mention hydration.

If the user's message confirms they drank water, run this before continuing:

```bash
python3 "$HOME/.codex/skills/water-reminder/scripts/water_reminder.py" drink --json
```

If they provide an amount, pass it as `--amount <ml>`.

Keep hydration state isolated from the task: do not use it in reasoning, plans, code reviews, implementation choices, summaries, or final answers except for the short reminder block when due.
````

Restart Codex after editing `~/.codex/AGENTS.md`.

## Configure

The skill stores local state in:

```text
~/.local/share/water-reminder/water-reminder.sqlite3
```

Common settings:

```bash
python3 ~/.codex/skills/water-reminder/scripts/water_reminder.py config set timezone Asia/Kolkata
python3 ~/.codex/skills/water-reminder/scripts/water_reminder.py config set reminder_interval_minutes 120
python3 ~/.codex/skills/water-reminder/scripts/water_reminder.py config set default_drink_ml 400
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

The reminder logic is intentionally simple. By default, the interval is 120 minutes.

```text
next_due_at = last_drink_acknowledged_at + reminder_interval_minutes
```

A reminder becomes due when the current time is at or after `next_due_at`. Once due, it remains pending and repeats on every generation until the user confirms they drank water.

Legacy settings from earlier versions are migrated or removed automatically:

- `minimum_interval_minutes` becomes `reminder_interval_minutes`
- `serving_ml` becomes `default_drink_ml`
- `work_start`, `work_end`, and `daily_target_ml` are removed

## Validate Before Release

From the repo root:

```bash
python3 -m py_compile skills/water-reminder/scripts/water_reminder.py
python3 ~/.codex/skills/.system/skill-creator/scripts/quick_validate.py skills/water-reminder
```

The validator requires `PyYAML` in the Python environment.
