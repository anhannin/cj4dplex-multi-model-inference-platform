"""Submission pruning must not remove baseline-to-optimization dependency paths."""

import ast
import hashlib
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]


class FinalSourceLayout(unittest.TestCase):
    def test_obsolete_http_and_waiter_entrypoints_are_absent(self):
        paths = [
            "api",
            "serving",
            "clients/http",
            "requirements-api.txt",
            "scripts/build_serving.sh",
            "scripts/start_serving.sh",
            "scripts/start_singlefile_api.sh",
            "scripts/smoke_serving.py",
            "scripts/launch_remote.sh",
            "scripts/run_preflight.py",
            "containers/start-dev.sh",
            "diagnostics/sustained/collect_when_done.py",
            "benchmark/watch_run.py",
            "optimization/watch_sweep.py",
            "optimization/export_after_sweep.sh",
            "optimization/final_after_control.sh",
            "optimization/confirm_control_after_factorial.sh",
            "optimization/probe_green_mapping_after_backend.sh",
            "optimization/run_remaining_after_probe.sh",
        ]
        for path in paths:
            with self.subTest(path=path):
                self.assertFalse((ROOT / path).exists())

    def test_final_and_baseline_dependency_sources_are_present(self):
        paths = [
            "ros2/qwen_node.py",
            "ros2/yolo_node.py",
            "clients/request_qwen.py",
            "clients/request_yolo.py",
            "scripts/worker.py",
            "scripts/build_images.sh",
            "scripts/acceleration.py",
            "scripts/metrics.py",
            "scripts/run_containers.py",
            "scripts/check_gpu_kernels.py",
            "scripts/check_installed_sources.py",
            "benchmark/run_five_phases.sh",
            "benchmark/monitor_host.py",
            "k8s/serving/qwen.json",
            "k8s/serving/yolo.json",
            "diagnostics/mps_static/eval_runner.py",
            "diagnostics/mps_static/profile_runner.py",
            "diagnostics/sustained/controller.py",
            "diagnostics/sustained/client.py",
            "diagnostics/fault_idle/controller.py",
            "diagnostics/fault_idle/resource_supervisor.py",
            "diagnostics/sm_sweep/controller.py",
            "diagnostics/green_burst/generate.py",
            "diagnostics/green_e2e/generate.py",
            "diagnostics/mps_burst/runner.py",
            "diagnostics/mps_concurrency/runtime.py",
            "diagnostics/kernel_overlap/runner.py",
            "optimization/live_logs.py",
            "optimization/run_sweep.py",
            "optimization/export_trt.py",
            "optimization/quality_trt.py",
            "optimization/final_confirmation.py",
        ]
        for path in paths:
            with self.subTest(path=path):
                self.assertTrue((ROOT / path).is_file())

    def test_retained_source_does_not_import_removed_http_stack(self):
        for folder in (
            "ros2",
            "clients",
            "scripts",
            "benchmark",
            "diagnostics",
            "optimization",
        ):
            for path in (ROOT / folder).rglob("*.py"):
                if "__pycache__" in path.parts:
                    continue
                for node in ast.walk(ast.parse(path.read_text())):
                    names = (
                        [node.module or ""]
                        if isinstance(node, ast.ImportFrom)
                        else [n.name for n in node.names]
                        if isinstance(node, ast.Import)
                        else []
                    )
                    for name in names:
                        self.assertNotIn(
                            name.split(".")[0],
                            ("fastapi", "uvicorn", "httpx", "httpx2", "api", "serving"),
                            str(path),
                        )

    def test_cleanup_manifest_accepts_only_exact_approved_state(self):
        from scripts.check_submission import unexpected_worktree_changes

        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / "requirements-dev.txt").write_text("Pillow\n")
            (root / "README.md").write_text("New docs\n")
            digest = hashlib.sha256(b"Pillow\n").hexdigest()
            manifest = {
                "removed": [{"path": "api/x.py"}],
                "updated": [
                    {"path": "requirements-dev.txt", "sha256": digest},
                    {
                        "path": "README.md",
                        "sha256": hashlib.sha256(b"New docs\n").hexdigest(),
                    },
                ],
            }
            with patch("scripts.check_submission.ROOT", root):
                self.assertEqual(
                    unexpected_worktree_changes(
                        ["README.md", "api/x.py", "requirements-dev.txt"], manifest
                    ),
                    [],
                )
                self.assertEqual(
                    unexpected_worktree_changes(["ros2/qwen_node.py"], manifest),
                    ["ros2/qwen_node.py"],
                )
                (root / "requirements-dev.txt").write_text("wrong")
                self.assertEqual(
                    unexpected_worktree_changes(["requirements-dev.txt"], manifest),
                    ["requirements-dev.txt"],
                )


class ExactReadmeApproval(unittest.TestCase):
    def test_unapproved_readme_drift_is_not_hidden(self):
        from scripts.check_submission import unexpected_worktree_changes

        self.assertEqual(unexpected_worktree_changes(["README.md"], {}), ["README.md"])
