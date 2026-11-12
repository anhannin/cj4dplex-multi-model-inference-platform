import copy
import json
from pathlib import Path
import unittest
from diagnostics.green_e2e.generate import (
    render_node,
    make_template,
    classify_change,
    combinations,
)


class GreenE2ETests(unittest.TestCase):
    def test_combinations_complement(self):
        pairs = combinations()
        self.assertEqual(set(pairs), {(8, 40), (16, 32), (24, 24), (32, 16), (40, 8)})
        self.assertTrue(all(q + y == 48 for q, y in pairs))

    def test_copies_keep_original_inference_calls_and_independent_nodes(self):
        for model in ("qwen", "yolo"):
            original = Path(f"ros2/{model}_node.py").read_text()
            code = render_node(original, model)
            compile(code, "candidate", "exec")
            self.assertIn("def _frozen_worker(self):", code)
            self.assertIn("self._frozen_worker()", code)
            self.assertIn("with torch.cuda.stream(stream):", code)
            self.assertIn("green_bridge.GreenPair", code)
            self.assertIn(f"/{model}/request", code)
            other = "yolo" if model == "qwen" else "qwen"
            self.assertNotIn(f"/{other}/request", code)
            if model == "qwen":
                self.assertEqual(code.count("output = model.generate("), 1)
                self.assertIn('generation_options["min_new_tokens"] = maximum', code)
            else:
                self.assertEqual(
                    code.count("result = model.predict(image, **options)[0]"), 1
                )

    def test_template_does_not_change_baseline_or_resources(self):
        original = json.loads(Path("k8s/serving/qwen.json").read_text())["spec"][
            "template"
        ]
        before = copy.deepcopy(original)
        t = make_template(original, "qwen", 16, 32, "/x", "q16-y32")
        self.assertEqual(original, before)
        c = t["spec"]["containers"][0]
        self.assertEqual(c["resources"], before["spec"]["containers"][0]["resources"])
        env = {e["name"]: e.get("value") for e in c["env"]}
        self.assertEqual(env["ROS_DOMAIN_ID"], "73")
        self.assertEqual(env["GREEN_PARTITION_INDEX"], "1")
        self.assertEqual(env["GREEN_LEFT_SMS"], "32")
        self.assertNotIn("CUDA_MPS_PIPE_DIRECTORY", env)

    def test_descriptive_band_not_equivalence_test(self):
        self.assertEqual(classify_change(100, 104)["classification"], "near_equal")
        self.assertEqual(classify_change(100, 130)["classification"], "slower")
        self.assertEqual(classify_change(100, 80)["classification"], "faster")
        self.assertAlmostEqual(classify_change(100, 130)["change_percent"], 30)


class ProtocolPreservationTests(unittest.TestCase):
    def test_all_nonworker_node_methods_are_unchanged(self):
        import ast

        for model in ("qwen", "yolo"):
            original = Path(f"ros2/{model}_node.py").read_text()
            rendered = render_node(original, model)
            a = next(
                n
                for n in ast.parse(original).body
                if isinstance(n, ast.ClassDef) and n.name.endswith("Node")
            )
            b = next(
                n
                for n in ast.parse(rendered).body
                if isinstance(n, ast.ClassDef) and n.name == a.name
            )
            actual = {n.name: n for n in b.body if isinstance(n, ast.FunctionDef)}
            for node in a.body:
                if isinstance(node, ast.FunctionDef) and node.name != "_worker":
                    self.assertEqual(
                        ast.dump(node), ast.dump(actual[node.name]), (model, node.name)
                    )


class DetectionAuditTests(unittest.TestCase):
    def test_fixed_image_fidelity_gate(self):
        from diagnostics.green_e2e.audit import detection_fidelity

        ref = [{"class_id": 0, "confidence": 0.8, "xyxy": [0, 0, 100, 100]}]
        detection_fidelity(ref, ref)
        with self.assertRaises(AssertionError):
            detection_fidelity(
                ref, [{"class_id": 0, "confidence": 0.8, "xyxy": [50, 50, 100, 100]}]
            )
        with self.assertRaises(AssertionError):
            detection_fidelity(
                ref, [{"class_id": 1, "confidence": 0.8, "xyxy": [0, 0, 100, 100]}]
            )
