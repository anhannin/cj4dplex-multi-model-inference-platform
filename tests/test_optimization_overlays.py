import copy
import json
from pathlib import Path
import unittest

from optimization.overlays import candidate_template, template_patch


class OverlayTests(unittest.TestCase):
    def setUp(self):
        self.original = json.loads(Path('k8s/serving/yolo.json').read_text())['spec']['template']

    def test_control_exact_and_nonmutating(self):
        before = copy.deepcopy(self.original)
        self.assertEqual(candidate_template(self.original, 'control', 'yolo', '/x'), before)
        candidate_template(self.original, 'dds', 'yolo', '/x')
        self.assertEqual(self.original, before)

    def test_dds_preserves_resources_and_protocol_code(self):
        t = candidate_template(self.original, 'dds', 'yolo', '/x')
        old = self.original['spec']['containers'][0]
        new = t['spec']['containers'][0]
        self.assertEqual(new['resources'], old['resources'])
        self.assertEqual(new['image'], old['image'])
        self.assertNotIn('command', new)
        self.assertIn({'name': 'FASTRTPS_DEFAULT_PROFILES_FILE', 'value': '/experiment/config/low-latency.xml'}, new['env'])

    def test_affinity_disjoint_fast_cores(self):
        q = candidate_template(self.original, 'affinity', 'qwen', '/x')['spec']['containers'][0]
        y = candidate_template(self.original, 'affinity', 'yolo', '/x')['spec']['containers'][0]
        self.assertIn('5-9', q['command'][-1])
        self.assertIn('15-19', y['command'][-1])

    def test_combination_keeps_q75_cap_and_trt(self):
        t = candidate_template(self.original, 'trt-dds-mps-q75', 'yolo', '/x')
        c = t['spec']['containers'][0]
        self.assertIn('/experiment/src/yolo_trt_node.py', c['command'][-1])
        env = {e['name']: e.get('value') for e in c['env']}
        self.assertEqual(env['CUDA_MPS_ACTIVE_THREAD_PERCENTAGE'], '100')
        self.assertIn('FASTRTPS_DEFAULT_PROFILES_FILE', env)
        q = candidate_template(self.original, 'trt-dds-mps-q75', 'qwen', '/x')
        envq = {e['name']: e.get('value') for e in q['spec']['containers'][0]['env']}
        self.assertEqual(envq['CUDA_MPS_ACTIVE_THREAD_PERCENTAGE'], '75')

    def test_restore_replaces_template_not_merge_stale_annotations(self):
        patch = template_patch(self.original)
        self.assertEqual(patch, [{'op': 'replace', 'path': '/spec/template', 'value': self.original}])

    def test_unknown_rejected(self):
        with self.assertRaises(ValueError):
            candidate_template(self.original, 'typo', 'yolo', '/x')


if __name__ == '__main__':
    unittest.main()
