import unittest


class TimelineTests(unittest.TestCase):
    def test_stage_boundaries_and_token_time_are_derived_from_actual_clocks(self):
        from diagnostics.mps_static.timeline_data import worker_record

        row = {
            "request_id": "r_test",
            "model": "qwen",
            "index": 0,
            "sent_ns": 900_000_000,
            "received_ns": 2_400_000_000,
            "response": {
                "server_enqueued_perf_ns": 1_000_000_000,
                "server_started_perf_ns": 1_200_000_000,
                "model_start_perf_ns": 1_300_000_000,
                "model_end_perf_ns": 2_300_000_000,
                "processing_ms": 1150,
                "timings_ms": {"server_ttft_ms": 500},
                "itl_ms": [100] * 8,
            },
        }
        e = {"worker_busy_ms": 1250}
        r = worker_record(row, e, 900_000_000)
        self.assertEqual(r["queue"], [0.1, 0.3])
        self.assertEqual(r["phases"][0]["kind"], "preprocess")
        self.assertAlmostEqual(r["phases"][1]["start"], 0.4)
        self.assertAlmostEqual(r["phases"][1]["end"], 0.6)
        self.assertEqual(r["phases"][2]["kind"], "generation")
        self.assertAlmostEqual(r["phases"][-1]["end"], 1.55)
        self.assertAlmostEqual(r["received"], 1.5)

    def test_queue_depth_events_have_no_negative_or_unfinished_jobs(self):
        from diagnostics.mps_static.timeline_data import queue_events

        r = queue_events([[0.0, 1.0], [0.2, 1.5], [1.0, 2.0]])
        self.assertEqual(r, [[0.0, 1], [0.2, 2], [1.0, 2], [1.5, 1], [2.0, 0]])

    def test_invalid_worker_order_is_rejected(self):
        from diagnostics.mps_static.timeline_data import worker_record

        row = {
            "request_id": "r_bad",
            "model": "yolo",
            "index": 0,
            "sent_ns": 0,
            "received_ns": 3,
            "response": {
                "server_enqueued_perf_ns": 1,
                "server_started_perf_ns": 2,
                "model_start_perf_ns": 1,
                "model_end_perf_ns": 2,
                "processing_ms": 1,
            },
        }
        with self.assertRaises(ValueError):
            worker_record(row, {"worker_busy_ms": 2}, 0)
