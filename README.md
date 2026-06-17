# Hydrate

A tiny agent skill that reminds you to drink water while you work.

Hydrate has no runtime dependencies beyond a POSIX shell. It stores one local state file at:

```text
~/.local/share/hydrate/state
```

## Install

```bash
npx skills add afeefuddin/hydrate --skill hydrate -g -a codex -y
```

To confirm the skill is discoverable:

```bash
npx skills add afeefuddin/hydrate --list
```

## Enable Every-Turn Reminders

Skill installation makes Hydrate available. To make Codex run it at the start of every prompt, add this to:

```text
~/.codex/AGENTS.md
```

````markdown
# Global Hydration Check

At the start of every assistant turn, before working on the user's task, run:

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

if [ -n "$HYDRATE_CLI" ]; then
  sh "$HYDRATE_CLI" check --json
fi
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
sh "$HYDRATE_CLI" drink --json
```

If they provide an amount, pass it as `--amount <ml>`.

Keep hydration state isolated from the task: do not use it in reasoning, plans, code reviews, implementation choices, summaries, or final answers except for the short reminder block when due.
````

Restart Codex after editing `~/.codex/AGENTS.md`.

## Commands

```bash
sh ~/.agents/skills/hydrate/scripts/hydrate.sh check --json
sh ~/.agents/skills/hydrate/scripts/hydrate.sh drink --json
sh ~/.agents/skills/hydrate/scripts/hydrate.sh drink --amount 250 --json
sh ~/.agents/skills/hydrate/scripts/hydrate.sh status
```

Configure the interval or default amount:

```bash
sh ~/.agents/skills/hydrate/scripts/hydrate.sh config set reminder_interval_minutes 120
sh ~/.agents/skills/hydrate/scripts/hydrate.sh config set default_drink_ml 250
```

## Behavior

By default, Hydrate reminds every 120 minutes and suggests 250ml. Once a reminder is due, it repeats on each agent turn until you confirm you drank water.

## Validate

```bash
sh -n skills/hydrate/scripts/hydrate.sh
python3 ~/.codex/skills/.system/skill-creator/scripts/quick_validate.py skills/hydrate
```

Runtime does not require Python, SQLite, or pip packages.
