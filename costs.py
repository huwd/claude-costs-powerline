#!/usr/bin/env python3
"""Estimate Claude Code API cost from session JSONL files for a given time window."""

import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

# USD per million tokens
# Source: https://platform.claude.com/docs/en/about-claude/pricing
# Cache writes have two tiers: 5-minute (1.25× input) and 1-hour (2× input).
# Claude Code predominantly uses 1-hour cache writes.
PRICING = {
    # Fable 5 / Mythos 5: $10 / $50
    "claude-fable-5": {"input": 10.00, "cache_write_5m": 12.50, "cache_write_1h": 20.00, "cache_read": 1.00, "output": 50.00},
    "claude-mythos-5": {"input": 10.00, "cache_write_5m": 12.50, "cache_write_1h": 20.00, "cache_read": 1.00, "output": 50.00},
    # Opus 5 and Opus 4.6-4.8: $5 / $25
    "claude-opus-5": {"input": 5.00, "cache_write_5m":  6.25, "cache_write_1h": 10.00, "cache_read": 0.50, "output": 25.00},
    "claude-opus-4-8": {"input": 5.00, "cache_write_5m":  6.25, "cache_write_1h": 10.00, "cache_read": 0.50, "output": 25.00},
    "claude-opus-4-7": {"input": 5.00, "cache_write_5m":  6.25, "cache_write_1h": 10.00, "cache_read": 0.50, "output": 25.00},
    "claude-opus-4-6": {"input": 5.00, "cache_write_5m":  6.25, "cache_write_1h": 10.00, "cache_read": 0.50, "output": 25.00},
    "claude-opus-4-5": {"input": 5.00, "cache_write_5m":  6.25, "cache_write_1h": 10.00, "cache_read": 0.50, "output": 25.00},
    # Opus 4.1 and earlier: $15 / $75
    "claude-opus-4-1": {"input": 15.00, "cache_write_5m": 18.75, "cache_write_1h": 30.00, "cache_read": 1.50, "output": 75.00},
    # Sonnet 5: $2 / $10
    "claude-sonnet-5": {"input": 2.00, "cache_write_5m": 2.50, "cache_write_1h":  4.00, "cache_read": 0.20, "output": 10.00},
    # Sonnet 4.5 / 4.6: $3 / $15
    "claude-sonnet-4-6": {"input": 3.00, "cache_write_5m": 3.75, "cache_write_1h":  6.00, "cache_read": 0.30, "output": 15.00},
    "claude-sonnet-4-5": {"input": 3.00, "cache_write_5m": 3.75, "cache_write_1h":  6.00, "cache_read": 0.30, "output": 15.00},
    # Haiku 4.5: $1 / $5
    "claude-haiku-4-5": {"input": 1.00, "cache_write_5m":  1.25, "cache_write_1h":  2.00, "cache_read": 0.10, "output":  5.00},
    # Haiku 3.5 (retired): $0.80 / $4
    "claude-haiku-3-5": {"input": 0.80, "cache_write_5m":  1.00, "cache_write_1h":  1.60, "cache_read": 0.08, "output":  4.00},
}
DEFAULT_PRICING = PRICING["claude-sonnet-5"]


def get_pricing(model: str) -> dict:
    if model in PRICING:
        return PRICING[model]
    for key in PRICING:
        if model.startswith(key):
            return PRICING[key]
    return DEFAULT_PRICING


def message_cost(model: str, usage: dict) -> float:
    p = get_pricing(model)
    m = 1_000_000
    # Use per-tier cache creation breakdown when available (present in newer JSONL records).
    # Falls back to the aggregate field assuming 5-minute rate for older records.
    cache_creation = usage.get("cache_creation", {})
    cache_5m = cache_creation.get("ephemeral_5m_input_tokens")
    cache_1h = cache_creation.get("ephemeral_1h_input_tokens")
    if cache_5m is None and cache_1h is None:
        cache_5m = usage.get("cache_creation_input_tokens", 0)
        cache_1h = 0
    else:
        cache_5m = cache_5m or 0
        cache_1h = cache_1h or 0
    return (
        usage.get("input_tokens", 0) * p["input"] / m
        + cache_5m * p["cache_write_5m"] / m
        + cache_1h * p["cache_write_1h"] / m
        + usage.get("cache_read_input_tokens", 0) * p["cache_read"] / m
        + usage.get("output_tokens", 0) * p["output"] / m
    )


def costs_for_windows(windows_hours: list[float]) -> list[float]:
    """Scan JSONL files once and return total cost for each time window."""
    projects_dir = Path.home() / ".claude" / "projects"
    now = datetime.now(timezone.utc).timestamp()
    cutoffs = [now - h * 3600 for h in windows_hours]
    oldest_cutoff = min(cutoffs)
    totals = [0.0] * len(windows_hours)

    for jsonl_file in projects_dir.rglob("*.jsonl"):
        if jsonl_file.is_symlink():
            continue
        try:
            if jsonl_file.stat().st_mtime < oldest_cutoff:
                continue
            for line in jsonl_file.open():
                try:
                    obj = json.loads(line)
                    if obj.get("type") != "assistant":
                        continue
                    ts = obj.get("timestamp")
                    if not ts:
                        continue
                    ts_val = datetime.fromisoformat(ts.replace("Z", "+00:00")).timestamp()
                    msg = obj.get("message", {})
                    usage = msg.get("usage")
                    if not usage:
                        continue
                    cost = message_cost(msg.get("model", ""), usage)
                    for i, cutoff in enumerate(cutoffs):
                        if ts_val >= cutoff:
                            totals[i] += cost
                except (json.JSONDecodeError, ValueError):
                    continue
        except OSError:
            continue

    return totals


def format_cost(cost: float) -> str:
    if cost < 0.01:
        return f"${cost:.4f}"
    if cost < 1.0:
        return f"${cost:.3f}"
    return f"${cost:.2f}"


def cached_costs(windows_hours: list[float]) -> list[float]:
    cache_key = "-".join(str(int(h * 10)) for h in windows_hours)
    cache_dir = Path.home() / ".cache" / "claude"
    cache_dir.mkdir(parents=True, exist_ok=True)
    cache_file = cache_dir / f"costs_{cache_key}.json"
    if cache_file.exists() and (time.time() - cache_file.stat().st_mtime) < 120:
        return json.loads(cache_file.read_text())["costs"]
    costs = costs_for_windows(windows_hours)
    cache_file.write_text(json.dumps({"costs": costs}))
    return costs


def main():
    if len(sys.argv) == 1:
        five_h, seven_d = cached_costs([5.0, 168.0])
        print(f"{format_cost(five_h)} {format_cost(seven_d)}")
    else:
        try:
            hours = float(sys.argv[1])
        except ValueError:
            print(f"Usage: {sys.argv[0]} [hours]", file=sys.stderr)
            sys.exit(1)
        print(format_cost(cached_costs([hours])[0]))


if __name__ == "__main__":
    main()
