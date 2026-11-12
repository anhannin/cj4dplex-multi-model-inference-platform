import unittest
from optimization.pacing import launch_allowed


class PacingTests(unittest.TestCase):
    def test_unlimited_and_qwen(self):
        self.assertTrue(launch_allowed('yolo', 100, 100, 0))
        self.assertTrue(launch_allowed('qwen', 100, 100, 20))

    def test_exact_50ms_period(self):
        self.assertFalse(launch_allowed('yolo', 1_049_999_999, 1_000_000_000, 20))
        self.assertTrue(launch_allowed('yolo', 1_050_000_000, 1_000_000_000, 20))
