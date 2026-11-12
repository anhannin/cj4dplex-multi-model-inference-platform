#!/usr/bin/env python3
"""Standalone ROS 2 Qwen node: callback -> FIFO -> stock generate() -> result topic.

Official model usage: https://huggingface.co/Qwen/Qwen3.5-9B
No inference Backend wrapper, shared node, HTTP service, or workload mode.
"""

import inspect
import itertools
import gc
import hashlib
from gpu_observer import ForwardTimer
from stage_metrics import summarize_forward
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


class QwenNode(Node):
    def __init__(self):
        super().__init__("qwen_node")
        READY_FILE.unlink(missing_ok=True)
        path = "/cache/models--Qwen--Qwen3.5-9B/snapshots/c202236235762e1c871ad0ccb60c8ee5ba337b9a"
        self.model_path = self.declare_parameter("model_path", path).value
        self.max_new_tokens = self.declare_parameter("max_new_tokens", 0).value
        capacity = self.declare_parameter("queue_capacity", 8).value
        if capacity < 1 or self.max_new_tokens < 0:
            raise ValueError(
                "queue_capacity must be positive; max_new_tokens must be 0 (EOS) or positive"
            )
        self.requests = queue.Queue(maxsize=capacity)
        self.sequence = itertools.count(1)
        self.stopping = threading.Event()
        self.loaded = threading.Event()
        self.load_error = None
        self.result_timeout = self.declare_parameter("result_timeout", 5.0).value
        if self.result_timeout <= 0:
            raise ValueError("result_timeout must be positive")
        self.worker = threading.Thread(target=self._worker, name="qwen-inference")
        self.worker.start()
        self.loaded.wait()
        if self.load_error is not None:
            raise RuntimeError("Model startup failed") from self.load_error
        self.subscription = self.create_subscription(
            String,
            "/qwen/request",
            self._on_request,
            QoSProfile(depth=512, durability=DurabilityPolicy.TRANSIENT_LOCAL),
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
        torch = None
        try:
            import torch
            import ctypes
            torch.set_num_threads(4)
            torch.cuda.set_device(0)
            actual = int(torch.cuda.get_device_properties(0).multi_processor_count)
            expected = int(os.environ["EXPECTED_SMS"])
            if actual != expected:
                raise RuntimeError(f"MPS visible SM mismatch: {actual} != {expected}")
            self._green_mode = False
            self._green_sms = actual
            self._expected_stream = torch.cuda.current_stream().cuda_stream
            runtime = ctypes.c_int()
            ctypes.CDLL("libcudart.so.13").cudaRuntimeGetVersion(ctypes.byref(runtime))
            metadata = {"event":"gpu_resource_ready", "enabled":False,
                "selected_sms":actual, "observed_smids":None,
                "partition_id":os.environ.get("CUDA_MPS_SM_PARTITION"),
                "torch_build_cuda":torch.version.cuda, "cuda_runtime":runtime.value,
                "pid":os.getpid(), "time_ns":time.time_ns(), "pair":os.environ["PAIR_LABEL"]}
            if runtime.value != 13010:
                raise RuntimeError("Expected actually loaded CUDA13.1 runtime, not only toolkit installation")
            folder = Path("/experiment/metadata")
            folder.mkdir(exist_ok=True)
            name = os.environ["PAIR_LABEL"] + "-qwen-" + str(os.getpid()) + "-" + str(time.time_ns()) + ".json"
            (folder/name).write_text(json.dumps(metadata,indent=2))
            self.get_logger().info(json.dumps(metadata))
            self._frozen_worker()
        except BaseException as error:
            self.load_error = error
            self.loaded.set()
            self.get_logger().error("MPS worker failure: " + repr(error))
        finally:
            if hasattr(self, "_gpu_timer"):
                self._gpu_timer.close()
            if torch is not None:
                torch.cuda.synchronize()
                gc.collect()
                torch.cuda.empty_cache()

    def _frozen_worker(self):
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
            self._gpu_timer = ForwardTimer(torch, model, "qwen")
            self._gpu_timer.configure(torch.cuda.current_stream(), 128)
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
            reply["server_enqueued_perf_ns"] = int(enqueued * 1e9)
            reply["server_started_perf_ns"] = int(started * 1e9)
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
                text = envelope.get("text")
                maximum = envelope.get("max_new_tokens", self.max_new_tokens or None)
                if not isinstance(text, str) or not text.strip() or len(text) > 32768:
                    raise ValueError(
                        "text must be nonblank and at most 32768 characters"
                    )
                if maximum is not None and (type(maximum) is not int or maximum < 1):
                    raise ValueError(
                        "max_new_tokens must be null or a positive integer"
                    )
                timing["envelope_parse_ms"] = (time.perf_counter() - started) * 1000
                timing_mode = envelope.get("timing_mode", "basic")
                if timing_mode not in ("basic", "tokens"):
                    raise ValueError("timing_mode must be basic or tokens")
                reply["timing_mode"] = timing_mode
                token_clock = TokenClock() if timing_mode == "tokens" else None
                preprocess_start = time.perf_counter_ns()
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
                requested_maximum = maximum
                # Resolve the generation budget from the model context.
                config = getattr(model.config, "text_config", model.config)
                context_limit = int(config.max_position_embeddings)
                remaining = context_limit - input_tokens
                if remaining < 1:
                    raise ValueError("No remaining model context")
                if maximum is None:
                    maximum = remaining
                elif maximum > remaining:
                    raise ValueError("Requested output exceeds remaining model context")
                reply["input_tokens"] = int(input_tokens)
                reply["input_ids_sha256"] = hashlib.sha256(
                    json.dumps(inputs["input_ids"][0].tolist()).encode()
                ).hexdigest()
                with torch.inference_mode():
                    timing["template_tokenize_ms"] = (
                        time.perf_counter_ns() - preprocess_start
                    ) / 1e6
                    transfer_start = time.perf_counter_ns()
                    inputs = {key: value.to("cuda") for key, value in inputs.items()}
                    # Default blocking .to() copies: wall span includes input availability.
                    timing["input_transfer_ms"] = (
                        time.perf_counter_ns() - transfer_start
                    ) / 1e6
                    if torch.cuda.current_stream().cuda_stream != self._expected_stream:
                        raise RuntimeError("Request GPU work escaped selected stream")
                    self._gpu_timer.reset()
                    reply["model_start_perf_ns"] = time.perf_counter_ns()
                    generate_start = time.perf_counter_ns()
                    generation_options = (
                        {"streamer": token_clock} if token_clock else {}
                    )
                    if os.environ.get("BENCH_FORCE_LENGTH") == "1":
                        generation_options["min_new_tokens"] = maximum
                    output = model.generate(
                        **inputs,
                        **generation_options,
                        max_new_tokens=maximum,
                        do_sample=False,
                        use_cache=True,
                        pad_token_id=tokenizer.eos_token_id,
                    )
                    # Generation already reads CUDA output tokens for stopping/streaming.
                    # One completion boundary per request, never per-token synchronize.
                    torch.cuda.synchronize()
                    timing["generate_wall_ms"] = (
                        time.perf_counter_ns() - generate_start
                    ) / 1e6
                    reply["model_end_perf_ns"] = time.perf_counter_ns()
                    forward_times = self._gpu_timer.elapsed()
                    stages = summarize_forward(self._gpu_timer.lengths, forward_times, int(input_tokens), int(maximum))
                    timing["gpu_prefill_span_ms"] = stages["prefill_forward_ms"]
                    timing["gpu_decode_total_span_ms"] = stages["decode_forward_total_ms"]
                    timing["gpu_decode_ms_per_token"] = stages["decode_forward_ms_per_token"]
                    timing["gpu_forward_span_ms"] = sum(forward_times)
                    reply["gpu_forward_event_ms"] = forward_times
                    reply["gpu_forward_lengths"] = list(self._gpu_timer.lengths)
                    if token_clock is not None:
                        token_metrics = token_clock.metrics(
                            generate_start, int(enqueued * 1e9)
                        )
                        timing.update(
                            {k: v for k, v in token_metrics.items() if k != "itl_ms"}
                        )
                        reply["itl_ms"] = token_metrics["itl_ms"]
                    decode_start = time.perf_counter_ns()
                    generated = output[0, input_tokens:]
                    reply.update(
                        status="ok",
                        text=tokenizer.decode(generated, skip_special_tokens=True),
                        output_tokens=int(generated.shape[-1]),
                        generation_mode="eos"
                        if requested_maximum is None
                        else "bounded",
                        effective_max_new_tokens=maximum,
                        context_limit=context_limit,
                    )
                    eos = model.generation_config.eos_token_id or tokenizer.eos_token_id
                    eos_ids = eos if isinstance(eos, (list, tuple)) else [eos]
                    reply["finish_reason"] = (
                        "eos" if int(generated[-1].item()) in eos_ids else "length"
                    )
                    timing["output_decode_ms"] = (
                        time.perf_counter_ns() - decode_start
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
        publisher = self.create_publisher(String, "/qwen/result/" + request_id, 1)
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
        self.worker.join()  # Finish the running GPU call before destroying the publisher.


class TokenClock:
    """Timestamp stock streamer output; prompt ignored, no text decoding or I/O."""

    def __init__(self):
        self.prompt = True
        self.times = []

    def put(self, value):
        if self.prompt:
            self.prompt = False
            return
        # Current greedy batch1 generation emits one token per callback.
        count = 1
        for dimension in value.shape:
            count *= dimension
        if count != 1:
            raise ValueError("Token timing requires one generated token per callback")
        self.times.append(time.perf_counter_ns())

    def end(self):
        pass

    def metrics(self, generate_start, server_received):
        n = len(self.times)
        intervals = [(b - a) / 1e6 for a, b in zip(self.times, self.times[1:])]
        return {
            "generate_ttft_ms": (self.times[0] - generate_start) / 1e6 if n else None,
            "server_ttft_ms": (self.times[0] - server_received) / 1e6 if n else None,
            "decode_span_ms": (self.times[-1] - self.times[0]) / 1e6 if n else None,
            "tpot_ms": sum(intervals) / (n - 1) if n > 1 else None,
            "itl_ms": intervals,
        }


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
