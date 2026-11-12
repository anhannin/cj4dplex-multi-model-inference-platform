import copy
import json
from pathlib import Path
import unittest


class MpsBurstPlanTests(unittest.TestCase):
    def test_schedule_five_complete_randomized_blocks(self):
        from diagnostics.mps_burst.plan import schedule, CONDITIONS

        rows = schedule()
        self.assertEqual(len(rows), 35)
        self.assertEqual(rows, schedule())
        self.assertEqual(len({r["label"] for r in rows}), 35)
        self.assertEqual(len(CONDITIONS), 7)
        for n in range(5):
            selected = [r["condition"] for r in rows if r["round"] == n]
            self.assertEqual(set(selected), set(CONDITIONS))
            self.assertEqual(len(selected), 7)
        self.assertNotEqual(
            [r["condition"] for r in rows[:7]], [r["condition"] for r in rows[7:14]]
        )

    def test_templates_only_change_scheduler_not_workload_contract(self):
        from diagnostics.mps_burst.plan import condition_template, CONDITIONS

        for m in ("qwen", "yolo"):
            original = json.loads(Path(f"k8s/serving/{m}.json").read_text())["spec"][
                "template"
            ]
            before = copy.deepcopy(original)
            for name, case in CONDITIONS.items():
                t = condition_template(
                    original, m, case, "/experiment-root", "label", "/private/mps"
                )
                c = t["spec"]["containers"][0]
                env = {e["name"]: e.get("value") for e in c["env"]}
                self.assertEqual(env["ROS_DOMAIN_ID"], "74")
                self.assertEqual(env["BENCH_FORCE_LENGTH"], "1")
                self.assertEqual(env["GREEN_ENABLED"], str(int(case["green"])))
                self.assertEqual("CUDA_MPS_PIPE_DIRECTORY" in env, case["mps"])
                self.assertNotIn("CUDA_MPS_ACTIVE_THREAD_PERCENTAGE", env)
                self.assertNotIn("nsys", str(c["command"]))
                self.assertIn(
                    "queue_capacity:=16" if m == "qwen" else "queue_capacity:=512",
                    str(c["command"]),
                )
                self.assertEqual(
                    c["resources"], before["spec"]["containers"][0]["resources"]
                )
            self.assertEqual(original, before)

    def test_membership_is_exact_not_merely_two_arbitrary_clients(self):
        from diagnostics.mps_burst.plan import check_membership

        self.assertTrue(check_membership([101, 102], [101, 102], True))
        self.assertTrue(check_membership([], [101, 102], False))
        with self.assertRaises(ValueError):
            check_membership([201, 202], [101, 102], True)
        with self.assertRaises(ValueError):
            check_membership([101], [101, 102], True)
        with self.assertRaises(ValueError):
            check_membership([101, 102], [101, 102], False)
