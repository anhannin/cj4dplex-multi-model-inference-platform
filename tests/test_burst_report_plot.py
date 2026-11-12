"""Figure values must match pooled request p95, not means or batch makespan."""

import json
from pathlib import Path
import unittest
from scripts.plot_burst_report import comparison_data

ROOT = Path(__file__).resolve().parents[1]


class BurstPlotValues(unittest.TestCase):
    def test_only_baseline_and_q8_y40_and_correct_request_metric(self):
        s = json.loads(
            (ROOT / "results/static-eval/20261110-v1/analysis/summary.json").read_text()
        )
        d = comparison_data(s)
        self.assertEqual([r["model"] for r in d], ["qwen", "yolo"])
        self.assertAlmostEqual(d[0]["before_s"], 113.29920292675)
        self.assertAlmostEqual(d[0]["after_s"], 111.87620404415, places=3)
        self.assertAlmostEqual(d[1]["before_s"], 14.9625205385)
        self.assertAlmostEqual(d[1]["after_s"], 10.6736063, places=3)
        self.assertAlmostEqual(d[1]["reduction_pct"], 28.664, places=2)
        self.assertEqual([r["requests_per_condition"] for r in d], [50, 1500])
        self.assertTrue(all(r["metric"] == "pooled request E2E p95" for r in d))

    def test_missing_condition_is_an_error_not_a_silent_plot(self):
        with self.assertRaises(ValueError):
            comparison_data({"conditions": []})


class MinimalFigureLabels(unittest.TestCase):
    def test_requested_axis_labels_and_no_titles_or_footnotes(self):
        import inspect
        from scripts.plot_burst_report import plot

        source = inspect.getsource(plot)
        self.assertIn("E2E Latency p95 (s)", source)
        self.assertIn("Baseline", source)
        self.assertIn("Ours", source)
        self.assertNotIn("suptitle(", source)
        self.assertNotIn("set_title(", source)
        self.assertNotIn("fig.text(", source)
        self.assertNotIn("초", source)
