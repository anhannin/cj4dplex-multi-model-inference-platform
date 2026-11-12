import unittest
from diagnostics.green_context.ncu_analysis import (
    metric_number,
    parse_rows,
    select_linear_targets,
)


class CounterAnalysisTests(unittest.TestCase):
    def test_missing_metrics_are_not_zero(self):
        self.assertIsNone(metric_number("n/a"))
        self.assertIsNone(metric_number("nan"))
        self.assertIsNone(metric_number(""))
        self.assertEqual(metric_number("1,234.5"), 1234.5)

    def test_parse_friendly_names_without_calling_memory_dram(self):
        rows = [
            {
                "ID": "0",
                "Kernel Name": "gemvx",
                "Section Name": "GPU Speed Of Light Throughput",
                "Metric Name": "Memory Throughput",
                "Metric Unit": "%",
                "Metric Value": "15.8",
            },
            {
                "ID": "0",
                "Kernel Name": "gemvx",
                "Section Name": "GPU Speed Of Light Throughput",
                "Metric Name": "Compute (SM) Throughput",
                "Metric Unit": "%",
                "Metric Value": "10.3",
            },
        ]
        result = parse_rows(rows)[0]
        self.assertEqual(result["metrics"]["Memory Throughput"]["value"], 15.8)
        self.assertNotIn("DRAM Throughput", result["metrics"])

    def test_select_same_layer_up_and_down_without_modifying_model(self):
        names = [
            "model.language_model.layers.0.mlp.gate_proj",
            "model.language_model.layers.0.mlp.up_proj",
            "model.language_model.layers.0.mlp.down_proj",
            "model.language_model.layers.1.mlp.up_proj",
            "model.language_model.layers.1.mlp.down_proj",
        ]
        self.assertEqual(select_linear_targets(names), names[1:3])


class RawCounterDerivationTests(unittest.TestCase):
    def test_stall_contribution_is_not_program_wall_time(self):
        from diagnostics.green_context.ncu_analysis import derive_raw_stalls

        raw = {
            "smsp__average_warp_latency_per_inst_issued.ratio": "80",
            "smsp__average_warps_issue_stalled_long_scoreboard_per_issue_active.ratio": "40",
            "smsp__average_warps_issue_stalled_lg_throttle_per_issue_active.ratio": "20",
        }
        result = derive_raw_stalls(raw)
        self.assertEqual(result["long_scoreboard_contribution_pct"], 50)
        self.assertEqual(result["lg_throttle_contribution_pct"], 25)
        self.assertNotIn("program_wall_memory_pct", result)

    def test_absent_raw_metric_is_unknown(self):
        from diagnostics.green_context.ncu_analysis import derive_raw_stalls

        self.assertIsNone(derive_raw_stalls({})["long_scoreboard_contribution_pct"])
