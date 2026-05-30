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

## How costs are calculated

### Data source

Claude Code writes a record for every API response to JSONL files under
`~/.claude/projects/**/*.jsonl`. Each line is a JSON object; `costs.py` only
reads records where `type == "assistant"`, which are the ones that carry token
usage data.

A typical record looks like:

```json
{
  "type": "assistant",
  "timestamp": "2026-05-31T14:23:01.456Z",
  "message": {
    "model": "claude-sonnet-4-6",
    "usage": {
      "input_tokens": 8021,
      "cache_creation_input_tokens": 1200,
      "cache_read_input_tokens": 42300,
      "output_tokens": 614
    }
  }
}
```

### Token categories

Each response reports four token counts:

| Field | What it is | Relative price |
|---|---|---|
| `input_tokens` | Tokens read fresh from the context window | Full input price |
| `cache_creation_input_tokens` | Tokens written into a prompt cache | ~1.25× input price |
| `cache_read_input_tokens` | Tokens served from an existing cache | ~0.1× input price |
| `output_tokens` | Tokens generated in the response | Full output price (~5× input) |

Cache hits (`cache_read_input_tokens`) are cheap — about 10% of the input
price. Prompt caching is used heavily by Claude Code to avoid re-sending the
full conversation context on every turn, so a typical session has a high ratio
of cache reads to fresh input tokens.

### Cost formula

For each response:

```
cost = (input_tokens             × input_price
      + cache_creation_input_tokens × cache_write_price
      + cache_read_input_tokens  × cache_read_price
      + output_tokens            × output_price) ÷ 1,000,000
```

Prices are per million tokens. The current table (USD):

| Model | Input | Cache write | Cache read | Output |
|---|---|---|---|---|
| claude-sonnet-4-6 / 4-5 | $3.00 | $3.75 | $0.30 | $15.00 |
| claude-opus-4-8 / 4-5 | $15.00 | $18.75 | $1.50 | $75.00 |
| claude-haiku-4-5 | $0.80 | $1.00 | $0.08 | $4.00 |

### Rolling windows

The 5h and 7d figures sum the cost of every response whose `timestamp` falls
within the window ending now. Both windows are computed in a single pass over
the JSONL files. Symlinked files are skipped. Lines that fail to parse are
skipped silently.

### Model ID resolution

Claude Code records full versioned model IDs like `claude-haiku-4-5-20251001`.
`get_pricing()` resolves these to a pricing row with:

1. Exact match against the `PRICING` dict.
2. Prefix match — `claude-haiku-4-5-20251001` matches `claude-haiku-4-5`.
3. Fallback to Sonnet 4.6 rates for any unrecognised model.

### Limitations and accuracy

- **This is an estimate.** The source of truth for billing is Anthropic's
  usage dashboard, not local JSONL files.
- **Pricing table can go stale.** If Anthropic changes prices or you use a
  model not in the table, update the `PRICING` dict in `costs.py`. An unknown
  model falls back to Sonnet rates, which will overstate costs for Haiku and
  understate them for Opus.
- **The session cost field** (`session: $N`) comes from Claude Code's own JSON
  feed rather than `costs.py`, so it may use a different accounting method.
- **Clock skew.** Timestamps in the JSONL files are UTC. The rolling window
  cutoff is also computed in UTC, so local timezone has no effect.

## Cache

Rolling cost figures are cached at `~/.cache/claude/costs_50-1680.json` for 2
minutes. Delete this file to force an immediate recalculation.
