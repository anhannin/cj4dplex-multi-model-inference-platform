import unittest


class StaticPlanTests(unittest.TestCase):
    def test_partition_output_requires_created_id_not_error(self):
        from diagnostics.mps_static.config import parse_partition

        self.assertEqual(
            parse_partition("Partition GPU-123/abc created\n"), "GPU-123/abc"
        )
        self.assertEqual(parse_partition("GPU-123/abc\n"), "GPU-123/abc")
        with self.assertRaises(ValueError):
            parse_partition("Failed to create partition")

    def test_static_env_has_partition_not_dynamic_quota_or_green(self):
        from diagnostics.mps_static.config import static_env

        env = static_env("/pipe", "GPU-123/abc", "/compat")
        self.assertEqual(env["CUDA_MPS_SM_PARTITION"], "GPU-123/abc")
        self.assertEqual(env["CUDA_MPS_PIPE_DIRECTORY"], "/pipe")
        self.assertNotIn("CUDA_MPS_ACTIVE_THREAD_PERCENTAGE", env)
        self.assertNotIn("GREEN_ENABLED", env)


class StaticServingTests(unittest.TestCase):
    def test_native_worker_has_no_green_api_and_uses_mps_visible_count(self):
        from diagnostics.mps_static.generate import render_static_node
        from pathlib import Path

        for model in ("qwen", "yolo"):
            code = render_static_node(Path(f"ros2/{model}_node.py").read_text(), model)
            compile(code, "static-node", "exec")
            self.assertNotIn("green_bridge", code)
            self.assertNotIn("GreenPair", code)
            self.assertIn("EXPECTED_SMS", code)
            self.assertIn("multi_processor_count", code)
            self.assertIn("CUDA_MPS_SM_PARTITION", code)
            self.assertIn("self._frozen_worker()", code)
            self.assertIn("self._green_mode = False", code)

    def test_static_plan_is_7_conditions_5_rounds_and_no_green(self):
        from diagnostics.mps_static.plan import schedule, CONDITIONS

        rows = schedule()
        self.assertEqual(len(rows), 35)
        self.assertEqual(len(CONDITIONS), 7)
        for n in range(5):
            self.assertEqual(
                {r["condition"] for r in rows if r["round"] == n}, set(CONDITIONS)
            )
        self.assertTrue(all(not r["green"] for r in rows))
        self.assertEqual(
            {(r["qsm"], r["ysm"]) for r in rows if r["static"]},
            {(8, 40), (16, 32), (24, 24), (32, 16), (40, 8)},
        )

    def test_native_static_template_has_no_compat_or_green_and_fixed_inputs(self):
        import json
        import copy
        from pathlib import Path
        from diagnostics.mps_static.plan import condition_template, CONDITIONS

        for model in ("qwen", "yolo"):
            old = json.loads(Path(f"k8s/serving/{model}.json").read_text())["spec"][
                "template"
            ]
            before = copy.deepcopy(old)
            for case in CONDITIONS.values():
                t = condition_template(
                    old,
                    model,
                    case,
                    "/rootx",
                    "label",
                    "/pipe",
                    {"qwen": "GPU-test/Q", "yolo": "GPU-test/Y"},
                )
                c = t["spec"]["containers"][0]
                env = {e["name"]: e.get("value") for e in c["env"]}
                self.assertFalse(any(k.startswith("GREEN_") for k in env))
                self.assertNotIn("CUDA_MPS_ACTIVE_THREAD_PERCENTAGE", env)
                self.assertNotIn("compat", env["LD_LIBRARY_PATH"])
                self.assertEqual(
                    env["EXPECTED_SMS"],
                    str(case["qsm"] if model == "qwen" else case["ysm"]),
                )
                self.assertEqual("CUDA_MPS_PIPE_DIRECTORY" in env, case["mps"])
                self.assertEqual("CUDA_MPS_SM_PARTITION" in env, case["static"])
                self.assertEqual(env["BENCH_FORCE_LENGTH"], "1")
                self.assertEqual(env["ROS_DOMAIN_ID"], "74")
                self.assertEqual(
                    c["resources"], before["spec"]["containers"][0]["resources"]
                )
            self.assertEqual(old, before)


class RankingTests(unittest.TestCase):
    def test_descriptive_total_tie_band_then_cv_priority(self):
        from diagnostics.mps_static.summary_math import ranking

        rows = [
            {"label": "fast", "total": 100, "cv": 20},
            {"label": "cv", "total": 102, "cv": 10},
            {"label": "slow", "total": 110, "cv": 9},
        ]
        r = ranking(rows, 0.03)
        self.assertEqual(r["strict_fastest"], "fast")
        self.assertEqual(r["balanced"], "cv")
        self.assertEqual(set(r["pareto"]), {"fast", "cv", "slow"})
        self.assertEqual(ranking(rows, 0)["balanced"], "fast")
