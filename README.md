# claude-powerline

A custom status line for [Claude Code](https://claude.ai/code) that shows
context usage, session cost, and rolling API spend at a glance.

## What it does

Claude Code lets you supply a shell script that renders a prompt-style status
line after each response. This repo provides that script, backed by a small
Python helper that calculates rolling API costs from your local session history.

The status line looks like:

```
user@host:~/Projects/my-project (main) | Claude Sonnet 4.6 | ctx: 42% | session: $0.0312 | 5h: ████░░░░░░ $1.23 | 7d: ██░░░░░░░░ $8.45
```

**Fields:**

| Field | Source | Notes |
|---|---|---|
| `user@host:dir` | Shell / JSON | Coloured prompt-style prefix |
| `(branch)` | `git symbolic-ref` | Hidden when not in a git repo |
| Model name | Status line JSON | e.g. `Claude Sonnet 4.6` |
| `ctx: N%` | Status line JSON | Context window consumption |
| `session: $N` | Status line JSON | Cost for the current session |
| `5h: ▓▓▓░░ $N` | `costs.py` | Rolling 5-hour spend + bar |
| `7d: ▓▓░░░ $N` | `costs.py` | Rolling 7-day spend + bar |

The 5h/7d figures are derived from Claude Code's local JSONL session files
(`~/.claude/projects/**/*.jsonl`) and cached for 2 minutes to keep the status
line fast.

## Files

- **`statusline-command.sh`** — the status line renderer, called by Claude Code
  on each update
- **`costs.py`** — scans session JSONL files and returns rolling spend figures;
  called by the shell script with a 2-minute file cache

## Installation

1. Copy the files into `~/.claude/`:

   ```sh
   cp statusline-command.sh ~/.claude/
   cp costs.py ~/.claude/
   chmod +x ~/.claude/statusline-command.sh
   ```

2. Tell Claude Code to use the script. In `~/.claude/settings.json`:

   ```json
   {
     "statusCommand": "~/.claude/statusline-command.sh"
   }
   ```

3. Open (or restart) Claude Code — the custom status line appears immediately.

## Pricing

`costs.py` has a hardcoded pricing table for current Claude models. If
Anthropic changes pricing or releases new models, update the `PRICING` dict at
the top of the file. Model IDs with date suffixes (e.g.
`claude-haiku-4-5-20251001`) are matched by prefix, so only the base model ID
needs to be in the table.

## Cache

Rolling cost figures are cached at `~/.cache/claude/costs_50-1680.json` for 2
minutes. Delete this file to force an immediate recalculation.
