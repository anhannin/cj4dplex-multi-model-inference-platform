import unittest
from pathlib import Path


class IdleFaultTests(unittest.TestCase):
    def test_idle_gate_synchronizes_actual_worker_and_blocks_gpu_until_release(self):
        from diagnostics.fault_idle.generate import add_idle_gate

        source = Path(
            "results/static-eval/20261110-v1-generated/yolo_burst_node.py"
        ).read_text()
        code = add_idle_gate(source)
        compile(code, "idle-gated", "exec")
        self.assertIn("torch.cuda.synchronize()", code)
        self.assertIn("idle_ack", code)
        self.assertIn("self.requests.empty()", code)
        self.assertIn("while idle_gate.exists()", code)
        self.assertNotIn("green_bridge", code)

    def test_k8s_observation_detects_termination_and_new_container(self):
        from diagnostics.fault_idle.metrics import pod_snapshot, transition

        old = pod_snapshot(
            {
                "metadata": {"uid": "podA", "name": "y"},
                "status": {
                    "containerStatuses": [
                        {
                            "name": "yolo",
                            "containerID": "containerd://old",
                            "restartCount": 0,
                            "ready": True,
                            "state": {"running": {"startedAt": "old"}},
                        }
                    ]
                },
            }
        )
        down = pod_snapshot(
            {
                "metadata": {"uid": "podA"},
                "status": {
                    "containerStatuses": [
                        {
                            "name": "yolo",
                            "containerID": "",
                            "restartCount": 0,
                            "ready": False,
                            "state": {
                                "terminated": {"exitCode": 137, "reason": "Error"}
                            },
                        }
                    ]
                },
            }
        )
        new = pod_snapshot(
            {
                "metadata": {"uid": "podA"},
                "status": {
                    "containerStatuses": [
                        {
                            "name": "yolo",
                            "containerID": "containerd://new",
                            "restartCount": 1,
                            "ready": False,
                            "state": {"running": {"startedAt": "new"}},
                            "lastState": {"terminated": {"exitCode": 137}},
                        }
                    ]
                },
            }
        )
        self.assertTrue(transition(old, down)["detected"])
        self.assertTrue(transition(old, new)["restarted"])
        self.assertFalse(transition(old, new)["ready"])
        new["ready"] = True
        self.assertTrue(transition(old, new)["ready"])

    def test_fault_signal_is_never_allowed_for_an_unverified_pid(self):
        from diagnostics.fault_idle.metrics import validate_target

        self.assertTrue(
            validate_target(
                123,
                1000,
                "python /experiment/src/yolo_burst_node.py --ros-args",
                {"qwen": 122, "yolo": 123},
                [122, 123],
            )
        )
        for pid, uid, cmd in (
            (122, 1000, "python /experiment/src/qwen_burst_node.py"),
            (123, 0, "python /experiment/src/yolo_burst_node.py"),
            (999, 1000, "python /experiment/src/yolo_burst_node.py"),
        ):
            with self.assertRaises(ValueError):
                validate_target(pid, uid, cmd, {"qwen": 122, "yolo": 123}, [122, 123])
