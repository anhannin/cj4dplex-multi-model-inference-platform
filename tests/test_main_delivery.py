"""Static delivery checks: navigation and build inputs, not GPU execution claims."""

import json
from pathlib import Path
import re
import shlex
import unittest
from scripts.check_submission import DOCS, local_links

ROOT = Path(__file__).resolve().parents[1]


class MainDeliveryContracts(unittest.TestCase):
    def test_new_navigation_is_covered_by_submission_checker(self):
        for name in ("EXPERIMENT_INDEX", "IMPLEMENTATION", "DEPLOYMENT_MODES"):
            self.assertIn("docs/" + name + ".ko.md", DOCS)
        for folder in (
            "01_baseline",
            "02_bottleneck_analysis",
            "03_sm_sensitivity",
            "04_hypothesis_validation",
            "05_static_mps_optimization",
            "06_fault_recovery",
        ):
            path = "experiments/" + folder + "/README.md"
            self.assertIn(path, DOCS)
            text = (ROOT / path).read_text()
            for heading in (
                "Objective",
                "Hypothesis",
                "Environment",
                "Workload",
                "Configuration",
                "Methodology",
                "Metrics",
                "Results",
                "Analysis",
                "Limitations",
                "Artifacts",
            ):
                self.assertIn("## " + heading, text)

    def test_primary_readme_structure_and_links_preserved(self):
        text = (ROOT / "README.md").read_text()
        headings = re.findall(r"^## (\d+)\.", text, re.M)
        self.assertEqual(headings, [str(i) for i in range(1, 10)])
        self.assertNotIn("](figures/system-architecture.svg)", text)
        for target in local_links(text):
            self.assertTrue((ROOT / target).exists(), target)
        self.assertFalse((ROOT / "serving").exists())
        self.assertFalse((ROOT / "api").exists())
        self.assertTrue((ROOT / "k8s/serving").is_dir())

    def test_retained_docker_copy_sources_exist(self):
        checked = 0
        for path in (ROOT / "containers").rglob("Dockerfile*"):
            for line in path.read_text().splitlines():
                if not line.startswith("COPY "):
                    continue
                tokens = shlex.split(line)
                if any(t.startswith("--from=") for t in tokens):
                    continue
                sources = [t for t in tokens[1:-1] if not t.startswith("--")]
                for src in sources:
                    self.assertTrue((ROOT / src).exists(), f"{path}: COPY {src}")
                    checked += 1
        self.assertGreaterEqual(checked, 4)

    def test_core_deployment_volume_and_gpu_references(self):
        for model in ("qwen", "yolo"):
            deployment = json.loads((ROOT / f"k8s/serving/{model}.json").read_text())
            self.assertEqual(deployment["kind"], "Deployment")
            self.assertEqual(deployment["spec"]["replicas"], 1)
            pod = deployment["spec"]["template"]["spec"]
            self.assertTrue(pod["hostIPC"])
            self.assertTrue(pod["hostNetwork"])
            volumes = {v["name"] for v in pod["volumes"]}
            for container in pod["containers"]:
                self.assertEqual(
                    container["resources"]["limits"]["nvidia.com/gpu.shared"], 1
                )
                self.assertEqual(container["imagePullPolicy"], "Never")
                for mount in container["volumeMounts"]:
                    self.assertIn(mount["name"], volumes)

    def test_summary_matches_burst_scope(self):
        text = (ROOT / "docs/EXECUTIVE_SUMMARY.ko.md").read_text()
        self.assertNotIn("15req/s", text)
        self.assertNotIn("8req/s", text)
        for value in ("28.98", "28.66", "4.163", "4.504"):
            self.assertIn(value, text)

    def test_readme_key_values_match_native_summary(self):
        summary = json.loads(
            (ROOT / "results/static-eval/20261110-v1/analysis/summary.json").read_text()
        )
        cases = {c["label"]: c for c in summary["conditions"]}
        text = (ROOT / "README.md").read_text()
        specs = [
            ("전체 310건 완료시간", None, "total_ms", "mean"),
            ("YOLO 300건 완료시간", None, "yolo_ms", "mean"),
            ("YOLO 요청 E2E p95", "yolo", "request_e2e_ms", "p95"),
            ("Qwen 요청 E2E p95", "qwen", "request_e2e_ms", "p95"),
            ("Qwen 내부 Generate TTFT p95", "qwen", "generate_ttft_ms", "p95"),
        ]
        for label, model, key, stat in specs:
            line = next(
                row for row in text.splitlines() if row.startswith("| " + label + " |")
            )
            got = re.findall(r"\d+\.\d+", line)
            wanted = []
            for name in ("control", "mps-only", "static-q8-y40"):
                value = (
                    cases[name][key][stat]
                    if model is None
                    else cases[name]["models"][model]["pooled_descriptive"][key][stat]
                )
                scale = 1 if key == "generate_ttft_ms" else 1000
                wanted.append(f"{value / scale:.3f}")
            self.assertEqual(got, wanted, label)
