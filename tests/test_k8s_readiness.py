from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]


class ReadinessMarkerTests(unittest.TestCase):
    def test_own_ready_marker_is_cleared_before_loading_and_set_after_subscription(
        self,
    ):
        for kind in ["qwen", "yolo"]:
            text = (ROOT / "ros2" / f"{kind}_node.py").read_text()
            self.assertIn('"/tmp/cj-model-ready"', text)
            self.assertLess(
                text.index("READY_FILE.unlink(missing_ok=True)"),
                text.index("self.worker.start()"),
            )
            self.assertGreater(
                text.index("READY_FILE.write_text(str(os.getpid()))"),
                text.index("self.create_subscription("),
            )
            close = text.split("    def close(self):", 1)[1]
            self.assertLess(
                close.index("READY_FILE.unlink(missing_ok=True)"),
                close.index("self.worker.join()"),
            )
