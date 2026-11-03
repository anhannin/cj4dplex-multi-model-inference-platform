"""Lock the agreed minimal single-Spark serving contract."""

import json
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1] / "k8s" / "serving"


class ServingManifestTests(unittest.TestCase):
    def test_independent_single_workers_with_shared_gpu_and_no_cpu_ram_caps(self):
        for kind in ("qwen", "yolo"):
            data = json.loads((ROOT / (kind + ".json")).read_text())
            spec = data["spec"]
            self.assertEqual(spec["replicas"], 1)
            self.assertEqual(spec["strategy"]["type"], "Recreate")
            pod = spec["template"]["spec"]
            self.assertTrue(pod["hostNetwork"])
            self.assertTrue(pod["hostIPC"])
            self.assertFalse(pod["automountServiceAccountToken"])
            self.assertEqual(pod["runtimeClassName"], "nvidia")
            self.assertEqual(len(pod["containers"]), 1)
            c = pod["containers"][0]
            self.assertEqual(c["imagePullPolicy"], "Never")
            self.assertEqual(c["resources"]["limits"], {"nvidia.com/gpu.shared": 1})
            self.assertEqual(c["resources"]["requests"]["nvidia.com/gpu.shared"], 1)
            self.assertNotIn("livenessProbe", c)
            self.assertEqual(c["startupProbe"]["failureThreshold"], 120)
            for volume in pod["volumes"]:
                if "hostPath" in volume:
                    mount = next(
                        x for x in c["volumeMounts"] if x["name"] == volume["name"]
                    )
                    self.assertTrue(mount["readOnly"])
            env = {x["name"]: x["value"] for x in c["env"]}
            self.assertEqual(env["ROS_DOMAIN_ID"], "42")
            self.assertNotIn("NVIDIA_VISIBLE_DEVICES", env)

    def test_device_plugin_sharing_is_two_access_references_not_mps(self):
        data = json.loads((ROOT / "gpu-sharing.json").read_text())["data"][
            "config.yaml"
        ]
        self.assertIn("timeSlicing:", data)
        self.assertIn("replicas: 2", data)
        self.assertIn("renameByDefault: true", data)
        self.assertIn("failRequestsGreaterThanOne: true", data)
        self.assertNotIn("mps:", data)
