# Hydrate

An installable agent skill that reminds you to drink water while working with agents.

The skill runs a small shell CLI at the start of agent generations. When the configured interval has elapsed since the last time the user acknowledged drinking water, the agent prepends a short reminder block before continuing the user's actual task. Once the user confirms they drank water, the CLI records it in a local state file and suppresses reminders until the interval elapses again.

## Install With skills.sh

After pushing this repo to GitHub:

```bash
npx skills add afeefuddin/hydrate --skill hydrate -g -a codex
```

Or install from the direct GitHub path:

```bash
npx skills add https://github.com/afeefuddin/hydrate/tree/main/skills/hydrate -g -a codex
```

For other supported agents, replace `codex` with the target agent or omit `-a codex` and let the CLI prompt.

## Install With Codex Skill Installer

After pushing this repo to GitHub, install with:

```bash
python3 ~/.codex/skills/.system/skill-installer/scripts/install-skill-from-github.py \
  --repo afeefuddin/hydrate \
  --path skills/hydrate
```

Then restart Codex so the skill is picked up.

## Discoverability

The repo uses the standard `skills/<name>/SKILL.md` layout, so `skills.sh` can discover it:

```bash
npx skills add afeefuddin/hydrate --list
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

## Configure

The skill stores local state in:

```text
~/.local/share/hydrate/state
```

Common settings:

```bash
sh ~/.agents/skills/hydrate/scripts/hydrate.sh config set timezone Asia/Kolkata
sh ~/.agents/skills/hydrate/scripts/hydrate.sh config set reminder_interval_minutes 120
sh ~/.agents/skills/hydrate/scripts/hydrate.sh config set default_drink_ml 250
```

## CLI

Runtime commands:

```bash
sh ~/.agents/skills/hydrate/scripts/hydrate.sh init
sh ~/.agents/skills/hydrate/scripts/hydrate.sh check --json
sh ~/.agents/skills/hydrate/scripts/hydrate.sh drink --json
sh ~/.agents/skills/hydrate/scripts/hydrate.sh drink --amount 500 --json
sh ~/.agents/skills/hydrate/scripts/hydrate.sh status
sh ~/.agents/skills/hydrate/scripts/hydrate.sh config list
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
sh -n skills/hydrate/scripts/hydrate.sh
python3 ~/.codex/skills/.system/skill-creator/scripts/quick_validate.py skills/hydrate
```

The validator requires `PyYAML` in the Python environment. Runtime does not require Python or SQLite.
