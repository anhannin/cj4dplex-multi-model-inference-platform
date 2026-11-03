#!/usr/bin/env python3
"""Standalone ROS 2 Qwen node: callback -> FIFO -> stock generate() -> result topic.

Official model usage: https://huggingface.co/Qwen/Qwen3.5-9B
No inference Backend wrapper, shared node, HTTP service, or workload mode.
"""

import inspect
import itertools
import json
import queue
import threading
import time

import rclpy
from rclpy.executors import ExternalShutdownException
from rclpy.node import Node
from std_msgs.msg import String


class QwenNode(Node):
    def __init__(self):
        super().__init__("qwen_node")
        path = "/cache/models--Qwen--Qwen3.5-9B/snapshots/c202236235762e1c871ad0ccb60c8ee5ba337b9a"
        self.model_path = self.declare_parameter("model_path", path).value
        self.max_new_tokens = self.declare_parameter("max_new_tokens", 128).value
        capacity = self.declare_parameter("queue_capacity", 8).value
        if capacity < 1 or not 1 <= self.max_new_tokens <= 512:
            raise ValueError(
                "queue_capacity must be positive; max_new_tokens must be 1..512"
            )
        self.requests = queue.Queue(maxsize=capacity)
        self.sequence = itertools.count(1)
        self.stopping = threading.Event()
        self.loaded = threading.Event()
        self.load_error = None
        self.results = self.create_publisher(String, "/qwen/result", 32)
        self.worker = threading.Thread(target=self._worker, name="qwen-inference")
        self.worker.start()
        self.loaded.wait()
        if self.load_error is not None:
            raise RuntimeError("Model startup failed") from self.load_error
        self.subscription = self.create_subscription(
            String, "/qwen/request", self._on_request, 32
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
            from transformers import AutoTokenizer, Qwen3_5ForConditionalGeneration
            from transformers.models.qwen3_5 import modeling_qwen3_5

            torch.set_num_threads(4)
            torch.cuda.set_device(0)
            tokenizer = AutoTokenizer.from_pretrained(
                self.model_path, local_files_only=True
            )
            model = (
                Qwen3_5ForConditionalGeneration.from_pretrained(
                    self.model_path,
                    dtype=torch.bfloat16,
                    local_files_only=True,
                    attn_implementation="sdpa",
                )
                .eval()
                .to("cuda")
            )
            # Read-only check of the pinned stock Transformers dispatchers.
            bindings = {}
            for attribute, prefix in [
                ("causal_conv1d_fn", "causal_conv1d."),
                ("causal_conv1d_update", "causal_conv1d."),
                ("torch_chunk_gated_delta_rule", "fla."),
                ("torch_recurrent_gated_delta_rule", "fla."),
            ]:
                function = getattr(modeling_qwen3_5, attribute)
                selected = inspect.getclosurevars(function).nonlocals.get(
                    "implementation"
                )
                module = getattr(selected, "__module__", "")
                if not module.startswith(prefix):
                    raise RuntimeError("Missing GPU acceleration: " + attribute)
                bindings[attribute] = module
            self.get_logger().info(
                json.dumps(
                    {
                        "event": "model_loaded",
                        "time": time.time(),
                        "dtype": "bfloat16",
                        "bindings": bindings,
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
                "request_id": str(sequence),
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
                # String.data may be a plain prompt or an optional JSON request envelope.
                text, maximum = message.data, self.max_new_tokens
                try:
                    envelope = json.loads(text)
                except (json.JSONDecodeError, ValueError):
                    envelope = None
                if isinstance(envelope, dict) and "text" in envelope:
                    text = envelope["text"]
                    maximum = envelope.get("max_new_tokens", maximum)
                    request_id = envelope.get("request_id", str(sequence))
                    if not isinstance(request_id, str) or len(request_id) > 128:
                        raise ValueError(
                            "request_id must be a string of at most 128 characters"
                        )
                    reply["request_id"] = request_id
                if not isinstance(text, str) or not text.strip() or len(text) > 32768:
                    raise ValueError(
                        "text must be nonblank and at most 32768 characters"
                    )
                if type(maximum) is not int or not 1 <= maximum <= 512:
                    raise ValueError("max_new_tokens must be an integer in 1..512")
                # Stock Hugging Face example: template -> tokenize -> generate -> decode.
                prompt = tokenizer.apply_chat_template(
                    [{"role": "user", "content": text}],
                    tokenize=False,
                    add_generation_prompt=True,
                    enable_thinking=False,
                )
                inputs = tokenizer(prompt, return_tensors="pt")
                input_tokens = inputs["input_ids"].shape[-1]
                if input_tokens > 2048:
                    raise ValueError(
                        "Input including chat template exceeds 2048 tokens"
                    )
                with torch.inference_mode():
                    inputs = {key: value.to("cuda") for key, value in inputs.items()}
                    output = model.generate(
                        **inputs,
                        max_new_tokens=maximum,
                        do_sample=False,
                        use_cache=True,
                        pad_token_id=tokenizer.eos_token_id,
                    )
                    generated = output[0, input_tokens:]
                    reply.update(
                        status="ok",
                        text=tokenizer.decode(generated, skip_special_tokens=True),
                        output_tokens=int(generated.shape[-1]),
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
        self.worker.join()  # Finish the running GPU call before destroying the publisher.


def main():
    rclpy.init()
    node = None
    try:
        node = QwenNode()
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
