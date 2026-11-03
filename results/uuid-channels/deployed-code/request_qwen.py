#!/usr/bin/env python3
"""One native ROS 2 text request and its UUID-specific response."""

import argparse
import json
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


def request_qwen(text, max_new_tokens=128, timeout=300):
    import rclpy
    from rclpy.qos import DurabilityPolicy, QoSProfile
    from std_msgs.msg import String

    if (
        not text.strip()
        or len(text) > 32768
        or not 1 <= max_new_tokens <= 512
        or timeout <= 0
    ):
        raise ValueError(
            "Nonblank text <=32768 chars, max-new-tokens1..512 and positive timeout required"
        )
    request_id = "r_" + uuid.uuid4().hex
    response = None
    rclpy.init(args=[])
    node = rclpy.create_node("request_qwen_" + request_id)

    def on_result(message):
        nonlocal response
        reply = parse_result(message.data, request_id)
        if reply is not None:
            response = reply

    # Subscribe BEFORE sending; the server later discovers this exact reader.
    subscription = node.create_subscription(
        String, "/qwen/result/" + request_id, on_result, 1
    )
    publisher = node.create_publisher(
        String,
        "/qwen/request",
        QoSProfile(depth=1, durability=DurabilityPolicy.TRANSIENT_LOCAL),
    )
    deadline = time.monotonic() + timeout
    try:
        while publisher.get_subscription_count() == 0:
            if time.monotonic() >= deadline:
                raise TimeoutError("No Qwen request subscriber discovered")
            rclpy.spin_once(node, timeout_sec=0.05)
        publisher.publish(
            String(
                data=json.dumps(
                    {
                        "request_id": request_id,
                        "text": text,
                        "max_new_tokens": max_new_tokens,
                    },
                    ensure_ascii=False,
                )
            )
        )
        while response is None:
            if time.monotonic() >= deadline:
                raise TimeoutError("Qwen response timed out: " + request_id)
            rclpy.spin_once(node, timeout_sec=0.05)
        if response.get("status") != "ok":
            raise RuntimeError(
                response.get("error", response.get("error_type", "Qwen request failed"))
            )
        return response
    finally:
        node.destroy_subscription(subscription)
        node.destroy_node()
        rclpy.try_shutdown()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--text", required=True)
    parser.add_argument("--max-new-tokens", type=int, default=128)
    parser.add_argument("--timeout", type=float, default=300)
    parser.add_argument(
        "--result-json", type=Path, help="Optional raw response record (new file only)"
    )
    args = parser.parse_args()
    reply = request_qwen(args.text, args.max_new_tokens, args.timeout)
    if args.result_json:
        with args.result_json.open("x") as stream:
            json.dump(reply, stream, ensure_ascii=False, indent=2)
    print(reply["text"])
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (ValueError, RuntimeError, TimeoutError, OSError) as error:
        raise SystemExit(str(error)) from None
