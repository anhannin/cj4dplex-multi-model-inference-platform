#!/usr/bin/env python3
"""One native ROS 2 image request; save annotated original-size result and exit."""

import argparse
import base64
import json
import math
from pathlib import Path
import time
import uuid


def parse_result(data, request_id):
    try:
        reply = json.loads(data)
    except (ValueError, TypeError):
        return None
    return (
        reply
        if isinstance(reply, dict) and reply.get("request_id") == request_id
        else None
    )


def request_yolo(image_path, timeout=300):
    import rclpy
    from rclpy.qos import DurabilityPolicy, QoSProfile
    from std_msgs.msg import String
    from PIL import Image

    with Path(image_path).open("rb") as source:
        data = source.read(10 * 1024 * 1024 + 1)
    if not data or len(data) > 10 * 1024 * 1024 or timeout <= 0:
        raise ValueError("Image must be1..10MiB and timeout positive")
    with Image.open(Path(image_path)) as image:
        if (
            image.format not in ("JPEG", "PNG")
            or image.width * image.height > 16_000_000
        ):
            raise ValueError("JPEG/PNG <=16M pixels required")
    request_id = "r_" + uuid.uuid4().hex
    response = None
    rclpy.init(args=[])
    node = rclpy.create_node("request_yolo_" + request_id)

    def on_result(message):
        nonlocal response
        reply = parse_result(message.data, request_id)
        if reply is not None:
            response = reply

    subscription = node.create_subscription(
        String, "/yolo/result/" + request_id, on_result, 1
    )
    publisher = node.create_publisher(
        String,
        "/yolo/request",
        QoSProfile(depth=1, durability=DurabilityPolicy.TRANSIENT_LOCAL),
    )
    deadline = time.monotonic() + timeout
    try:
        while publisher.get_subscription_count() == 0:
            if time.monotonic() >= deadline:
                raise TimeoutError("No YOLO request subscriber discovered")
            rclpy.spin_once(node, timeout_sec=0.05)
        publisher.publish(
            String(
                data=json.dumps(
                    {
                        "request_id": request_id,
                        "image_base64": base64.b64encode(data).decode("ascii"),
                    }
                )
            )
        )
        while response is None:
            if time.monotonic() >= deadline:
                raise TimeoutError("YOLO response timed out: " + request_id)
            rclpy.spin_once(node, timeout_sec=0.05)
        if response.get("status") != "ok":
            raise RuntimeError(
                response.get("error", response.get("error_type", "YOLO request failed"))
            )
        return response
    finally:
        node.destroy_subscription(subscription)
        node.destroy_node()
        rclpy.try_shutdown()


def save_result_image(source, output, reply):
    from PIL import Image, ImageDraw

    source, output = Path(source), Path(output)
    if output.exists():
        raise FileExistsError("Refusing to overwrite: " + str(output))
    with Image.open(source) as original:
        image = original.convert("RGB")
    if image.size != (reply["width"], reply["height"]):
        raise ValueError("Response dimensions do not match input image")
    draw = ImageDraw.Draw(image)
    for detection in reply["detections"]:
        box = detection["xyxy"]
        if len(box) != 4 or not all(math.isfinite(v) for v in box):
            raise ValueError("Invalid detection coordinates")
        draw.rectangle(box, outline="red", width=3)
        label = f"{detection['label']} {detection['confidence']:.2f}"
        draw.text((box[0], max(0, box[1] - 12)), label, fill="red")
    output.parent.mkdir(parents=True, exist_ok=True)
    # Exclusive creation also prevents simultaneous clients overwriting each other.
    with output.open("xb") as stream:
        image.save(
            stream,
            format="JPEG" if output.suffix.lower() in (".jpg", ".jpeg") else "PNG",
        )
    return output


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--image", type=Path, required=True)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--timeout", type=float, default=300)
    parser.add_argument(
        "--result-json", type=Path, help="Optional raw response record (new file only)"
    )
    args = parser.parse_args()
    if args.output is not None and args.output.exists():
        raise FileExistsError("Refusing to overwrite: " + str(args.output))
    reply = request_yolo(args.image, args.timeout)
    target = args.output or args.image.with_name(
        args.image.stem + "_detected_" + reply["request_id"] + ".png"
    )
    saved = save_result_image(args.image, target, reply)
    if args.result_json:
        with args.result_json.open("x") as stream:
            json.dump(reply, stream, ensure_ascii=False, indent=2)
    print(saved)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (ValueError, RuntimeError, TimeoutError, OSError) as error:
        raise SystemExit(str(error)) from None
