"""Concurrent native Spark CLI processes; verify request-specific channels and saved images."""

import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys
import time
from PIL import Image, ImageChops
import rclpy
from std_msgs.msg import String
from rclpy.qos import DurabilityPolicy, QoSProfile


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=False)
    root = Path.home() / "cj-ros2"
    assets = Path.home() / "cj-containers/assets"
    result = {
        "state": "running",
        "scope": "functional routing; not SLO or security proof",
        "requests": {},
        "clients": {},
    }
    processes = {}
    seen = {}
    rclpy.init()
    node = rclpy.create_node("uuid_client_test_observer")
    try:
        deadline = time.monotonic() + 600
        while (
            node.count_subscribers("/qwen/request") < 1
            or node.count_subscribers("/yolo/request") < 1
        ):
            if time.monotonic() > deadline:
                raise TimeoutError("Models not ready")
            rclpy.spin_once(node, timeout_sec=0.1)

        def observe(kind, msg):
            data = json.loads(msg.data)
            rid = data["request_id"]
            seen[rid] = {
                "kind": kind,
                "text": data.get("text"),
                "encoded_bytes": len(data.get("image_base64", "")),
            }

        node.create_subscription(
            String,
            "/qwen/request",
            lambda msg: observe("qwen", msg),
            QoSProfile(depth=32, durability=DurabilityPolicy.TRANSIENT_LOCAL),
        )
        node.create_subscription(
            String,
            "/yolo/request",
            lambda msg: observe("yolo", msg),
            QoSProfile(depth=32, durability=DurabilityPolicy.TRANSIENT_LOCAL),
        )

        def launch(name, kind, options):
            out = (args.output / (name + ".stdout")).open("w")
            err = (args.output / (name + ".stderr")).open("w")
            command = [
                sys.executable,
                str(root / "clients" / ("request_" + kind + ".py")),
                *options,
                "--result-json",
                str(args.output / (name + ".json")),
                "--timeout",
                "180",
            ]
            process = subprocess.Popen(command, stdout=out, stderr=err)
            processes[name] = (process, out, err)

        launch(
            "q1",
            "qwen",
            [
                "--text",
                "Explain GPU resource contention in detail with six bullet points.",
                "--max-new-tokens",
                "128",
            ],
        )
        deadline = time.monotonic() + 30
        while not any(x["kind"] == "qwen" for x in seen.values()):
            if time.monotonic() > deadline:
                raise TimeoutError("Qwen client did not publish")
            rclpy.spin_once(node, timeout_sec=0.05)
        launch(
            "q2",
            "qwen",
            [
                "--text",
                "Describe what FIFO means in one sentence.",
                "--max-new-tokens",
                "32",
            ],
        )
        before = {
            p.name: hashlib.sha256(p.read_bytes()).hexdigest()
            for p in [assets / "bus.jpg", assets / "zidane.jpg"]
        }
        launch(
            "y1",
            "yolo",
            [
                "--image",
                str(assets / "bus.jpg"),
                "--output",
                str(args.output / "bus.png"),
            ],
        )
        launch(
            "y2",
            "yolo",
            [
                "--image",
                str(assets / "zidane.jpg"),
                "--output",
                str(args.output / "zidane.png"),
            ],
        )
        deadline = time.monotonic() + 200
        while any(p.poll() is None for p, _, _ in processes.values()):
            if time.monotonic() > deadline:
                raise TimeoutError("Concurrent clients did not complete")
            rclpy.spin_once(node, timeout_sec=0.05)
        for name, (process, out, err) in processes.items():
            out.close()
            err.close()
            assert process.returncode == 0, (
                name,
                (args.output / (name + ".stderr")).read_text(),
            )
            response = json.loads((args.output / (name + ".json")).read_text())
            rid = response["request_id"]
            assert re.fullmatch(r"r_[0-9a-f]{32}", rid)
            assert rid in seen and response["status"] == "ok"
            result["clients"][name] = response
            if name.startswith("q"):
                expected = (
                    "Explain GPU resource contention in detail with six bullet points."
                    if name == "q1"
                    else "Describe what FIFO means in one sentence."
                )
                assert seen[rid]["kind"] == "qwen" and seen[rid]["text"] == expected
                assert (
                    args.output / (name + ".stdout")
                ).read_text().strip() == response["text"].strip()
            else:
                image_name, output_name = (
                    ("bus.jpg", "bus.png")
                    if name == "y1"
                    else ("zidane.jpg", "zidane.png")
                )
                assert seen[rid]["kind"] == "yolo" and response["detections"]
                with (
                    Image.open(assets / image_name) as original,
                    Image.open(args.output / output_name) as annotated,
                ):
                    assert annotated.size == original.size
                    assert (
                        ImageChops.difference(
                            original.convert("RGB"), annotated.convert("RGB")
                        ).getbbox()
                        is not None
                    )
                assert (
                    hashlib.sha256((assets / image_name).read_bytes()).hexdigest()
                    == before[image_name]
                )
        ids = [x["request_id"] for x in result["clients"].values()]
        assert len(set(ids)) == 4
        deadline = time.monotonic() + 15
        while any(
            node.count_publishers("/" + seen[rid]["kind"] + "/result/" + rid) > 0
            for rid in ids
        ):
            if time.monotonic() > deadline:
                raise AssertionError("Result publishers were not destroyed")
            rclpy.spin_once(node, timeout_sec=0.1)
        result.update(
            state="PASS",
            requests=seen,
            unique_ids=4,
            wrong_response_mixups=0,
            annotated_images=2,
            ephemeral_publishers_cleaned=True,
        )
    except Exception as error:
        result.update(state="FAIL", error=repr(error))
        raise
    finally:
        for process, out, err in processes.values():
            if process.poll() is None:
                process.terminate()
                process.wait(timeout=10)
            out.close()
            err.close()
        result["requests"] = seen
        (args.output / "summary.json").write_text(
            json.dumps(result, ensure_ascii=False, indent=2) + "\n"
        )
        node.destroy_node()
        rclpy.try_shutdown()
    print(json.dumps({"state": result["state"], "output": str(args.output)}))


if __name__ == "__main__":
    main()
