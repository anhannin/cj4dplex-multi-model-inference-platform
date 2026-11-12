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
    def test_requested_axis_labels_panel_titles_and_no_footnotes(self):
        import inspect
        from scripts.plot_burst_report import plot

        source = inspect.getsource(plot)
        self.assertIn("E2E Latency p95 (s)", source)
        self.assertIn("Baseline", source)
        self.assertIn("Ours", source)
        self.assertNotIn("suptitle(", source)
        self.assertIn("ax.set_title(", source)
        self.assertIn('"Qwen"', source)
        self.assertIn('"YOLO"', source)
        self.assertIn("top=0.88", source)
        self.assertNotIn("fig.text(", source)
        self.assertNotIn("초", source)


class ReportPerformanceCriteria(unittest.TestCase):
    def test_burst_criteria_are_not_called_operational_slo(self):
        report = (ROOT / "docs/TECHNICAL_REPORT.ko.md").read_text()
        section = report.split("### 2.3 ", 1)[1].split("## 3.", 1)[0]
        self.assertIn("성능 목표 및 평가 기준", section)
        self.assertIn("Qwen 113.299초 이하, YOLO 11.970초 이하", section)
        self.assertNotIn("SLO", section)

    def test_result_states_burst_goal_was_met(self):
        report = (ROOT / "docs/TECHNICAL_REPORT.ko.md").read_text()
        section = report.split("### 5.2 ", 1)[1].split("### 5.3 ", 1)[0]
        self.assertIn("정적 8/40은 설정한 상대 성능 기준을 모두 만족하였다", section)
        self.assertIn("목표를 달성하였다", section)
        self.assertNotIn("SLO", section)
