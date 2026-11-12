import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from optimization.pool_results import pool_runs


class PoolTests(unittest.TestCase):
    def make(self, root, name, rate=0, rid=None):
        d = Path(root) / name
        d.mkdir()
        manifest = {'state': 'PASS', 'models': ['yolo'], 'max_new_tokens': 128, 'timing_mode': 'tokens', 'prompts': ['a'], 'images': [], 'concurrency_per_model': 1, 'cv_launch_rate_ceiling': rate, 'measurement_seconds': {'yolo': 2}}
        (d / 'manifest.json').write_text(json.dumps(manifest))
        row = {'request_id': rid or name, 'model': 'yolo', 'warmup': False, 'status': 'ok', 'request_e2e_ms': 10, 'response': {}}
        (d / 'requests.jsonl').write_text(json.dumps(row)+'\n')
        return d

    def test_pool_actual_windows(self):
        with TemporaryDirectory() as root:
            a, b = self.make(root, 'a'), self.make(root, 'b')
            s = pool_runs([a, b])['summary']['yolo']
            self.assertEqual(s['successful'], 2)
            self.assertEqual(s['successful_requests_per_second'], .5)

    def test_rate_protocol_mismatch_rejected(self):
        with TemporaryDirectory() as root:
            a, b = self.make(root, 'a'), self.make(root, 'b', rate=20)
            with self.assertRaises(ValueError):
                pool_runs([a, b])

    def test_duplicate_requests_rejected(self):
        with TemporaryDirectory() as root:
            a, b = self.make(root, 'a', rid='x'), self.make(root, 'b', rid='x')
            with self.assertRaises(ValueError):
                pool_runs([a, b])
