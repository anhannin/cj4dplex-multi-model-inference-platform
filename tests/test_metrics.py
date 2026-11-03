import unittest
from scripts.metrics import summarize, overlapping

class MetricsTests(unittest.TestCase):
    def test_summary_linear_percentile(self):
        result = summarize([1, 2, 3, 4])
        self.assertEqual(result['n'], 4)
        self.assertEqual(result['mean_ms'], 2.5)
        self.assertAlmostEqual(result['p95_ms'], 3.85)
    def test_empty_is_not_zero(self):
        self.assertIsNone(summarize([])['mean_ms'])
    def test_overlap_excludes_boundary_crossing(self):
        rows = [{'start': 1, 'end': 3}, {'start': 2, 'end': 4}, {'start': 3, 'end': 5}]
        self.assertEqual(overlapping(rows, 2, 4), [rows[1]])
