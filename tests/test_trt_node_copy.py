import ast
from pathlib import Path
from types import SimpleNamespace
import unittest
from optimization.prepare_trt_node import trt_node


class CopyTests(unittest.TestCase):
    def test_inference_and_publication_body_identical(self):
        original = Path('ros2/yolo_node.py').read_text()
        candidate = trt_node(original)
        self.assertEqual(original.split('        self.loaded.set()\n        while')[1], candidate.split('        self.loaded.set()\n        while')[1])
        self.assertIn('backend.bindings["images"].dtype not in (np.float16, np.float32)', candidate)
        compile(candidate, 'trt_node', 'exec')

    def test_installed_backend_format_guard(self):
        tree = ast.parse(trt_node(Path('ros2/yolo_node.py').read_text()))
        test = next(n.test for n in ast.walk(tree) if isinstance(n, ast.If) and any(isinstance(x, ast.Attribute) and x.attr == 'bindings' for x in ast.walk(n.test)))
        code = compile(ast.Expression(test), '<guard>', 'eval')
        np = SimpleNamespace(float16='float16', float32='float32')
        backend = SimpleNamespace(format='engine', device=SimpleNamespace(type='cuda'), bindings={'images': SimpleNamespace(dtype='float32')})
        self.assertFalse(eval(code, {'backend': backend, 'np': np}))
        backend.format = 'pt'
        self.assertTrue(eval(code, {'backend': backend, 'np': np}))

    def test_missing_block_rejected(self):
        with self.assertRaises(ValueError):
            trt_node('incorrect source')
