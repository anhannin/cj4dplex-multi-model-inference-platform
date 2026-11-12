import unittest
from diagnostics.nsight.analyze import union_ns, delay_metrics


class NsightMathTests(unittest.TestCase):
    def test_union_does_not_double_count_overlapping_kernels(self):
        self.assertEqual(union_ns([(0, 10), (5, 15), (20, 25)]), 20)
        self.assertEqual(union_ns([]), 0)

    def test_submission_delay_keeps_negative_post_return_gap(self):
        kernels = [
            {"start": 100, "end": 200, "correlationId": 1},
            {"start": 120, "end": 200, "correlationId": 2},
            {"start": 300, "end": 400, "correlationId": 999},
        ]
        apis = [
            {"start": 90, "end": 110, "correlationId": 1, "name": "cuLaunchKernel"},
            {"start": 90, "end": 100, "correlationId": 2, "name": "cuLaunchKernel"},
        ]
        s = delay_metrics(kernels, apis)
        self.assertEqual(s["matched_kernel_count"], 2)
        self.assertEqual(s["unmatched_kernel_count"], 1)
        self.assertEqual(s["kernel_started_before_api_return"], 1)
        self.assertEqual(s["post_return_signed_us"]["min"], -0.01)
        self.assertEqual(s["positive_post_return_us"]["n"], 1)


class RangeCoverageTests(unittest.TestCase):
    def test_clip_kernels_to_range_and_do_not_label_gaps_cpu_time(self):
        from diagnostics.nsight.analyze import range_coverage

        result = range_coverage(0, 10, [(-5, 5), (3, 7), (8, 12)])
        self.assertEqual(result["kernel_union_ns"], 9)
        self.assertEqual(result["non_kernel_coverage_ns"], 1)
        self.assertNotIn("cpu_time", result)


class LaunchGeometryTests(unittest.TestCase):
    def test_grid_capacity_is_not_reported_as_measured_sm_utilization(self):
        from diagnostics.nsight.analyze import geometry_metrics

        result = geometry_metrics(
            [
                {"start": 0, "end": 10, "gridX": 1, "gridY": 2, "gridZ": 1},
                {"start": 10, "end": 30, "gridX": 48, "gridY": 1, "gridZ": 1},
            ],
            48,
        )
        self.assertEqual(result["launches_with_fewer_blocks_than_sms"], 1)
        self.assertAlmostEqual(result["elapsed_sum_fraction_in_small_grids"], 1 / 3)
        self.assertNotIn("sm_utilization", result)
