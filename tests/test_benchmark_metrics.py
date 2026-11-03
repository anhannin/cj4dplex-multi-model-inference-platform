import importlib.util
from pathlib import Path
import unittest


def module():
    p = Path(__file__).resolve().parents[1] / "benchmark/aggregate_latency.py"
    spec = importlib.util.spec_from_file_location("aggregate_latency", p)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


class AggregateTests(unittest.TestCase):
    def test_percentile_linear_and_empty(self):
        m = module()
        self.assertAlmostEqual(m.stats([1, 2, 3, 4])["p95"], 3.85)
        self.assertIsNone(m.stats([])["p95"])

    def test_failures_count_and_warmup_excluded(self):
        m = module()
        rows = [
            {"model": "qwen", "warmup": True, "status": "ok", "request_e2e_ms": 999},
            {
                "model": "qwen",
                "warmup": False,
                "status": "ok",
                "request_e2e_ms": 10,
                "response": {"timings_ms": {"tpot_ms": None}, "output_tokens": 2},
            },
            {
                "model": "qwen",
                "warmup": False,
                "status": "timeout",
                "request_e2e_ms": 100,
            },
        ]
        s = m.aggregate(rows, {"qwen": 2})["qwen"]
        self.assertEqual(s["attempted"], 2)
        self.assertEqual(s["failed"], 1)
        self.assertEqual(s["request_e2e_ms"]["mean"], 10)
        self.assertEqual(s["successful_requests_per_second"], 0.5)


class SchedulerTests(unittest.TestCase):
    def test_yolo_continues_until_qwen_done_but_warmup_is_bounded(self):
        import ast

        source = (
            Path(__file__).resolve().parents[1] / "benchmark/bench_ros2.py"
        ).read_text()
        tree = ast.parse(source)
        f = next(
            x
            for x in tree.body
            if isinstance(x, ast.FunctionDef) and x.name == "needs_more"
        )
        ns = {}
        exec(compile(ast.Module(body=[f], type_ignores=[]), "<needs_more>", "exec"), ns)
        needs = ns["needs_more"]
        self.assertTrue(needs("yolo", {"qwen": 2, "yolo": 300}, 30, False, True))
        self.assertFalse(needs("yolo", {"qwen": 30, "yolo": 300}, 30, False, True))
        self.assertFalse(needs("yolo", {"qwen": 2, "yolo": 5}, 5, True, True))
        self.assertFalse(needs("qwen", {"qwen": 30, "yolo": 1}, 30, False, True))


class JoinTests(unittest.TestCase):
    def test_join_by_uuid_preserves_negative_residual_and_flags_it(self):
        import json
        import sys
        import tempfile
        from unittest.mock import patch

        folder = Path(__file__).resolve().parents[1] / "benchmark"
        with patch.object(sys, "path", [str(folder), *sys.path]):
            import join_server_timings as joiner
        with tempfile.TemporaryDirectory() as d:
            p = Path(d)
            row = {
                "model": "yolo",
                "request_id": "own",
                "warmup": False,
                "status": "ok",
                "request_e2e_ms": 10,
                "response": {"timings_ms": {"callback_to_result_ready_ms": 11}},
            }
            (p / "requests.jsonl").write_text(json.dumps(row) + "\n")
            (p / "manifest.json").write_text(
                json.dumps({"measurement_seconds": {"yolo": 1}})
            )
            pub = {
                "event": "publication_finished",
                "request_id": "own",
                "publisher_create_ms": 1,
                "result_discovery_ms": 1,
                "response_serialize_ms": 1,
            }
            process = {
                "event": "processing_finished",
                "request_id": "own",
                "worker_busy_ms": 20,
            }
            wrong = {
                "event": "processing_finished",
                "request_id": "other",
                "worker_busy_ms": 999,
            }
            (p / "yolo-server.log").write_text(
                "\n".join(json.dumps(e) for e in (wrong, pub, process))
            )
            joiner.join(p)
            r = json.loads((p / "joined-requests.jsonl").read_text())
            self.assertTrue(r["server_events_complete"])
            self.assertTrue(r["negative_residual_flag"])
            self.assertEqual(r["post_response_server_timings_ms"]["worker_busy_ms"], 20)


class OutputComparisonTests(unittest.TestCase):
    def test_token_work_is_required_but_text_variation_is_reported(self):
        import sys
        from unittest.mock import patch

        folder = Path(__file__).resolve().parents[1] / "benchmark"
        with patch.object(sys, "path", [str(folder), *sys.path]):
            import report_five_phases as report
        result = report.compare_outputs(
            [("input", "text-a", 128)], [("input", "text-b", 128)]
        )
        self.assertEqual(result["different_output_requests"], 1)
        self.assertFalse(result["exact_text_match"])
        with self.assertRaises(AssertionError):
            report.compare_outputs([("input", "a", 128)], [("different", "a", 128)])
        with self.assertRaises(AssertionError):
            report.compare_outputs([("input", "a", 128)], [("input", "a", 127)])
