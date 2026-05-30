#!/usr/bin/env python3
"""Estimate Claude Code API cost from session JSONL files for a given time window."""

import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

# USD per million tokens
PRICING = {
    "claude-sonnet-4-6": {"input": 3.00, "cache_write": 3.75, "cache_read": 0.30, "output": 15.00},
    "claude-sonnet-4-5": {"input": 3.00, "cache_write": 3.75, "cache_read": 0.30, "output": 15.00},
    "claude-opus-4-8":   {"input": 15.00, "cache_write": 18.75, "cache_read": 1.50, "output": 75.00},
    "claude-opus-4-5":   {"input": 15.00, "cache_write": 18.75, "cache_read": 1.50, "output": 75.00},
    "claude-haiku-4-5":  {"input": 0.80, "cache_write": 1.00, "cache_read": 0.08, "output": 4.00},
}
DEFAULT_PRICING = PRICING["claude-sonnet-4-6"]


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
    return (
        usage.get("input_tokens", 0) * p["input"] / m
        + usage.get("cache_creation_input_tokens", 0) * p["cache_write"] / m
        + usage.get("cache_read_input_tokens", 0) * p["cache_read"] / m
        + usage.get("output_tokens", 0) * p["output"] / m
    )


def costs_for_windows(windows_hours: list[float]) -> list[float]:
    """Scan JSONL files once and return total cost for each time window."""
    projects_dir = Path.home() / ".claude" / "projects"
    now = datetime.now(timezone.utc).timestamp()
    cutoffs = [now - h * 3600 for h in windows_hours]
    totals = [0.0] * len(windows_hours)

    for jsonl_file in projects_dir.rglob("*.jsonl"):
        if jsonl_file.is_symlink():
            continue
        try:
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
