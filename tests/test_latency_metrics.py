import ast
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import patch
import time

ROOT = Path(__file__).resolve().parents[1]


class TokenTimingTests(unittest.TestCase):
    def clock(self):
        tree = ast.parse((ROOT / "ros2/qwen_node.py").read_text())
        cls = next(
            x
            for x in tree.body
            if isinstance(x, ast.ClassDef) and x.name == "TokenClock"
        )
        ns = {"time": time}
        exec(compile(ast.Module(body=[cls], type_ignores=[]), "<clock>", "exec"), ns)
        return ns["TokenClock"]()

    def test_prompt_is_ignored_and_tpot_uses_n_minus_one(self):
        c = self.clock()
        with patch.object(time, "perf_counter_ns", side_effect=[2_000_000, 5_000_000]):
            c.put(SimpleNamespace(shape=(1, 20)))
            c.put(SimpleNamespace(shape=(1,)))
            c.put(SimpleNamespace(shape=(1,)))
        m = c.metrics(1_000_000, 0)
        self.assertEqual(m["generate_ttft_ms"], 1)
        self.assertEqual(m["server_ttft_ms"], 2)
        self.assertEqual(m["tpot_ms"], 3)
        self.assertEqual(m["itl_ms"], [3])

    def test_zero_and_one_output_have_null_tpot(self):
        for n in (0, 1):
            c = self.clock()
            c.put(SimpleNamespace(shape=(1, 20)))
            for _ in range(n):
                c.put(SimpleNamespace(shape=(1,)))
            self.assertIsNone(c.metrics(0, 0)["tpot_ms"])

    def test_multitoken_chunk_is_not_fake_per_token_timing(self):
        c = self.clock()
        c.put(SimpleNamespace(shape=(1, 20)))
        with self.assertRaises(ValueError):
            c.put(SimpleNamespace(shape=(1, 2)))

    def test_both_nodes_expose_stages_and_publication_log(self):
        for kind in ("qwen", "yolo"):
            s = (ROOT / "ros2" / (kind + "_node.py")).read_text()
            for field in (
                "timings_ms",
                "publication_finished",
                "worker_busy_ms",
                "result_discovery_ms",
                "ack_wait_ms",
            ):
                self.assertIn(field, s)
        self.assertIn(
            'result.speed["inference"]', (ROOT / "ros2/yolo_node.py").read_text()
        )


class NativeTimingContractTests(unittest.TestCase):
    def test_clients_keep_timing_out_of_stdout_and_report_save_separately(self):
        for model in ("qwen", "yolo"):
            text = (ROOT / "clients" / f"request_{model}.py").read_text()
            self.assertIn('"client_timings_ms"', text)
            self.assertIn('"request_e2e_ms"', text)
            self.assertIn('"setup_discovery_ms"', text)
        self.assertIn(
            '"output_save_ms"', (ROOT / "clients/request_yolo.py").read_text()
        )

    def test_no_per_token_gpu_sync_or_output(self):
        tree = ast.parse((ROOT / "ros2/qwen_node.py").read_text())
        cls = next(
            x
            for x in tree.body
            if isinstance(x, ast.ClassDef) and x.name == "TokenClock"
        )
        source = ast.unparse(cls)
        self.assertNotIn("synchronize", source)
        self.assertNotIn("print(", source)
        self.assertNotIn("decode(", source)
