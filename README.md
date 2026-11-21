# claude-powerline

A custom status line for [Claude Code](https://claude.ai/code) that shows
context usage, subscription usage bars, and estimated API-equivalent costs.

## What it does

Claude Code lets you supply a shell script that renders a prompt-style status
line after each response. This repo provides that script, backed by a small
Python helper that estimates rolling API-equivalent costs from local session
history.

The status line looks like:

```text
user@host:~/Projects/my-project (main) | Claude Sonnet 4.6 | ctx: 42% | session API equiv. (est.): $0.0312 | 5h API equiv. (est.): ████░░░░░░ $1.23 | 7d API equiv. (est.): ██░░░░░░░░ $8.45
```

**Fields:**

| Field | Source | Notes |
|---|---|---|
| `user@host:dir` | Shell / JSON | Coloured prompt-style prefix |
| `(branch)` | `git symbolic-ref` | Hidden when not in a git repo |
| Model name | Status line JSON | e.g. `Claude Sonnet 4.6` |
| `ctx: N%` | Status line JSON | Context window consumption |
| `session API equiv. (est.): $N` | Status line JSON | Claude Code’s estimate for the current session |
| `5h API equiv. (est.): ▓▓▓░░ $N` | JSON + `costs.py` | Subscription usage bar + rolling 5-hour estimate |
| `7d API equiv. (est.): ▓▓░░░ $N` | JSON + `costs.py` | Subscription usage bar + rolling 7-day estimate |

The 5h/7d figures are derived from Claude Code's local JSONL session files
(`~/.claude/projects/**/*.jsonl`) and cached for 2 minutes to keep the status
line fast.

Dollar figures estimate the token cost at API rates; they are not subscription
charges. Bars come from Anthropic’s subscription usage percentages. The rolling
dollar windows do not necessarily match the bars’ reset periods.

## Files

- **`statusline-command.sh`** — the status line renderer, called by Claude Code
  on each update
- **`costs.py`** — scans session JSONL files and returns rolling spend figures;
  called by the shell script with a 2-minute file cache

## Installation

1. Copy the files from this repo into `~/.claude/`:

   ```sh
   cp statusline-command.sh ~/.claude/
   cp costs.py ~/.claude/
   chmod +x ~/.claude/statusline-command.sh
   ```

2. Tell Claude Code to use the script. In `~/.claude/settings.json`:

   ```json
   {
     "statusLine": {
       "type": "command",
       "command": "~/.claude/statusline-command.sh"
     }
   }
   ```

3. Restart Claude Code. The custom status line appears at the bottom of the
   interface.

## How costs are calculated

### Data source

Claude Code writes conversation records to JSONL files under
`~/.claude/projects/**/*.jsonl`. Each line is a JSON object; `costs.py` only
reads records where `type == "assistant"`, which are the ones that carry token
usage data. Multiple records can share one API response’s usage, for example
when thinking, text and tool blocks are stored separately. The scanner counts
each API `message.id` once across all files, using the latest timestamped record.
If the message ID is absent, it uses the record UUID, or counts the line
individually when neither identifier is available.

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
| `cache_creation_input_tokens` | Tokens written into a prompt cache | 1.25× input for 5m; 2× for 1h |
| `cache_read_input_tokens` | Tokens served from an existing cache | Model-specific discounted rate |
| `output_tokens` | Tokens generated in the response | Full output price (~5× input) |

Cache hits (`cache_read_input_tokens`) cost between 2.5% and 10% of the input
price, depending on the model. Claude Code uses prompt caching heavily to
reuse conversation context, so a typical session has a high ratio of cache
reads to fresh input tokens.

### Cost formula

For each unique response:

```text
cost = (input_tokens                    × input_price
      + cache_creation_5m_tokens        × cache_write_5m_price
      + cache_creation_1h_tokens        × cache_write_1h_price
      + cache_read_input_tokens         × cache_read_price
      + output_tokens                   × output_price) ÷ 1,000,000
```

Prices are USD per million tokens, checked on 21 November 2026. Source:
[platform.claude.com/docs/en/about-claude/pricing](https://platform.claude.com/docs/en/about-claude/pricing)

| Model | Input | Cache write 5m | Cache write 1h | Cache read | Output |
|---|---|---|---|---|---|
| claude-fable-5-2 / claude-mythos-5-2 | $8.00 | $10.00 | $16.00 | $0.20 | $40.00 |
| claude-sonnet-5-5 | $2.00 | $2.50 | $4.00 | $0.10 | $10.00 |
| claude-haiku-5-5 (prompt ≤100k tokens) | $0.10 | $0.125 | $0.20 | $0.01 | $0.50 |
| claude-haiku-5-5 (prompt >100k tokens) | $0.50 | $0.625 | $1.00 | $0.05 | $2.50 |
| claude-fable-5-1 / claude-mythos-5-1 | $10.00 | $12.50 | $20.00 | $0.25 | $50.00 |
| claude-fable-5 / claude-mythos-5 | $10.00 | $12.50 | $20.00 | $1.00 | $50.00 |
| claude-opus-5-5 | $4.00 | $5.00 | $8.00 | $0.20 | $20.00 |
| claude-opus-5, claude-opus-4-5 through 4-8 | $5.00 | $6.25 | $10.00 | $0.50 | $25.00 |
| claude-opus-4 / claude-opus-4-1 (retired) | $15.00 | $18.75 | $30.00 | $1.50 | $75.00 |
| claude-sonnet-5 | $2.00 | $2.50 | $4.00 | $0.20 | $10.00 |
| claude-sonnet-4 / 4-5 / 4-6 | $3.00 | $3.75 | $6.00 | $0.30 | $15.00 |
| claude-haiku-4-5 | $1.00 | $1.25 | $2.00 | $0.10 | $5.00 |
| claude-3-5-haiku (retired) | $0.80 | $1.00 | $1.60 | $0.08 | $4.00 |

Cache writes come in two durations: 5-minute (1.25× input price) and 1-hour
(2× input price). Cache reads are 0.1× input price, except on Fable and
Mythos 5.1 and 5.2 (0.025×), Opus 5.5 (0.05×) and Sonnet 5.5 (0.05×).
The JSONL records include a `cache_creation` breakdown with
`ephemeral_5m_input_tokens` and `ephemeral_1h_input_tokens`. Claude Code uses
1-hour cache writes for session context. For older JSONL records that lack this
breakdown, all cache writes are assumed 5-minute. This underestimates the
cache-write component by 37.5% if those writes actually had a 1-hour duration.

Haiku 5.5’s prompt threshold counts fresh input, cache writes and cache reads.
The higher rate applies to the whole request. Responses marked `speed: "fast"`
use a 2× multiplier; `inference_geo: "us"` adds a 1.1× multiplier. These
multipliers also apply to cache tokens.

### Rolling windows

The 5h and 7d figures sum the cost of each unique response whose `timestamp` falls
within the window ending now. Future timestamps are excluded. Both windows
are computed in a single pass over the JSONL files. Symlinked files are skipped. Lines that fail to parse are
skipped silently. The scan includes all local projects and subagents.

### Model ID resolution

Claude Code records model IDs such as `claude-haiku-4-5-20251001`.
`get_pricing()` accepts an exact model ID or a known ID followed by an
8-digit snapshot date. New versions cannot match an older version’s rates.

An unrecognised model with billable usage makes each affected window display
`unknown`. The helper reports the model IDs on stderr; the status line suppresses
stderr. Run `python3 ~/.claude/costs.py` to see which rates are missing. Unknown
results are not cached. Synthetic records with zero token usage cost zero.

### Limitations and accuracy

- **This is an estimate.** The source of truth for billing is Anthropic's
  usage dashboard, not local JSONL files.
- **Pricing table can go stale.** If Anthropic changes prices or you use a
  model not in the table, update the `PRICING` dict in `costs.py`. Unknown
  models display `unknown` rather than a partial or guessed total.
- **The session cost field** (`session API equiv. (est.): $N`) comes from Claude Code's own JSON
  feed rather than `costs.py`, so it may use a different accounting method.
- **Coverage.** Only locally stored transcripts are counted. Missing history,
  background requests absent from transcripts and other devices are not covered.
  Tool fees, batch discounts, negotiated prices, taxes and billing credits are
  outside this token estimate.
- **Clock skew.** Timestamps in the JSONL files are UTC. The rolling window
  cutoff is also computed in UTC, so local timezone has no effect.

## Cache

Rolling cost figures are cached at `~/.cache/claude/costs_v2_50-1680.json` for 2
minutes. Delete this file to force an immediate recalculation.

## Development checks

Run the accounting regression tests and check shell syntax:

```sh
python3 -m unittest discover -s tests -v
sh -n statusline-command.sh
```
