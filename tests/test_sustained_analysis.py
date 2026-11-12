import unittest
from diagnostics.sustained.analysis import (
    distribution,
    grouped_decision,
    queue_series,
    validate_rows,
)


class SustainedAnalysisTests(unittest.TestCase):
    def test_distribution_and_error_guard(self):
        self.assertEqual(distribution([10, 20, 30])["p95"], 29)
        self.assertIsNone(distribution([])["p95"])
        base = {
            "qwen": {"e2e_ms": {"p95": 100}},
            "yolo": {"e2e_ms": {"p95": 100}},
            "errors": 0,
        }
        good = {
            "qwen": {"e2e_ms": {"p95": 100}},
            "yolo": {"e2e_ms": {"p95": 80}},
            "errors": 0,
        }
        self.assertTrue(grouped_decision(good, base)["both_pass"])
        good["errors"] = 1
        self.assertFalse(grouped_decision(good, base)["both_pass"])

    def test_queue_counts_server_enqueues_not_client_unreceived(self):
        rows = [
            {
                "model": "yolo",
                "status": "ok",
                "response": {
                    "server_enqueued_perf_ns": 0,
                    "server_started_perf_ns": 2_000_000_000,
                },
            }
        ]
        self.assertEqual(queue_series(rows, 0, 3, 1), [(0, 1), (1, 1), (2, 0), (3, 0)])

    def test_audit_missing_and_duplicate(self):
        manifest = {
            "run_id": "a",
            "expected": {"qwen": 1, "yolo": 0},
            "t0_ns": 0,
            "stop_ns": 100,
            "duration_s": 1e-7,
        }
        with self.assertRaises(ValueError):
            validate_rows([], manifest, {})
