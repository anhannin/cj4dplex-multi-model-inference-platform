import unittest
from diagnostics.green_context.concurrency_probe import overlap_ratios


class GreenConcurrencyMathTests(unittest.TestCase):
    def test_reports_ratios_without_claiming_global_parallelism(self):
        r = overlap_ratios(10, 10, 11)
        self.assertAlmostEqual(r["both_over_sum"], 0.55)
        self.assertAlmostEqual(r["both_over_max"], 1.1)
        self.assertNotIn("guaranteed_concurrent", r)

    def test_invalid_times_are_rejected(self):
        with self.assertRaises(ValueError):
            overlap_ratios(0, 1, 2)


class ProbeControlsTests(unittest.TestCase):
    def test_no_allocation_barrier_inside_timed_work(self):
        from pathlib import Path

        root = Path(__file__).resolve().parents[1]
        source = (root / "diagnostics/green_context/green_bridge.cu").read_text()
        body = source.split("double fixed_work(", 1)[1].split(
            "std::vector<unsigned int> sample_smids", 1
        )[0]
        self.assertNotIn("cuMemAlloc", body)
        self.assertNotIn("cuMemFree", body)

    def test_cross_process_solo_references_are_explicitly_serialized(self):
        from pathlib import Path

        root = Path(__file__).resolve().parents[1]
        source = (root / "diagnostics/green_context/concurrency_probe.py").read_text()
        self.assertIn("solo-go", source)
        self.assertIn("solo.json", source)
