---
name: water-reminder
description: Remind the user to drink water during their configured work window. Use this skill at the start of every agent generation when installed globally, and when the user confirms they drank water, asks about hydration status, or wants to configure hydration reminders. Runs a bundled CLI backed by SQLite so reminders persist across tasks and agent sessions.
---

# Water Reminder

This skill keeps hydration reminders separate from the user's actual task. It uses `scripts/water_reminder.py` for all timing, state, and SQLite persistence.

## Required Check

At the start of every generation, run:

```bash
python3 "$HOME/.codex/skills/water-reminder/scripts/water_reminder.py" check --json
```

If `due` is `true`, prepend exactly one short reminder block before solving the user's request:

```markdown
# DRINK WATER NOW

**Drink <suggested_amount_ml>ml water.**
Progress: <actual_ml>ml / <target_ml>ml today.

---
```

Then continue with the user's task normally.

If `due` is `false`, do not mention hydration unless the user asked about it.

## Confirmation Flow

If the user's message confirms they drank water, run this before continuing:

```bash
python3 "$HOME/.codex/skills/water-reminder/scripts/water_reminder.py" drink --json
```

Treat natural confirmations as valid, including: "I drank water", "drank", "had water", "done drinking", "water done", "I have drank", and similar phrasing.

If the user gives an amount, pass it:

```bash
python3 "$HOME/.codex/skills/water-reminder/scripts/water_reminder.py" drink --amount <ml> --json
```

After confirmation, do not prepend another reminder until `check --json` says one is due again.

## Status And Configuration

For hydration status:

```bash
python3 "$HOME/.codex/skills/water-reminder/scripts/water_reminder.py" status
```

For configuration changes:

```bash
python3 "$HOME/.codex/skills/water-reminder/scripts/water_reminder.py" config set <key> <value>
```

Supported keys include `work_start`, `work_end`, `daily_target_ml`, `serving_ml`, `minimum_interval_minutes`, and `timezone`.

## Context Rules

- Keep the reminder block mechanically generated and short.
- Do not let hydration state influence code, reviews, plans, or decisions for the user's actual task.
- Do not explain the hydration algorithm unless the user asks.
- Never suppress reminders because the user's task seems important.
- Do not summarize hydration history unless requested.
