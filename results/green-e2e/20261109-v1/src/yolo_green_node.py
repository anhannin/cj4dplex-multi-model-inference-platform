#!/usr/bin/env python3
"""Standalone ROS 2 image node: callback -> FIFO -> stock predict() -> result topic.

Official model usage: https://docs.ultralytics.com/modes/predict/
No inference Backend wrapper, shared node, HTTP service, or workload mode.
"""

import base64
import io
import itertools
import gc
import hashlib
import json
import os
from pathlib import Path
import queue
import re
import threading
import time

import rclpy
from rclpy.duration import Duration
from rclpy.executors import ExternalShutdownException
from rclpy.node import Node
from rclpy.qos import DurabilityPolicy, QoSProfile
from std_msgs.msg import String


READY_FILE = Path(os.environ.get("READY_FILE", "/tmp/cj-model-ready"))


class YoloNode(Node):
    def __init__(self):
        super().__init__("yolo_node")
        READY_FILE.unlink(missing_ok=True)
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
        self.result_timeout = self.declare_parameter("result_timeout", 5.0).value
        if self.result_timeout <= 0:
            raise ValueError("result_timeout must be positive")
        self.worker = threading.Thread(target=self._worker, name="yolo-inference")
        self.worker.start()
        self.loaded.wait()
        if self.load_error is not None:
            raise RuntimeError("Model startup failed") from self.load_error
        self.subscription = self.create_subscription(
            String,
            "/yolo/request",
            self._on_request,
            QoSProfile(depth=32, durability=DurabilityPolicy.TRANSIENT_LOCAL),
        )
        READY_FILE.write_text(str(os.getpid()))
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
        pair = None
        stream = None
        torch = None
        try:
            import torch
            torch.set_num_threads(4)
            torch.cuda.set_device(0)
            enabled = os.environ.get("GREEN_ENABLED", "0") == "1"
            index = int(os.environ.get("GREEN_PARTITION_INDEX", "0"))
            expected = int(os.environ.get("GREEN_EXPECTED_SM", "48"))
            self._green_mode = enabled
            if enabled:
                import green_bridge
                pair = green_bridge.GreenPair(int(os.environ["GREEN_LEFT_SMS"]))
                metadata = dict(pair.metadata())
                selected = metadata["parts"][index]
                actual = int(selected["actual_sms"])
                ids = pair.sample_smids(index)
                if actual != expected or not 0 < len(ids) <= actual:
                    raise RuntimeError("Wrong Green allocation or sampled SM set")
                stream = torch.cuda.ExternalStream(pair.stream_ptr(index), device=0)
                stream.wait_stream(torch.cuda.current_stream())
                metadata.update(selected_index=index, selected_sms=actual, observed_smids=ids)
            else:
                stream = torch.cuda.current_stream()
                actual = int(torch.cuda.get_device_properties(0).multi_processor_count)
                if actual != 48:
                    raise RuntimeError("Unexpected full-GPU control size")
                metadata = {"selected_sms": actual, "observed_smids": None}
            self._green_sms = actual
            self._expected_stream = stream.cuda_stream
            metadata.update(event="gpu_resource_ready", enabled=enabled,
                            pair=os.environ.get("PAIR_LABEL"), pid=os.getpid(), time_ns=time.time_ns())
            folder = Path("/experiment/metadata")
            folder.mkdir(exist_ok=True)
            name = os.environ["PAIR_LABEL"] + "-yolo-" + str(os.getpid()) + "-" + str(time.time_ns()) + ".json"
            (folder / name).write_text(json.dumps(metadata, indent=2))
            self.get_logger().info(json.dumps(metadata))
            with torch.cuda.stream(stream):
                self._frozen_worker()
        except BaseException as error:
            self.load_error = error
            self.loaded.set()
            self.get_logger().error("GPU worker failure: " + repr(error))
        finally:
            if torch is not None:
                torch.cuda.synchronize()
                gc.collect()
                torch.cuda.empty_cache()
            if pair is not None:
                del stream
                pair.close()

    def _frozen_worker(self):
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
            timing = {}
            reply = {
                "timing_schema": 1,
                "timings_ms": timing,
                "sequence": sequence,
                "request_id": None,
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
            reply["green_enabled"] = self._green_mode
            reply["assigned_sms"] = self._green_sms
            try:
                envelope = json.loads(message.data)
                if not isinstance(envelope, dict):
                    raise ValueError("Request must be a JSON object")
                request_id = envelope.get("request_id")
                if (
                    not isinstance(request_id, str)
                    or re.fullmatch(r"r_[0-9a-f]{32}", request_id) is None
                ):
                    raise ValueError(
                        "request_id must be r_ followed by 32 lowercase hex digits"
                    )
                reply["request_id"] = request_id
                reply["run_id"] = str(envelope.get("run_id", ""))[:128]
                encoded = envelope.get("image_base64")
                if (
                    not isinstance(encoded, str)
                    or not encoded
                    or len(encoded) > 4 * ((10 * 1024 * 1024 + 2) // 3)
                ):
                    raise ValueError("Missing image_base64 or encoded image too large")
                timing["envelope_parse_ms"] = (time.perf_counter() - started) * 1000
                decode_start = time.perf_counter_ns()
                data = base64.b64decode(encoded, validate=True)
                if not data or len(data) > 10 * 1024 * 1024:
                    raise ValueError("Image must be nonempty and at most 10 MiB")
                with Image.open(io.BytesIO(data)) as source:
                    if source.format not in ("JPEG", "PNG"):
                        raise ValueError("Only JPEG and PNG are supported")
                    if source.width * source.height > 16_000_000:
                        raise ValueError("Image exceeds 16 million pixels")
                    image = source.convert("RGB")
                timing["image_decode_ms"] = (
                    time.perf_counter_ns() - decode_start
                ) / 1e6
                # Stock Ultralytics example: predict image, read original-coordinate boxes.
                with torch.inference_mode():
                    if torch.cuda.current_stream().cuda_stream != self._expected_stream:
                        raise RuntimeError("Request GPU work escaped selected stream")
                    predict_start = time.perf_counter_ns()
                    result = model.predict(image, **options)[0]
                    timing["predict_wall_ms"] = (
                        time.perf_counter_ns() - predict_start
                    ) / 1e6
                    timing["yolo_preprocess_ms"] = result.speed["preprocess"]
                    timing["yolo_inference_ms"] = result.speed["inference"]
                    timing["yolo_postprocess_ms"] = result.speed["postprocess"]
                    timing["predict_overhead_ms"] = timing["predict_wall_ms"] - sum(
                        result.speed.values()
                    )
                    extract_start = time.perf_counter_ns()
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
                    timing["result_extract_ms"] = (
                        time.perf_counter_ns() - extract_start
                    ) / 1e6
            except Exception as error:
                reply.update(status="error", error_type=type(error).__name__)
                if isinstance(error, ValueError):
                    reply["error"] = str(error)
            reply["processing_ms"] = (time.perf_counter() - started) * 1000
            timing["callback_to_result_ready_ms"] = (
                time.perf_counter() - enqueued
            ) * 1000
            try:
                if rclpy.ok(context=self.context):
                    self._publish_result(reply.get("request_id"), reply)
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
                        "request_id": reply.get("request_id"),
                        "run_id": reply.get("run_id"),
                        "worker_busy_ms": (time.perf_counter() - started) * 1000,
                        "timings_ms": timing,
                    }
                )
            )
            del message

    def _publish_result(self, request_id, reply):
        if (
            not isinstance(request_id, str)
            or re.fullmatch(r"r_[0-9a-f]{32}", request_id) is None
        ):
            self.get_logger().warning(json.dumps({"event": "invalid_request_id"}))
            return False
        publication_start = time.perf_counter_ns()
        publication = {
            "publisher_create_ms": None,
            "result_discovery_ms": None,
            "response_serialize_ms": None,
            "publish_call_ms": None,
            "ack_wait_ms": None,
            "acknowledged": False,
        }
        publisher = self.create_publisher(String, "/yolo/result/" + request_id, 1)
        publication["publisher_create_ms"] = (
            time.perf_counter_ns() - publication_start
        ) / 1e6
        discovery_start = time.perf_counter_ns()
        try:
            deadline = time.monotonic() + self.result_timeout
            while publisher.get_subscription_count() == 0:
                if (
                    self.stopping.is_set()
                    or not rclpy.ok(context=self.context)
                    or time.monotonic() >= deadline
                ):
                    self.get_logger().warning(
                        json.dumps(
                            {
                                "event": "result_subscriber_timeout",
                                "request_id": request_id,
                            }
                        )
                    )
                    return False
                time.sleep(0.01)
            publication["result_discovery_ms"] = (
                time.perf_counter_ns() - discovery_start
            ) / 1e6
            serialize_start = time.perf_counter_ns()
            message = String(data=json.dumps(reply, ensure_ascii=False))
            publication["response_serialize_ms"] = (
                time.perf_counter_ns() - serialize_start
            ) / 1e6
            publish_start = time.perf_counter_ns()
            publisher.publish(message)
            publication["publish_call_ms"] = (
                time.perf_counter_ns() - publish_start
            ) / 1e6
            ack_start = time.perf_counter_ns()
            acknowledged = publisher.wait_for_all_acked(Duration(seconds=2))
            publication["ack_wait_ms"] = (time.perf_counter_ns() - ack_start) / 1e6
            publication["acknowledged"] = bool(acknowledged)
            if not acknowledged:
                self.get_logger().warning(
                    json.dumps(
                        {"event": "result_ack_timeout", "request_id": request_id}
                    )
                )
            return acknowledged
        finally:
            self.destroy_publisher(publisher)
            self.get_logger().info(
                json.dumps(
                    {
                        "event": "publication_finished",
                        "request_id": request_id,
                        "run_id": reply.get("run_id"),
                        "time": time.time(),
                        **publication,
                        "publication_total_ms": (
                            time.perf_counter_ns() - publication_start
                        )
                        / 1e6,
                    }
                )
            )

    def close(self):
        READY_FILE.unlink(missing_ok=True)
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
