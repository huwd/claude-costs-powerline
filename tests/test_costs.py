import contextlib
import io
import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

import costs


class PricingTests(unittest.TestCase):
    def test_each_token_category_and_cache_duration(self):
        usage = {
            "input_tokens": 100,
            "output_tokens": 1000,
            "cache_read_input_tokens": 100_000,
            "cache_creation_input_tokens": 3000,
            "cache_creation": {
                "ephemeral_5m_input_tokens": 2000,
                "ephemeral_1h_input_tokens": 1000,
            },
        }
        self.assertAlmostEqual(costs.message_cost("claude-opus-5-5", usage), 0.0584)

    def test_current_model_rates(self):
        for model, expected in [
            ("claude-sonnet-5-5", 0.1),
            ("claude-fable-5-2", 0.2),
            ("claude-mythos-5-2", 0.2),
        ]:
            with self.subTest(model=model):
                self.assertEqual(costs.message_cost(model, {"cache_read_input_tokens": 1_000_000}), expected)

    def test_haiku_threshold_includes_cached_input(self):
        usage = {"cache_read_input_tokens": 99_000, "input_tokens": 1000, "output_tokens": 1000}
        self.assertAlmostEqual(costs.message_cost("claude-haiku-5-5", usage), 0.00159)
        usage["input_tokens"] += 1
        self.assertAlmostEqual(costs.message_cost("claude-haiku-5-5", usage), 0.0079505)

    def test_snapshot_ids_and_unknown_versions(self):
        self.assertEqual(costs.get_pricing("claude-haiku-5-5-20261007"), costs.PRICING["claude-haiku-5-5"])
        for model in ["claude-sonnet-5-6", "claude-opus-5-50", "unrecognised"]:
            with self.subTest(model=model), self.assertRaises(costs.UnknownModelError):
                costs.get_pricing(model)

    def test_legacy_cache_writes_and_modifiers(self):
        usage = {"cache_creation_input_tokens": 1000, "speed": "fast", "inference_geo": "us"}
        self.assertAlmostEqual(costs.message_cost("claude-opus-5-5", usage), 0.011)

    def test_synthetic_zero_usage(self):
        self.assertEqual(costs.message_cost("<synthetic>", {"input_tokens": 0}), 0)


class WindowTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.home = Path(self.temp.name)
        self.projects = self.home / ".claude" / "projects"
        self.projects.mkdir(parents=True)
        self.home_patch = patch.object(costs.Path, "home", return_value=self.home)
        self.home_patch.start()
        self.addCleanup(self.home_patch.stop)

    def record(self, message_id, hours=1, model="claude-opus-5-5", output=1000):
        return {
            "type": "assistant",
            "timestamp": (datetime.now(timezone.utc) - timedelta(hours=hours)).isoformat(),
            "message": {"id": message_id, "model": model, "usage": {"output_tokens": output}},
        }

    def write(self, name, records):
        file = self.projects / name
        file.parent.mkdir(parents=True, exist_ok=True)
        file.write_text("\n".join(json.dumps(record) for record in records) + "\n")

    def test_duplicate_blocks_and_copies_count_once_but_subagents_count(self):
        response = self.record("same")
        self.write("main.jsonl", [response, response, response, self.record("older", hours=6)])
        self.write("subagents/agent.jsonl", [response, self.record("subagent")])
        self.assertEqual(costs.costs_for_windows([5, 168]), [0.04, 0.06])

    def test_latest_response_usage_wins(self):
        self.write("session.jsonl", [self.record("same", hours=2, output=100), self.record("same", output=1000)])
        self.assertEqual(costs.costs_for_windows([5]), [0.02])

    def test_uuid_fallback_preserves_distinct_responses(self):
        one, two = self.record(None), self.record(None)
        one["uuid"], two["uuid"] = "one", "two"
        self.write("session.jsonl", [one, one, two, self.record(None), self.record(None)])
        self.assertEqual(costs.costs_for_windows([5]), [0.08])

    def test_unknown_pricing_only_invalidates_affected_windows(self):
        self.write("session.jsonl", [self.record("known"), self.record("unknown", hours=6, model="new-model")])
        stderr = io.StringIO()
        with contextlib.redirect_stderr(stderr):
            self.assertEqual(costs.costs_for_windows([5, 168]), [0.02, None])
        self.assertIn("new-model", stderr.getvalue())
        self.assertEqual(costs.format_cost(None), "unknown")

    def test_future_expired_malformed_and_user_records_are_excluded(self):
        user = self.record("user")
        user["type"] = "user"
        self.write("session.jsonl", [self.record("future", hours=-1), self.record("expired", hours=200), user, self.record("valid")])
        with (self.projects / "session.jsonl").open("a") as file:
            file.write("invalid JSON\n")
        self.assertEqual(costs.costs_for_windows([5]), [0.02])

    def test_cache_ignores_old_totals_and_does_not_cache_unknowns(self):
        cache = self.home / ".cache" / "claude"
        cache.mkdir(parents=True)
        (cache / "costs_50.json").write_text('{"costs": [999]}')
        with patch.object(costs, "costs_for_windows", return_value=[0.02]) as scan:
            self.assertEqual(costs.cached_costs([5]), [0.02])
            self.assertEqual(costs.cached_costs([5]), [0.02])
            scan.assert_called_once()
        with patch.object(costs, "costs_for_windows", return_value=[None]) as scan:
            self.assertEqual(costs.cached_costs([168]), [None])
            self.assertEqual(costs.cached_costs([168]), [None])
            self.assertEqual(scan.call_count, 2)


if __name__ == "__main__":
    unittest.main()
