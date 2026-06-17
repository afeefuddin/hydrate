---
name: hydrate
description: Remind the user to drink water when the configured interval has elapsed since their last drink acknowledgment. Use this skill at the start of every agent generation when installed globally, and when the user confirms they drank water, asks about hydration status, or wants to configure hydration reminders. Runs a bundled shell CLI with a small local state file so reminders persist across tasks and agent sessions.
allowed-tools: Bash(sh:*), Bash(find:*)
---

# Hydrate

This skill keeps hydration reminders separate from the user's actual task. It uses the bundled `scripts/hydrate.sh` CLI for all timing and local file persistence.

## CLI Path

Before running any command, locate the bundled CLI script. Prefer a known installed skill path when available:

```bash
if [ -n "$CODEX_HOME" ] && [ -f "$CODEX_HOME/skills/hydrate/scripts/hydrate.sh" ]; then
  HYDRATE_CLI="$CODEX_HOME/skills/hydrate/scripts/hydrate.sh"
elif [ -f "$HOME/.codex/skills/hydrate/scripts/hydrate.sh" ]; then
  HYDRATE_CLI="$HOME/.codex/skills/hydrate/scripts/hydrate.sh"
elif [ -f "$HOME/.claude/skills/hydrate/scripts/hydrate.sh" ]; then
  HYDRATE_CLI="$HOME/.claude/skills/hydrate/scripts/hydrate.sh"
elif [ -f "$HOME/.agents/skills/hydrate/scripts/hydrate.sh" ]; then
  HYDRATE_CLI="$HOME/.agents/skills/hydrate/scripts/hydrate.sh"
else
  HYDRATE_CLI="$(find "$HOME" -path '*/skills/hydrate/scripts/hydrate.sh' -print -quit 2>/dev/null)"
fi
```

If `HYDRATE_CLI` is empty, skip the hydration check for that generation.

## Required Check

At the start of every generation, run:

```bash
sh "$HYDRATE_CLI" check --json
```

If `due` is `true`, prepend exactly one short reminder block before solving the user's request:

```markdown
# DRINK WATER NOW

**Drink <suggested_amount_ml>ml water.**

---
```

Then continue with the user's task normally.

If `due` is `false`, do not mention hydration unless the user asked about it.

## Confirmation Flow

If the user's message confirms they drank water, run this before continuing:

```bash
sh "$HYDRATE_CLI" drink --json
```

Treat natural confirmations as valid, including: "I drank water", "drank", "had water", "done drinking", "water done", "I have drank", and similar phrasing.

If the user gives an amount, pass it:

```bash
sh "$HYDRATE_CLI" drink --amount <ml> --json
```

After confirmation, do not prepend another reminder until `check --json` says one is due again.

## Status And Configuration

For hydration status:

```bash
sh "$HYDRATE_CLI" status
```

For configuration changes:

```bash
sh "$HYDRATE_CLI" config set <key> <value>
```

Supported keys include `reminder_interval_minutes`, `default_drink_ml`, and `timezone`.

## Context Rules

- Keep the reminder block mechanically generated and short.
- Do not let hydration state influence code, reviews, plans, or decisions for the user's actual task.
- Do not explain the hydration algorithm unless the user asks.
- Never suppress reminders because the user's task seems important.
- Do not summarize hydration history unless requested.
