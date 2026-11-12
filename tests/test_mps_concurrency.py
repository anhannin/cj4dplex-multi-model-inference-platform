import copy
import unittest


class MpsTemplateTests(unittest.TestCase):
    def test_private_absolute_socket_mount_and_unchanged_input(self):
        from diagnostics.mps_concurrency.overlay import with_mps

        original = {
            "spec": {
                "containers": [
                    {
                        "env": [{"name": "ROS_DOMAIN_ID", "value": "42"}],
                        "volumeMounts": [],
                    }
                ],
                "volumes": [],
            }
        }
        old = copy.deepcopy(original)
        result = with_mps(original, "/home/avees/cj-mps/pipe")
        self.assertEqual(original, old)
        self.assertEqual(with_mps(result, "/home/avees/cj-mps/pipe"), result)
        env = {e["name"]: e["value"] for e in result["spec"]["containers"][0]["env"]}
        self.assertEqual(env["CUDA_MPS_PIPE_DIRECTORY"], "/home/avees/cj-mps/pipe")
        self.assertNotIn("CUDA_MPS_ACTIVE_THREAD_PERCENTAGE", env)
        self.assertEqual(
            result["spec"]["volumes"][0]["hostPath"]["path"],
            env["CUDA_MPS_PIPE_DIRECTORY"],
        )
        with self.assertRaises(ValueError):
            with_mps(original, "relative")

    def test_serving_keeps_normal_domain_protocol_and_no_benchmark_limits(self):
        import json
        from pathlib import Path
        from diagnostics.mps_concurrency.serving import serving_template

        for model in ("qwen", "yolo"):
            original = json.loads(Path(f"k8s/serving/{model}.json").read_text())[
                "spec"
            ]["template"]
            before = copy.deepcopy(original)
            t = serving_template(original, model, "/home/avees/cj-serving/mps-green-v1")
            self.assertEqual(original, before)
            c = t["spec"]["containers"][0]
            env = {e["name"]: e.get("value") for e in c["env"]}
            self.assertEqual(env["ROS_DOMAIN_ID"], "42")
            self.assertNotIn("BENCH_FORCE_LENGTH", env)
            self.assertNotIn("PROFILE_CAPTURE_SEQUENCE", env)
            self.assertEqual(
                env["GREEN_EXPECTED_SM"], "16" if model == "qwen" else "32"
            )
            self.assertNotIn("queue_capacity", str(c["command"]))
            self.assertNotIn("nsys", str(c["command"]))
            self.assertIn("nvidia-cuda-mps-control", str(c["command"]))
            self.assertEqual(
                c["resources"], before["spec"]["containers"][0]["resources"]
            )


class MpsEvidenceTests(unittest.TestCase):
    def test_hardware_events_can_be_attributed_to_client_not_server(self):
        from diagnostics.mps_concurrency.evidence import associated_residence

        intervals = [
            (0, 10, 99, 10),
            (10, 30, 101, 21),
            (30, 50, 101, 22),
            (50, 60, 102, 777),
        ]
        self.assertEqual(
            associated_residence(intervals, server=10, clients=[21, 22]), [(0, 50)]
        )
        self.assertEqual(
            associated_residence(intervals, server=10, clients=[]), [(0, 10)]
        )


class DeploymentLauncherTests(unittest.TestCase):
    def test_ros_pythonpath_is_preserved_when_adding_helper_path(self):
        from pathlib import Path

        script = Path("diagnostics/mps_concurrency/launch_deploy.sh").read_text()
        self.assertIn('source "$HOME/.config/cj-ros2/spark-jazzy.bash"', script)
        self.assertIn("${PYTHONPATH:-}", script)
        self.assertIn('python3 -c "import rclpy"', script)


class MpsRuntimeTests(unittest.TestCase):
    def test_stale_socket_without_daemon_pid_is_not_a_live_daemon(self):
        from tempfile import TemporaryDirectory
        from pathlib import Path
        from diagnostics.mps_concurrency.runtime import live_daemon_pid

        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "control").touch()
            self.assertIsNone(live_daemon_pid(root))

    def test_deploy_readiness_requires_live_daemon_not_only_socket(self):
        from pathlib import Path

        text = Path("diagnostics/mps_concurrency/deploy.py").read_text()
        self.assertIn('live_daemon_pid(ROOT / "mps-pipe")', text)
