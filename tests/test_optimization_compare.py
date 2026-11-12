from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from optimization.compare import rows


class CompareTests(unittest.TestCase):
    def test_nonbenchmark_summary_ignored(self):
        with TemporaryDirectory() as directory:
            sub = Path(directory) / 'green-concurrency'
            sub.mkdir()
            (sub / 'summary.json').write_text('{"state":"PASS"}')
            self.assertEqual(list(rows(Path(directory))), [])
