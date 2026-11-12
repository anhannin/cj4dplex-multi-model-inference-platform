import importlib.util
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]


def load():
    spec = importlib.util.spec_from_file_location(
        "nsight_generate", ROOT / "diagnostics/nsight/generate.py"
    )
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


class DiagnosticGenerationTests(unittest.TestCase):
    def test_only_instruments_derived_copies(self):
        generate = load()
        for model in ("qwen", "yolo"):
            source = (ROOT / f"ros2/{model}_node.py").read_text()
            result = generate.instrument(model, source)
            compile(result, "diagnostic", "exec")
            self.assertIn("torch.cuda.profiler.start()", result)
            self.assertIn("torch.cuda.profiler.stop()", result)
            self.assertIn(f'"{model}.', result)
            self.assertNotIn("CUDA_MPS", result)
            self.assertEqual(
                source.count("model.generate("), result.count("model.generate(")
            )
            self.assertEqual(
                source.count("model.predict("), result.count("model.predict(")
            )
            self.assertIn("self.requests.get(timeout=0.1)", result)
            self.assertIn("torch.set_num_threads(4)", result)
            self.assertEqual((ROOT / f"ros2/{model}_node.py").read_text(), source)

    def test_baseline_benchmark_remains_unchanged_but_diagnostic_allows_no_extra_warmup(
        self,
    ):
        generate = load()
        source = (ROOT / "benchmark/bench_ros2.py").read_text()
        result = generate.benchmark_copy(source)
        self.assertIn("a.warmup < 0", result)
        self.assertIn("a.warmup < 1", source)
        compile(result, "diagnostic-benchmark", "exec")


class DeploymentProfileTests(unittest.TestCase):
    def test_keeps_image_resources_and_security_while_adding_only_diagnostic_launch(
        self,
    ):
        import copy

        spec = importlib.util.spec_from_file_location(
            "nsight_run", ROOT / "diagnostics/nsight/run.py"
        )
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        source = {
            "apiVersion": "apps/v1",
            "kind": "Deployment",
            "metadata": {"name": "qwen", "namespace": "cj-inference"},
            "spec": {
                "replicas": 1,
                "template": {
                    "spec": {
                        "containers": [
                            {
                                "name": "qwen",
                                "image": "baseline",
                                "resources": {"limits": {"nvidia.com/gpu.shared": 1}},
                                "securityContext": {"allowPrivilegeEscalation": False},
                                "volumeMounts": [],
                            }
                        ],
                        "volumes": [],
                    }
                },
            },
        }
        old = copy.deepcopy(source)
        result = module.make_diagnostic(source, "qwen", "/home/avees/test")
        c = result["spec"]["template"]["spec"]["containers"][0]
        self.assertEqual(c["image"], "baseline")
        self.assertEqual(
            c["resources"],
            source["spec"]["template"]["spec"]["containers"][0]["resources"],
        )
        self.assertEqual(
            c["securityContext"],
            source["spec"]["template"]["spec"]["containers"][0]["securityContext"],
        )
        self.assertEqual(source, old)
        self.assertIn("launch_node.sh", " ".join(c["command"]))


class HostClientEnvironmentTests(unittest.TestCase):
    def test_preserves_sourced_ros_pythonpath_and_runtime_library_environment(self):
        spec = importlib.util.spec_from_file_location(
            "nsight_run_env", ROOT / "diagnostics/nsight/run.py"
        )
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        original = {
            "PYTHONPATH": "/opt/ros/jazzy/lib/python3.12/site-packages",
            "LD_LIBRARY_PATH": "/opt/ros/jazzy/lib",
            "ROS_DOMAIN_ID": "42",
        }
        result = module.benchmark_environment(original, "/home/avees/cj-ros2/benchmark")
        self.assertTrue(
            result["PYTHONPATH"].startswith("/home/avees/cj-ros2/benchmark:")
        )
        self.assertIn("/opt/ros/jazzy", result["PYTHONPATH"])
        self.assertEqual(result["LD_LIBRARY_PATH"], original["LD_LIBRARY_PATH"])
        self.assertEqual(result["ROS_DOMAIN_ID"], "42")
        self.assertNotEqual(result, original)


class CaptureMappingTests(unittest.TestCase):
    def test_deferred_reports_are_mapped_after_profiler_shutdown(self):
        spec = importlib.util.spec_from_file_location(
            "nsight_run_mapping", ROOT / "diagnostics/nsight/run.py"
        )
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        result = module.map_capture_files(
            ["capture.3.nsys-rep", "capture.1.nsys-rep", "capture.2.nsys-rep"],
            ["qwen-only", "yolo-only", "concurrent"],
        )
        self.assertEqual(
            result,
            {
                "qwen-only": "capture.1.nsys-rep",
                "yolo-only": "capture.2.nsys-rep",
                "concurrent": "capture.3.nsys-rep",
            },
        )
        with self.assertRaises(AssertionError):
            module.map_capture_files(["capture.nsys-rep"], ["a", "b", "c"])


class ShutdownStateTests(unittest.TestCase):
    def test_automatic_session_close_is_accepted_only_with_all_reports(self):
        spec = importlib.util.spec_from_file_location(
            "nsight_shutdown", ROOT / "diagnostics/nsight/run.py"
        )
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        self.assertFalse(module.needs_shutdown([], "ours", 3))
        self.assertTrue(
            module.needs_shutdown([{"name": "ours", "accessible": True}], "ours", 0)
        )
        with self.assertRaises(AssertionError):
            module.needs_shutdown([], "ours", 2)
