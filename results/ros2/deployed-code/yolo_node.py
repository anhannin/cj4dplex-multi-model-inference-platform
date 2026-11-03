#!/usr/bin/env python3
"""Standalone ROS 2 image node: callback -> FIFO -> stock predict() -> result topic.

Official model usage: https://docs.ultralytics.com/modes/predict/
No inference Backend wrapper, shared node, HTTP service, or workload mode.
"""

import io
import itertools
import json
import queue
import threading
import time

import rclpy
from rclpy.executors import ExternalShutdownException
from rclpy.node import Node
from sensor_msgs.msg import CompressedImage
from std_msgs.msg import String


class YoloNode(Node):
    def __init__(self):
        super().__init__("yolo_node")
        self.model_path = self.declare_parameter(
            "model_path", "/assets/yolo26l.pt"
        ).value
        capacity = self.declare_parameter("queue_capacity", 8).value
        if capacity < 1:
            raise ValueError("queue_capacity must be positive")
        self.requests = queue.Queue(maxsize=capacity)
        self.sequence = itertools.count(1)
        self.stopping = threading.Event()
        self.loaded = threading.Event()
        self.load_error = None
        self.results = self.create_publisher(String, "/yolo/result", 32)
        self.worker = threading.Thread(target=self._worker, name="yolo-inference")
        self.worker.start()
        self.loaded.wait()
        if self.load_error is not None:
            raise RuntimeError("Model startup failed") from self.load_error
        self.subscription = self.create_subscription(
            CompressedImage, "/yolo/request", self._on_request, 32
        )
        self.get_logger().info(json.dumps({"event": "node_ready", "time": time.time()}))

    def _on_request(self, message):
        item = (next(self.sequence), time.perf_counter(), message)
        try:
            self.requests.put_nowait(item)
        except queue.Full:
            self.get_logger().warning(
                json.dumps({"event": "queue_full", "sequence": item[0]})
            )

    def _worker(self):
        try:
            import torch
            from PIL import Image
            from ultralytics import YOLO

            torch.set_num_threads(4)
            torch.cuda.set_device(0)
            model = YOLO(self.model_path)
            options = dict(
                device=0,
                imgsz=640,
                quantize=16,
                batch=1,
                rect=False,
                verbose=False,
                save=False,
            )
            # Warm up with the original predict() interface; do not modify model code.
            model.predict(Image.new("RGB", (640, 640)), **options)
            backend = model.predictor.model
            parameter = next(backend.model.parameters())
            if (
                backend.device.type != "cuda"
                or not backend.fp16
                or parameter.dtype != torch.float16
            ):
                raise RuntimeError("Executing backend is not native CUDA FP16")
            self.get_logger().info(
                json.dumps(
                    {
                        "event": "model_loaded",
                        "time": time.time(),
                        "device": str(parameter.device),
                        "dtype": str(parameter.dtype),
                    }
                )
            )
        except Exception as error:
            self.load_error = error
            self.loaded.set()
            return
        self.loaded.set()
        while not self.stopping.is_set():
            try:
                sequence, enqueued, message = self.requests.get(timeout=0.1)
            except queue.Empty:
                continue
            started = time.perf_counter()
            reply = {
                "sequence": sequence,
                "source_stamp": {
                    "sec": message.header.stamp.sec,
                    "nanosec": message.header.stamp.nanosec,
                },
                "frame_id": message.header.frame_id,
                "queue_wait_ms": (started - enqueued) * 1000,
            }
            self.get_logger().info(
                json.dumps(
                    {
                        "event": "processing_started",
                        "sequence": sequence,
                        "time": time.time(),
                    }
                )
            )
            try:
                if not message.data or len(message.data) > 10 * 1024 * 1024:
                    raise ValueError("Image must be nonempty and at most 10 MiB")
                with Image.open(io.BytesIO(bytes(message.data))) as source:
                    if source.format not in ("JPEG", "PNG"):
                        raise ValueError("Only JPEG and PNG are supported")
                    if source.width * source.height > 16_000_000:
                        raise ValueError("Image exceeds 16 million pixels")
                    image = source.convert("RGB")
                # Stock Ultralytics example: predict image, read original-coordinate boxes.
                with torch.inference_mode():
                    result = model.predict(image, **options)[0]
                    rows = result.boxes.data.cpu().tolist()
                    reply.update(
                        status="ok",
                        width=image.width,
                        height=image.height,
                        detections=[
                            {
                                "class_id": int(row[5]),
                                "label": result.names[int(row[5])],
                                "confidence": float(row[4]),
                                "xyxy": row[:4],
                            }
                            for row in rows
                        ],
                    )
                    torch.cuda.synchronize()
            except Exception as error:
                reply.update(status="error", error_type=type(error).__name__)
                if isinstance(error, ValueError):
                    reply["error"] = str(error)
            reply["processing_ms"] = (time.perf_counter() - started) * 1000
            try:
                if rclpy.ok(context=self.context):
                    self.results.publish(
                        String(data=json.dumps(reply, ensure_ascii=False))
                    )
            finally:
                self.requests.task_done()
            self.get_logger().info(
                json.dumps(
                    {
                        "event": "processing_finished",
                        "sequence": sequence,
                        "time": time.time(),
                        "status": reply["status"],
                        "queue_wait_ms": reply["queue_wait_ms"],
                        "processing_ms": reply["processing_ms"],
                    }
                )
            )
            del message

    def close(self):
        self.stopping.set()
        self.worker.join()


def main():
    rclpy.init()
    node = None
    try:
        node = YoloNode()
        rclpy.spin(node)
    except (KeyboardInterrupt, ExternalShutdownException):
        pass
    finally:
        if node is not None:
            node.close()
            node.destroy_node()
        rclpy.try_shutdown()


if __name__ == "__main__":
    main()
