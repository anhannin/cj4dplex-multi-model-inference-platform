import unittest
from diagnostics.kernel_overlap.analysis import (
    union,
    intersect,
    duration,
    overlap_bounds,
    fit_clock,
)
from diagnostics.kernel_overlap.generate import instrument
from pathlib import Path


class KernelOverlapTests(unittest.TestCase):
    def test_union_not_double_sum(self):
        self.assertEqual(
            union([(0, 10), (2, 8), (9, 20), (25, 30)]), [(0, 20), (25, 30)]
        )
        self.assertEqual(duration(union([(0, 10), (2, 8)])), 10)
        self.assertEqual(intersect([(0, 10), (20, 30)], [(5, 25)]), [(5, 10), (20, 25)])

    def test_overlap_bounds_are_conservative(self):
        r = overlap_bounds([(0, 100)], [(50, 150)], 5, 5)
        self.assertEqual(r, {"observed": 50, "lower": 40, "upper": 60})
        self.assertEqual(overlap_bounds([(0, 10)], [(20, 30)], 1, 1)["upper"], 0)

    def test_clock_offsets_not_assumed_equal(self):
        anchors = [
            {"trace_ns": 10, "pre_ns": 1009, "post_ns": 1011},
            {"trace_ns": 1010, "pre_ns": 2009, "post_ns": 2011},
            {"trace_ns": 2010, "pre_ns": 3009, "post_ns": 3011},
        ]
        f = fit_clock(anchors)
        self.assertEqual(f["map"](500), 1500)
        self.assertLessEqual(f["max_midpoint_residual_ns"], 1)
        with self.assertRaises(ValueError):
            fit_clock(anchors[:1])

    def test_real_node_capture_gate_and_cpu_clock_marks(self):
        p = Path("results/green-burst/20261109-v1-generated/qwen_burst_node.py")
        code = instrument(p.read_text(), "qwen")
        compile(code, "diagnostic", "exec")
        self.assertIn("time.perf_counter_ns()", code)
        self.assertIn("from clock_marks import anchor", code)
        self.assertIn(
            "torch.cuda.nvtx.mark",
            Path("diagnostics/kernel_overlap/clock_marks.py").read_text(),
        )
        self.assertIn("capture_requested", code)
        self.assertIn("request:qwen:", code)
        self.assertEqual(code.count("output = model.generate("), 1)


class LargeClockTests(unittest.TestCase):
    def test_utc_size_trace_timestamp_keeps_ns_resolution_by_relative_fit(self):
        base = 1794237500000000000
        host = 987654321000000
        anchors = [
            {
                "trace_ns": base + i * 10_000_000,
                "pre_ns": host + i * 10_000_000 - 50,
                "post_ns": host + i * 10_000_000 + 50,
            }
            for i in range(5)
        ]
        fit = fit_clock(anchors)
        self.assertEqual(fit["map"](base + 12345678), host + 12345678)
        self.assertEqual(fit["empirical_alignment_error_ns"], 50)


class PositiveControlAssociationTests(unittest.TestCase):
    def test_parallel_cpu_scopes_do_not_misattribute_other_green_kernel(self):
        import sqlite3
        from tempfile import TemporaryDirectory
        import sys

        directory = Path("diagnostics/kernel_overlap").resolve()
        sys.path.insert(0, str(directory))
        from analyze_reports import positive_analysis

        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            folder = root / "validation/positive"
            folder.mkdir(parents=True)
            with sqlite3.connect(folder / "trace.sqlite") as c:
                c.execute("CREATE TABLE StringIds(id INTEGER,value TEXT)")
                c.execute(
                    "CREATE TABLE NVTX_EVENTS(start INTEGER,end INTEGER,text TEXT,textId INTEGER)"
                )
                c.execute(
                    "CREATE TABLE CUPTI_ACTIVITY_KIND_KERNEL(start INTEGER,end INTEGER,greenContextId INTEGER)"
                )
                for lo, hi, label in [
                    (10, 100, "control.serial0"),
                    (110, 200, "control.serial1"),
                    (210, 400, "control.parallel0"),
                    (215, 405, "control.parallel1"),
                ]:
                    c.execute(
                        "INSERT INTO NVTX_EVENTS VALUES(?,?,?,NULL)",
                        (lo * 1000000, hi * 1000000, label),
                    )
                for lo, hi, green in [
                    (20, 90, 2),
                    (120, 190, 3),
                    (230, 390, 2),
                    (225, 385, 3),
                ]:
                    c.execute(
                        "INSERT INTO CUPTI_ACTIVITY_KIND_KERNEL VALUES(?,?,?)",
                        (lo * 1000000, hi * 1000000, green),
                    )
            r = positive_analysis(root)
            self.assertEqual(r["serial_kernel_overlap_ms"], 0)
            self.assertEqual(r["parallel_kernel_overlap_ms"], 155)


class SchedulerTests(unittest.TestCase):
    def test_restore_save_pairs_and_unclosed_tail_are_explicit(self):
        from diagnostics.kernel_overlap.scheduler_analysis import residencies

        rows = [
            (8, 11, 100, 50),
            (7, 11, 200, 50),
            (8, 22, 210, 60),
            (7, 22, 300, 60),
            (8, 11, 310, 50),
        ]
        intervals, unclosed = residencies(rows)
        self.assertEqual(intervals, [(100, 200, 11, 50), (210, 300, 22, 60)])
        self.assertEqual(unclosed, (310, 11, 50))
        self.assertEqual(
            intersect(
                [(a, b) for a, b, c, p in intervals if c == 11],
                [(a, b) for a, b, c, p in intervals if c == 22],
            ),
            [],
        )
