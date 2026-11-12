import unittest
from diagnostics.sustained.protocol import (
    scheduled_offsets,
    choose_rates,
    make_schedule,
    validity,
)


class SustainedProtocolTests(unittest.TestCase):
    def test_arrivals_are_fixed_and_stop_exclusive(self):
        self.assertEqual(scheduled_offsets(2, 1), [0, 500000000])
        self.assertEqual(len(scheduled_offsets(15, 120)), 1800)
        self.assertTrue(all(x < 120_000_000_000 for x in scheduled_offsets(22, 120)))
        with self.assertRaises(ValueError):
            scheduled_offsets(0, 1)

    def test_select_rates_requires_two_stable_points_and_selects_fixed_pair(self):
        def trial(rate, wait, slope=0):
            return {
                "rate": rate,
                "tail_queue_mean_ms": wait,
                "queue_slope_rps": slope,
                "errors": 0,
            }

        rows = [trial(8, 2), trial(15, 20), trial(22, 200, 1), trial(30, 500, 3)]
        self.assertEqual(choose_rates(rows), [8, 15])
        with self.assertRaises(ValueError):
            choose_rates([trial(8, 2), trial(15, 200)])

    def test_random_complete_blocks_and_generator_lag(self):
        s = make_schedule([8, 15])
        self.assertEqual(len(s), 40)
        self.assertEqual(s, make_schedule([8, 15]))
        for i in range(5):
            block = s[i * 8 : (i + 1) * 8]
            self.assertEqual(len({(x["condition"], x["rate"]) for x in block}), 8)
        self.assertTrue(validity([0, 1, 2], 0)["valid"])
        self.assertFalse(validity([0, 1, 101], 0)["valid"])
        self.assertFalse(validity([0], 1)["valid"])


class SendRecordTests(unittest.TestCase):
    def test_shared_send_record_reconciles_even_if_callback_arrived_first(self):
        from diagnostics.sustained.protocol import apply_send_record

        row = {"status": "ok", "received_ns": 12000000, "sent_ns": None}
        apply_send_record(row, 2000000, 3000000, 1000000)
        self.assertEqual(row["status"], "ok")
        self.assertEqual(row["request_e2e_ms"], 10)
        self.assertEqual(row["scheduled_e2e_ms"], 11)
        pending = {"status": "unissued", "sent_ns": None}
        apply_send_record(pending, 2000000, 3000000, 1000000)
        self.assertEqual(pending["status"], "pending")
        with self.assertRaises(ValueError):
            apply_send_record(pending, 0, 0, 0)
