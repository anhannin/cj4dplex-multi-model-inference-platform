from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import Mock
from optimization.live_logs import LiveLogs


class LiveLogsTests(unittest.TestCase):
    def test_follow_and_clean_shutdown(self):
        with TemporaryDirectory() as root:
            process = Mock()
            process.poll.return_value = None
            popen = Mock(return_value=process)
            capture = LiveLogs(Path(root), 'test', ['yolo'], '2026-11-04T00:00:00Z', popen=popen)
            capture.start()
            self.assertIn('--follow=true', popen.call_args.args[0])
            self.assertIn('--since-time=2026-11-04T00:00:00Z', popen.call_args.args[0])
            capture.close()
            process.terminate.assert_called_once()
            process.wait.assert_called_once()
            self.assertTrue((Path(root)/'test-yolo.log').exists())

    def test_partial_start_failure_cleans_existing_process(self):
        with TemporaryDirectory() as root:
            process = Mock()
            process.poll.return_value = None
            popen = Mock(side_effect=[process, OSError('cannot start')])
            capture = LiveLogs(Path(root), 'test', ['qwen', 'yolo'], 'now', popen=popen)
            with self.assertRaises(OSError):
                capture.start()
            process.terminate.assert_called_once()
