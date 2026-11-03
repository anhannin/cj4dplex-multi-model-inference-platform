# Historical v1 protocol only; for v2 run test_uuid_clients.py instead.
"""Native Spark-host ROS CLI + rclpy request test against resident containers."""

from array import array
import json
from pathlib import Path
import subprocess
import time
import uuid

import rclpy
from rclpy.node import Node
from sensor_msgs.msg import CompressedImage
from std_msgs.msg import String


def main():
    rclpy.init()
    node = Node("spark_native_host_check_" + uuid.uuid4().hex[:8])
    request_id = "spark-host-" + uuid.uuid4().hex
    received = {}
    image = CompressedImage()
    image.header.stamp = node.get_clock().now().to_msg()
    image.header.frame_id = "native_host_camera"
    image.format = "jpeg"
    image.data = array(
        "B", Path.home().joinpath("cj-containers/assets/bus.jpg").read_bytes()
    )
    stamp = {"sec": image.header.stamp.sec, "nanosec": image.header.stamp.nanosec}

    def q_callback(msg):
        result = json.loads(msg.data)
        if result.get("request_id") == request_id:
            received["qwen"] = result

    def y_callback(msg):
        result = json.loads(msg.data)
        if (
            result.get("source_stamp") == stamp
            and result.get("frame_id") == image.header.frame_id
        ):
            received["yolo"] = result

    qsub = node.create_subscription(String, "/qwen/result", q_callback, 32)
    ysub = node.create_subscription(String, "/yolo/result", y_callback, 32)
    publisher = node.create_publisher(CompressedImage, "/yolo/request", 32)
    command = None
    try:
        deadline = time.monotonic() + 45
        while not (
            qsub.get_publisher_count() >= 1
            and ysub.get_publisher_count() >= 1
            and publisher.get_subscription_count() >= 1
            and node.count_subscribers("/qwen/request") >= 1
        ):
            if time.monotonic() > deadline:
                raise TimeoutError("Native host could not discover model topics")
            rclpy.spin_once(node, timeout_sec=0.1)
        body = json.dumps(
            {
                "data": json.dumps(
                    {
                        "request_id": request_id,
                        "text": "Explain GPU resource contention in one sentence.",
                        "max_new_tokens": 32,
                    }
                )
            }
        )
        command = subprocess.Popen(
            [
                "ros2",
                "topic",
                "pub",
                "--once",
                "/qwen/request",
                "std_msgs/msg/String",
                body,
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        publisher.publish(image)
        deadline = time.monotonic() + 120
        while len(received) < 2:
            if time.monotonic() > deadline:
                raise TimeoutError("No result from native host request")
            rclpy.spin_once(node, timeout_sec=0.1)
        stdout, stderr = command.communicate(timeout=20)
        assert command.returncode == 0, stderr
        q, y = received["qwen"], received["yolo"]
        assert (
            q["status"] == "ok" and q["text"].strip() and 0 < q["output_tokens"] <= 32
        )
        assert (
            y["status"] == "ok"
            and y["detections"]
            and y["width"] > 0
            and y["height"] > 0
        )
        for box in y["detections"]:
            assert 0 <= box["confidence"] <= 1
        output = {
            "state": "PASS",
            "execution": "Spark host python/ros2, NOT docker exec",
            "domain": 42,
            "qwen_via": "native ros2 topic pub",
            "yolo_via": "native rclpy publisher",
            "results": received,
            "cli_stdout": stdout,
        }
        path = Path.home() / "cj-ros-host/evidence/native-host-test.json"
        path.write_text(json.dumps(output, ensure_ascii=False, indent=2) + "\n")
        print(json.dumps({"state": "PASS", "output": str(path)}))
    finally:
        if command is not None and command.poll() is None:
            command.terminate()
            command.wait(timeout=5)
        node.destroy_node()
        rclpy.try_shutdown()


if __name__ == "__main__":
    main()
