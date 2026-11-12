import json
from pathlib import Path
import unittest
from diagnostics.green_burst.generate import render_burst_node, burst_template
from diagnostics.green_burst.metrics import (
    burst_completion,
    request_parts,
    select_candidate,
)


class BurstTests(unittest.TestCase):
    def test_complete_shared_origin_not_mean_request_latency(self):
        rows = [
            {
                "model": "qwen",
                "request_id": "q",
                "sent_ns": 10,
                "received_ns": 110,
                "status": "ok",
            },
            {
                "model": "yolo",
                "request_id": "y",
                "sent_ns": 30,
                "received_ns": 90,
                "status": "ok",
            },
        ]
        result = burst_completion(rows, 0, {"qwen": 1, "yolo": 1})
        self.assertEqual(result["overall_completion_ms"], 110 / 1e6)
        self.assertEqual(result["model_completion_ms"]["yolo"], 90 / 1e6)
        with self.assertRaises(ValueError):
            burst_completion(rows, 0, {"qwen": 1, "yolo": 2})
        with self.assertRaises(ValueError):
            burst_completion(rows + rows[:1], 0, {"qwen": 2, "yolo": 1})

    def test_no_gpu_double_counting(self):
        r = request_parts(100, 60, 30, 20, 10)
        self.assertEqual(
            r,
            {
                "app_queue_ms": 60,
                "model_pipeline_ms": 20,
                "server_nonpipeline_ms": 10,
                "transport_client_residual_ms": 10,
                "gpu_forward_span_ms": 10,
            },
        )
        self.assertEqual(sum(r[k] for k in r if k != "gpu_forward_span_ms"), 100)

    def test_rank_total_then_cv_within_predeclared_tie_band(self):
        result = select_candidate(
            [
                {"label": "default", "total_mean_ms": 100, "yolo_mean_ms": 10},
                {"label": "green", "total_mean_ms": 99, "yolo_mean_ms": 20},
            ]
        )
        self.assertEqual(result["strict_fastest"], "green")
        self.assertEqual(result["balanced_selected"], "default")

    def test_capacity_qos_and_actual_gpu_observer(self):
        for model, capacity in [("qwen", 16), ("yolo", 512)]:
            source = render_burst_node(Path(f"ros2/{model}_node.py").read_text(), model)
            compile(source, "candidate", "exec")
            self.assertIn(
                "QoSProfile(depth=512, durability=DurabilityPolicy.TRANSIENT_LOCAL)",
                source,
            )
            self.assertIn("ForwardTimer", source)
            self.assertIn("gpu_forward_span_ms", source)
            self.assertIn("server_enqueued_perf_ns", source)
            orig = json.loads(Path(f"k8s/serving/{model}.json").read_text())["spec"][
                "template"
            ]
            template = burst_template(orig, model, 16, 32, "/x", "test")
            command = template["spec"]["containers"][0]["command"][-1]
            self.assertIn(f"queue_capacity:={capacity}", command)
            env = {
                x["name"]: x.get("value")
                for x in template["spec"]["containers"][0]["env"]
            }
            self.assertEqual(env["ROS_DOMAIN_ID"], "74")
