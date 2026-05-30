#!/bin/sh
input=$(cat)

# Strip non-printable and escape characters to prevent terminal injection
sanitize() { printf '%s' "$1" | tr -d '\033\007\001-\037\177'; }

# Render a 10-char progress bar from a percentage value
bar() {
  pct=$1
  filled=$(awk -v pct="$pct" 'BEGIN { printf "%.0f", pct * 10 / 100 }')
  empty=$((10 - filled))
  i=0; while [ $i -lt $filled ]; do printf '█'; i=$((i+1)); done
  i=0; while [ $i -lt $empty  ]; do printf '░'; i=$((i+1)); done
}

user=$(whoami)
host=$(hostname -s)

eval "$(echo "$input" | jq -r '
  "dir="             + (.workspace.current_dir // .cwd | @sh),
  "model="           + (.model.display_name // "" | @sh),
  "used_pct="        + ((.context_window.used_percentage // "") | tostring),
  "five_hour_pct="   + ((.rate_limits.five_hour.used_percentage // "") | tostring),
  "five_hour_reset=" + ((.rate_limits.five_hour.resets_at // "") | tostring),
  "seven_day_pct="   + ((.rate_limits.seven_day.used_percentage // "") | tostring),
  "seven_day_reset=" + ((.rate_limits.seven_day.resets_at // "") | tostring),
  "session_cost="    + ((.cost.total_cost_usd // "") | tostring)
')"

home="$HOME"
short_dir="${dir#"$home"}"
[ "$short_dir" != "$dir" ] && short_dir="~$short_dir"

# Session cost from status line JSON; 5h/7d costs from JSONL history (cached 2 min)
costs=$(python3 ~/.claude/costs.py 2>/dev/null)
five_hour_cost=$(echo "$costs" | cut -d' ' -f1)
seven_day_cost=$(echo "$costs" | cut -d' ' -f2)

# Git branch (skip optional locks to avoid contention)
branch=""
if [ -d "$dir/.git" ] || git -C "$dir" rev-parse --git-dir >/dev/null 2>&1; then
  branch=$(git -C "$dir" --no-optional-locks symbolic-ref --short HEAD 2>/dev/null)
fi

short_dir=$(sanitize "$short_dir")
model=$(sanitize "$model")
branch=$(sanitize "$branch")
five_hour_cost=$(sanitize "$five_hour_cost")
seven_day_cost=$(sanitize "$seven_day_cost")

# Print a rate-limit block: red bar + reset time if over limit, normal bar + cost otherwise
rate_block() {
  pct=$1
  reset_ts=$2
  cost=$3
  pct_int=$(printf "%.0f" "$pct")
  if [ "$pct_int" -ge 100 ]; then
    reset_fmt=""
    if [ -n "$reset_ts" ]; then
      reset_fmt=" resets $(date -d "@$reset_ts" "+%H:%M" 2>/dev/null)"
    fi
    printf " \033[0;31m%s%s\033[0m" "$(bar "$pct")" "$reset_fmt"
  else
    printf " %s" "$(bar "$pct")"
    [ -n "$cost" ] && printf " %s" "$cost"
  fi
}

# Build the status line
printf "\033[0;32m%s@%s\033[0m:\033[0;34m%s\033[0m" "$user" "$host" "$short_dir"

if [ -n "$branch" ]; then
  printf " \033[0;33m(%s)\033[0m" "$branch"
fi

if [ -n "$model" ]; then
  printf " | %s" "$model"
fi

if [ -n "$used_pct" ]; then
  printf " | ctx: %.0f%%" "$used_pct"
fi

if [ -n "$session_cost" ]; then
  printf " | session: \$%.4f" "$session_cost"
fi

if [ -n "$five_hour_pct" ] || [ -n "$five_hour_cost" ]; then
  printf " | 5h:"
  [ -n "$five_hour_pct" ] && rate_block "$five_hour_pct" "$five_hour_reset" "$five_hour_cost"
  [ -z "$five_hour_pct" ] && [ -n "$five_hour_cost" ] && printf " %s" "$five_hour_cost"
fi

if [ -n "$seven_day_pct" ] || [ -n "$seven_day_cost" ]; then
  printf " | 7d:"
  [ -n "$seven_day_pct" ] && rate_block "$seven_day_pct" "$seven_day_reset" "$seven_day_cost"
  [ -z "$seven_day_pct" ] && [ -n "$seven_day_cost" ] && printf " %s" "$seven_day_cost"
fi
