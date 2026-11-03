# Historical v1 protocol only; for v2 run test_uuid_clients.py instead.
"""Actual ROS 2/DDS functional test. Run inside the ROS image, not local CPU tests."""

from array import array
import json
from pathlib import Path
import subprocess
import time

from PIL import Image
import rclpy
from rclpy.node import Node
from sensor_msgs.msg import CompressedImage
from std_msgs.msg import String


def main():
    output = Path("/runtime/ros-live-results.json")
    summary = {
        "state": "running",
        "scope": "functional ROS topics, not a performance benchmark",
        "qwen": [],
        "yolo": [],
        "receive_order": [],
    }
    rclpy.init()
    node = Node("minimal_ros_smoke_client")
    qpub = node.create_publisher(String, "/qwen/request", 32)
    ypub = node.create_publisher(CompressedImage, "/yolo/request", 32)

    def receive_qwen(msg):
        data = json.loads(msg.data)
        summary["qwen"].append(data)
        summary["receive_order"].append(
            {"kind": "qwen", "sequence": data["sequence"], "time": time.time()}
        )

    def receive_yolo(msg):
        data = json.loads(msg.data)
        summary["yolo"].append(data)
        summary["receive_order"].append(
            {"kind": "yolo", "sequence": data["sequence"], "time": time.time()}
        )

    qsub = node.create_subscription(String, "/qwen/result", receive_qwen, 32)
    ysub = node.create_subscription(String, "/yolo/result", receive_yolo, 32)

    def spin_until(predicate, timeout=240):
        deadline = time.monotonic() + timeout
        while not predicate():
            if time.monotonic() > deadline:
                raise TimeoutError("ROS response/discovery timed out")
            rclpy.spin_once(node, timeout_sec=0.05)

    try:
        spin_until(
            lambda: qpub.get_subscription_count() >= 1
            and ypub.get_subscription_count() >= 1
            and qsub.get_publisher_count() >= 1
            and ysub.get_publisher_count() >= 1,
            timeout=600,
        )
        requests = [
            {
                "request_id": "ros-q1",
                "text": "Explain GPU resource contention in detail using at least six bullet points.",
                "max_new_tokens": 128,
            },
            {
                "request_id": "ros-q2",
                "text": "List two benefits of keeping models resident in GPU memory.",
                "max_new_tokens": 32,
            },
            {
                "request_id": "ros-q3",
                "text": "Explain what a FIFO queue does in one sentence.",
                "max_new_tokens": 16,
            },
        ]
        qpub.publish(String(data=json.dumps(requests[0])))
        # Let the first generation begin; host-side logs verify actual interval overlap.
        until = time.monotonic() + 0.5
        while time.monotonic() < until:
            rclpy.spin_once(node, timeout_sec=0.05)
        for request in requests[1:]:
            qpub.publish(String(data=json.dumps(request)))
        image_specs = []
        for index, name in enumerate(["bus.jpg", "zidane.jpg", "invalid"]):
            message = CompressedImage()
            now = time.time_ns() + index
            message.header.stamp.sec, message.header.stamp.nanosec = divmod(
                now, 1_000_000_000
            )
            message.header.frame_id = "test_camera"
            message.format = "jpeg"
            raw = (
                (Path("/assets") / name).read_bytes()
                if name != "invalid"
                else b"not-an-image"
            )
            message.data = array("B", raw)
            image_specs.append(
                {
                    "name": name,
                    "stamp": {
                        "sec": message.header.stamp.sec,
                        "nanosec": message.header.stamp.nanosec,
                    },
                }
            )
            ypub.publish(message)
        spin_until(lambda: len(summary["qwen"]) >= 3 and len(summary["yolo"]) >= 3)
        assert [r["request_id"] for r in summary["qwen"][:3]] == [
            "ros-q1",
            "ros-q2",
            "ros-q3",
        ]
        assert [r["sequence"] for r in summary["qwen"][:3]] == sorted(
            r["sequence"] for r in summary["qwen"][:3]
        )
        for expected, reply in zip(requests, summary["qwen"][:3]):
            assert reply["status"] == "ok" and reply["text"].strip()
            assert 0 < reply["output_tokens"] <= expected["max_new_tokens"]
            assert reply["queue_wait_ms"] >= 0 and reply["processing_ms"] > 0
        assert summary["qwen"][1]["queue_wait_ms"] > 100
        assert summary["qwen"][2]["queue_wait_ms"] > summary["qwen"][1]["queue_wait_ms"]
        assert [r["source_stamp"] for r in summary["yolo"][:3]] == [
            spec["stamp"] for spec in image_specs
        ]
        for spec, reply in zip(image_specs[:2], summary["yolo"][:2]):
            with Image.open(Path("/assets") / spec["name"]) as source:
                assert (reply["width"], reply["height"]) == source.size
            assert reply["status"] == "ok" and reply["detections"]
            for detection in reply["detections"]:
                assert 0 <= detection["confidence"] <= 1
                x1, y1, x2, y2 = detection["xyxy"]
                assert (
                    0 <= x1 <= x2 <= reply["width"] and 0 <= y1 <= y2 <= reply["height"]
                )
        assert summary["yolo"][2]["status"] == "error"
        assert next(
            i for i, e in enumerate(summary["receive_order"]) if e["kind"] == "yolo"
        ) < next(
            i for i, e in enumerate(summary["receive_order"]) if e["kind"] == "qwen"
        )
        qpub.publish(
            String(data=json.dumps({"request_id": "invalid-text", "text": ""}))
        )
        spin_until(lambda: len(summary["qwen"]) >= 4)
        assert (
            summary["qwen"][3]["request_id"] == "invalid-text"
            and summary["qwen"][3]["status"] == "error"
        )
        # Verify real ros2 CLI publish + echo, with no custom publisher protocol.
        echo = subprocess.Popen(
            [
                "ros2",
                "topic",
                "echo",
                "--once",
                "--field",
                "data",
                "/qwen/result",
                "std_msgs/msg/String",
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        try:
            # Ensure that the echo subscriber is discovered before publishing.
            spin_until(
                lambda: qpub.get_subscription_count() >= 1
                and node.count_subscribers("/qwen/result") >= 2,
                timeout=30,
            )
            published = subprocess.run(
                [
                    "ros2",
                    "topic",
                    "pub",
                    "--once",
                    "/qwen/request",
                    "std_msgs/msg/String",
                    '{data: "Reply with one short greeting."}',
                ],
                capture_output=True,
                text=True,
                timeout=45,
                check=True,
            )
            stdout, stderr = echo.communicate(timeout=120)
            assert echo.returncode == 0, stderr
            # --field data is rendered as a scalar by ros2 topic echo.
            import yaml

            parsed = list(yaml.safe_load_all(stdout))
            scalar = next(item for item in parsed if item is not None)
            cli_result = scalar if isinstance(scalar, dict) else json.loads(scalar)
            assert cli_result["status"] == "ok" and cli_result["text"].strip()
            summary["ros2_cli"] = {
                "publish_stdout": published.stdout,
                "echo_stdout": stdout,
                "result": cli_result,
            }
        finally:
            if echo.poll() is None:
                echo.terminate()
                echo.wait(timeout=5)
        summary["state"] = "PASS"
    except Exception as error:
        summary["state"] = "FAIL"
        summary["error"] = repr(error)
        raise
    finally:
        output.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n")
        node.destroy_node()
        rclpy.try_shutdown()
    print(json.dumps({"state": summary["state"], "output": str(output)}))


if __name__ == "__main__":
    main()
