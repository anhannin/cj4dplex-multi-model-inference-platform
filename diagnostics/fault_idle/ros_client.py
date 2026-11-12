"""One publish per UUID, explicit patient transient-local recovery semantics."""

import json
import time
import uuid
from pathlib import Path


def atomic(path, value):
    path = Path(path)
    tmp = path.with_suffix(".new")
    tmp.write_text(json.dumps(value, ensure_ascii=False))
    tmp.replace(path)


class RosClient:
    def __init__(self, model):
        import rclpy
        from rclpy.qos import DurabilityPolicy, QoSProfile
        from std_msgs.msg import String

        self.rclpy, self.String, self.model = rclpy, String, model
        rclpy.init(args=[])
        self.node = rclpy.create_node("fault_" + model + "_" + uuid.uuid4().hex)
        self.publisher = self.node.create_publisher(
            String,
            "/" + model + "/request",
            QoSProfile(depth=1, durability=DurabilityPolicy.TRANSIENT_LOCAL),
        )
        self.sub = None
        self.response = None

    def prepare(self, run_id, payload):
        self.response = None
        self.rid = "r_" + uuid.uuid4().hex
        self.received_ns = None
        self.sent_ns = None
        envelope = {**payload, "request_id": self.rid, "run_id": run_id}
        self.encoded = json.dumps(envelope, ensure_ascii=False)

        def result(message):
            before = time.perf_counter_ns()
            r = json.loads(message.data)
            if r.get("request_id") == self.rid:
                self.response = r
                self.received_ns = time.perf_counter_ns()
                self.parse_ms = (self.received_ns - before) / 1e6

        self.sub = self.node.create_subscription(
            self.String, "/" + self.model + "/result/" + self.rid, result, 1
        )
        return self.rid

    def spin(self, seconds=0.01):
        self.rclpy.spin_once(self.node, timeout_sec=seconds)

    def wait_subscriber(self, timeout=90):
        deadline = time.monotonic() + timeout
        while self.publisher.get_subscription_count() == 0:
            if time.monotonic() > deadline:
                raise TimeoutError("No model request subscriber")
            self.spin(0.02)

    def send(self):
        self.matches_at_send = self.publisher.get_subscription_count()
        self.sent_ns = time.perf_counter_ns()
        self.sent_wall_ns = time.time_ns()
        self.publisher.publish(self.String(data=self.encoded))

    def wait_result(self, timeout=90):
        deadline = time.monotonic() + timeout
        while self.response is None:
            if time.monotonic() > deadline:
                raise TimeoutError("No matching result: " + self.rid)
            self.spin(0.02)
        r = self.response
        if r.get("status") != "ok":
            raise RuntimeError(r)
        if r.get("assigned_sms") != (8 if self.model == "qwen" else 40) or r.get(
            "green_enabled"
        ):
            raise RuntimeError("Wrong resource path")
        if self.model == "qwen" and (
            r.get("input_tokens") != 512 or r.get("output_tokens") != 128
        ):
            raise RuntimeError("Wrong fixed work")
        if self.model == "yolo" and r.get("gpu_forward_shape") != [1, 3, 640, 640]:
            raise RuntimeError("Wrong image shape")
        return {
            "model": self.model,
            "request_id": self.rid,
            "sent_ns": self.sent_ns,
            "sent_wall_ns": self.sent_wall_ns,
            "received_ns": self.received_ns,
            "request_e2e_ms": (self.received_ns - self.sent_ns) / 1e6,
            "matches_at_publish": self.matches_at_send,
            "publish_count": 1,
            "response": r,
        }

    def release(self, keep=0.2):
        deadline = time.monotonic() + keep
        while time.monotonic() < deadline:
            self.spin(0.01)
        if self.sub is not None:
            self.node.destroy_subscription(self.sub)
            self.sub = None

    def close(self):
        if self.sub is not None:
            self.node.destroy_subscription(self.sub)
        self.node.destroy_node()
        self.rclpy.try_shutdown()
