#!/bin/sh

set -eu

STATE_FILE="${HYDRATE_STATE_FILE:-$HOME/.local/share/hydrate/state}"

json=false
amount=""
command=""
config_command=""
config_key=""
config_value=""

while [ "$#" -gt 0 ]; do
  case "$1" in
    --json)
      json=true
      shift
      ;;
    --amount)
      amount="${2:-}"
      [ -n "$amount" ] || { echo "missing --amount value" >&2; exit 2; }
      shift 2
      ;;
    --state)
      STATE_FILE="${2:-}"
      [ -n "$STATE_FILE" ] || { echo "missing --state value" >&2; exit 2; }
      shift 2
      ;;
    --db)
      # Compatibility with older Hydrate releases that used SQLite.
      STATE_FILE="${2:-}"
      [ -n "$STATE_FILE" ] || { echo "missing --db value" >&2; exit 2; }
      shift 2
      ;;
    init|check|drink|status|config)
      command="$1"
      shift
      break
      ;;
    *)
      echo "unknown option: $1" >&2
      exit 2
      ;;
  esac
done

if [ -z "$command" ]; then
  echo "usage: hydrate.sh [--state path] <init|check|drink|status|config>" >&2
  exit 2
fi

while [ "$#" -gt 0 ]; do
  case "$1" in
    --json)
      json=true
      shift
      ;;
    --amount)
      amount="${2:-}"
      [ -n "$amount" ] || { echo "missing --amount value" >&2; exit 2; }
      shift 2
      ;;
    --state|--db)
      STATE_FILE="${2:-}"
      [ -n "$STATE_FILE" ] || { echo "missing $1 value" >&2; exit 2; }
      shift 2
      ;;
    *)
      break
      ;;
  esac
done

if [ "$command" = "config" ]; then
  config_command="${1:-}"
  [ -n "$config_command" ] || { echo "usage: hydrate.sh config <list|get|set>" >&2; exit 2; }
  shift
  case "$config_command" in
    list) ;;
    get)
      config_key="${1:-}"
      [ -n "$config_key" ] || { echo "usage: hydrate.sh config get <key>" >&2; exit 2; }
      shift
      ;;
    set)
      config_key="${1:-}"
      config_value="${2:-}"
      [ -n "$config_key" ] && [ -n "$config_value" ] || {
        echo "usage: hydrate.sh config set <key> <value>" >&2
        exit 2
      }
      shift 2
      ;;
    *)
      echo "unknown config command: $config_command" >&2
      exit 2
      ;;
  esac
  while [ "$#" -gt 0 ]; do
    case "$1" in
      --json)
        json=true
        shift
        ;;
      *)
        echo "unknown option: $1" >&2
        exit 2
        ;;
    esac
  done
fi

state_dir=$(dirname "$STATE_FILE")
mkdir -p "$state_dir"

timezone="local"
reminder_interval_minutes="120"
default_drink_ml="250"
last_drink_at_epoch=""
last_drink_at=""
last_amount_ml=""
pending="false"
pending_since=""
pending_since_epoch=""
suggested_amount_ml=""
last_reminder_at=""
last_reminder_at_epoch=""

if [ -f "$STATE_FILE" ]; then
  # shellcheck disable=SC1090
  . "$STATE_FILE"
fi

is_positive_int() {
  case "$1" in
    ''|*[!0-9]*) return 1 ;;
    0) return 1 ;;
    *) return 0 ;;
  esac
}

require_positive_int() {
  key="$1"
  value="$2"
  if ! is_positive_int "$value"; then
    echo "$key must be greater than zero" >&2
    exit 2
  fi
}

date_with_tz() {
  fmt="$1"
  if [ "$timezone" = "local" ]; then
    date "$fmt"
  else
    TZ="$timezone" date "$fmt"
  fi
}

now_epoch() {
  date_with_tz "+%s"
}

now_iso() {
  raw=$(date_with_tz "+%Y-%m-%dT%H:%M:%S%z")
  case "$raw" in
    *[+-][0-9][0-9][0-9][0-9])
      printf "%s" "$raw" | sed 's/\(..\)$/:\1/'
      ;;
    *)
      printf "%s" "$raw"
      ;;
  esac
}

iso_from_epoch() {
  epoch="$1"
  if [ "$timezone" = "local" ]; then
    raw=$(date -r "$epoch" "+%Y-%m-%dT%H:%M:%S%z" 2>/dev/null || date -d "@$epoch" "+%Y-%m-%dT%H:%M:%S%z")
  else
    raw=$(TZ="$timezone" date -r "$epoch" "+%Y-%m-%dT%H:%M:%S%z" 2>/dev/null || TZ="$timezone" date -d "@$epoch" "+%Y-%m-%dT%H:%M:%S%z")
  fi
  case "$raw" in
    *[+-][0-9][0-9][0-9][0-9])
      printf "%s" "$raw" | sed 's/\(..\)$/:\1/'
      ;;
    *)
      printf "%s" "$raw"
      ;;
  esac
}

quote_state() {
  printf "'%s'" "$(printf "%s" "$1" | sed "s/'/'\\\\''/g")"
}

write_state() {
  tmp="$STATE_FILE.$$"
  {
    printf "timezone=%s\n" "$(quote_state "$timezone")"
    printf "reminder_interval_minutes=%s\n" "$(quote_state "$reminder_interval_minutes")"
    printf "default_drink_ml=%s\n" "$(quote_state "$default_drink_ml")"
    printf "last_drink_at_epoch=%s\n" "$(quote_state "$last_drink_at_epoch")"
    printf "last_drink_at=%s\n" "$(quote_state "$last_drink_at")"
    printf "last_amount_ml=%s\n" "$(quote_state "$last_amount_ml")"
    printf "pending=%s\n" "$(quote_state "$pending")"
    printf "pending_since=%s\n" "$(quote_state "$pending_since")"
    printf "pending_since_epoch=%s\n" "$(quote_state "$pending_since_epoch")"
    printf "suggested_amount_ml=%s\n" "$(quote_state "$suggested_amount_ml")"
    printf "last_reminder_at=%s\n" "$(quote_state "$last_reminder_at")"
    printf "last_reminder_at_epoch=%s\n" "$(quote_state "$last_reminder_at_epoch")"
  } > "$tmp"
  mv "$tmp" "$STATE_FILE"
}

json_string() {
  if [ -z "$1" ]; then
    printf "null"
  else
    printf '"%s"' "$(printf "%s" "$1" | sed 's/\\/\\\\/g; s/"/\\"/g')"
  fi
}

next_due_epoch() {
  now="$1"
  if [ -n "$last_drink_at_epoch" ]; then
    printf "%s" "$((last_drink_at_epoch + reminder_interval_minutes * 60))"
  else
    printf "%s" "$now"
  fi
}

payload() {
  due="$1"
  reason="$2"
  suggested="$3"
  message="$4"
  pending_value="${5:-$pending}"
  now="$6"
  next_due="$7"
  seconds_until_due="$8"
  if [ "$json" = true ]; then
    cat <<EOF
{
  "due": $due,
  "last_drink": {
    "amount_ml": ${last_amount_ml:-null},
    "drank_at": $(json_string "$last_drink_at")
  },
  "message": "$(printf "%s" "$message" | sed 's/\\/\\\\/g; s/"/\\"/g')",
  "next_due_at": "$(iso_from_epoch "$next_due")",
  "now": "$(iso_from_epoch "$now")",
  "pending": $pending_value,
  "reason": "$reason",
  "seconds_until_due": $seconds_until_due,
  "settings": {
    "default_drink_ml": $default_drink_ml,
    "reminder_interval_minutes": $reminder_interval_minutes,
    "timezone": "$timezone"
  },
  "suggested_amount_ml": $suggested
}
EOF
  elif [ "$due" = true ]; then
    printf "%s\n" "$message"
  else
    minutes=$((seconds_until_due / 60))
    [ "$minutes" -gt 0 ] || minutes=1
    printf "No reminder due. Next reminder in about %s minute(s).\n" "$minutes"
  fi
}

require_positive_int "reminder_interval_minutes" "$reminder_interval_minutes"
require_positive_int "default_drink_ml" "$default_drink_ml"

case "$command" in
  init)
    write_state
    if [ "$json" = true ]; then
      printf '{\n  "initialized": true,\n  "state_file": "%s"\n}\n' "$STATE_FILE"
    else
      printf "Initialized %s\n" "$STATE_FILE"
    fi
    ;;
  check)
    now=$(now_epoch)
    next_due=$(next_due_epoch "$now")
    seconds_until_due=$((next_due - now))
    [ "$seconds_until_due" -gt 0 ] || seconds_until_due=0

    if [ "$pending" = "true" ]; then
      [ -n "$suggested_amount_ml" ] || suggested_amount_ml="$default_drink_ml"
      last_reminder_at_epoch="$now"
      last_reminder_at="$(iso_from_epoch "$now")"
      write_state
      payload true "pending_until_confirmed" "$suggested_amount_ml" "DRINK WATER NOW: ${suggested_amount_ml}ml" true "$now" "$next_due" "$seconds_until_due"
    elif [ "$seconds_until_due" -le 0 ]; then
      suggested_amount_ml="$default_drink_ml"
      pending="true"
      pending_since_epoch="$now"
      pending_since="$(iso_from_epoch "$now")"
      last_reminder_at_epoch="$now"
      last_reminder_at="$pending_since"
      write_state
      payload true "interval_elapsed" "$suggested_amount_ml" "DRINK WATER NOW: ${suggested_amount_ml}ml" true "$now" "$next_due" "$seconds_until_due"
    else
      payload false "waiting_for_interval" 0 "" false "$now" "$next_due" "$seconds_until_due"
    fi
    ;;
  drink)
    now=$(now_epoch)
    if [ -n "$amount" ]; then
      require_positive_int "amount" "$amount"
      consumed="$amount"
    elif [ -n "$suggested_amount_ml" ]; then
      consumed="$suggested_amount_ml"
    else
      consumed="$default_drink_ml"
    fi
    last_drink_at_epoch="$now"
    last_drink_at="$(iso_from_epoch "$now")"
    last_amount_ml="$consumed"
    pending="false"
    pending_since=""
    pending_since_epoch=""
    suggested_amount_ml=""
    last_reminder_at=""
    last_reminder_at_epoch=""
    write_state
    next_due=$(next_due_epoch "$now")
    seconds_until_due=$((next_due - now))
    [ "$seconds_until_due" -gt 0 ] || seconds_until_due=0
    if [ "$json" = true ]; then
      cat <<EOF
{
  "amount_ml": $consumed,
  "last_drink": {
    "amount_ml": $last_amount_ml,
    "drank_at": "$(iso_from_epoch "$last_drink_at_epoch")"
  },
  "message": "Recorded ${consumed}ml water.",
  "next_due_at": "$(iso_from_epoch "$next_due")",
  "now": "$(iso_from_epoch "$now")",
  "recorded": true,
  "seconds_until_due": $seconds_until_due,
  "settings": {
    "default_drink_ml": $default_drink_ml,
    "reminder_interval_minutes": $reminder_interval_minutes,
    "timezone": "$timezone"
  }
}
EOF
    else
      printf "Recorded %sml water.\n" "$consumed"
    fi
    ;;
  status)
    now=$(now_epoch)
    next_due=$(next_due_epoch "$now")
    seconds_until_due=$((next_due - now))
    [ "$seconds_until_due" -gt 0 ] || seconds_until_due=0
    if [ "$json" = true ]; then
      payload false "status" "${suggested_amount_ml:-0}" "" "$pending" "$now" "$next_due" "$seconds_until_due"
    else
      printf "Last drink: %s\n" "${last_drink_at:-never}"
      printf "Next reminder: %s\n" "$(iso_from_epoch "$next_due")"
      printf "Pending reminder: %s\n" "$pending"
    fi
    ;;
  config)
    case "$config_command" in
      list)
        if [ "$json" = true ]; then
          cat <<EOF
{
  "default_drink_ml": "$default_drink_ml",
  "reminder_interval_minutes": "$reminder_interval_minutes",
  "timezone": "$timezone"
}
EOF
        else
          printf "default_drink_ml=%s\nreminder_interval_minutes=%s\ntimezone=%s\n" "$default_drink_ml" "$reminder_interval_minutes" "$timezone"
        fi
        ;;
      get)
        case "$config_key" in
          default_drink_ml) value="$default_drink_ml" ;;
          reminder_interval_minutes) value="$reminder_interval_minutes" ;;
          timezone) value="$timezone" ;;
          serving_ml) value="$default_drink_ml" ;;
          minimum_interval_minutes) value="$reminder_interval_minutes" ;;
          *) echo "Unknown setting: $config_key" >&2; exit 2 ;;
        esac
        if [ "$json" = true ]; then
          printf '{\n  "%s": "%s"\n}\n' "$config_key" "$value"
        else
          printf "%s\n" "$value"
        fi
        ;;
      set)
        case "$config_key" in
          default_drink_ml|serving_ml)
            require_positive_int "default_drink_ml" "$config_value"
            default_drink_ml="$config_value"
            config_key="default_drink_ml"
            ;;
          reminder_interval_minutes|minimum_interval_minutes)
            require_positive_int "reminder_interval_minutes" "$config_value"
            reminder_interval_minutes="$config_value"
            config_key="reminder_interval_minutes"
            ;;
          timezone)
            timezone="$config_value"
            ;;
          *) echo "Unknown setting: $config_key" >&2; exit 2 ;;
        esac
        pending="false"
        pending_since=""
        pending_since_epoch=""
        suggested_amount_ml=""
        last_reminder_at=""
        last_reminder_at_epoch=""
        write_state
        if [ "$json" = true ]; then
          printf '{\n  "key": "%s",\n  "updated": true,\n  "value": "%s"\n}\n' "$config_key" "$config_value"
        else
          printf "%s=%s\n" "$config_key" "$config_value"
        fi
        ;;
    esac
    ;;
esac
