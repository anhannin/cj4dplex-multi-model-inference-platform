#!/usr/bin/env python3
"""Standalone Qwen HTTP service: own FIFO, one GPU worker, native SDK calls."""

import asyncio
from contextlib import asynccontextmanager
import itertools
import json
import logging
import os
import queue
import threading
import time
import uuid

from fastapi import FastAPI, HTTPException, Request
from pydantic import BaseModel, Field, field_validator

LOG = logging.getLogger("qwen_api")
LOG.setLevel(logging.INFO)
LOG.propagate = False
if not LOG.handlers:
    LOG.addHandler(logging.StreamHandler())


class GenerateRequest(BaseModel):
    text: str = Field(min_length=1, max_length=32768)
    max_new_tokens: int = Field(default=128, ge=1, le=512)

    @field_validator("text")
    @classmethod
    def not_blank(cls, value):
        if not value.strip():
            raise ValueError("Text must not be blank")
        return value


def create_app(queue_capacity=None):
    capacity = (
        int(os.environ.get("QUEUE_CAPACITY", "8"))
        if queue_capacity is None
        else queue_capacity
    )
    if capacity < 1:
        raise ValueError("QUEUE_CAPACITY must be positive")

    @asynccontextmanager
    async def lifespan(app):
        loop = asyncio.get_running_loop()
        requests = queue.Queue(maxsize=capacity)
        stopping = threading.Event()
        loaded = loop.create_future()
        app.state.requests = requests
        app.state.sequence = itertools.count(1)

        def complete(future, result=None, error=None):
            # Executed on the ASGI event loop, never on the GPU thread.
            if not future.done():
                if error is None:
                    future.set_result(result)
                else:
                    future.set_exception(error)

        def worker():
            try:
                import inspect
                import torch
                from transformers import AutoTokenizer, Qwen3_5ForConditionalGeneration
                from transformers.models.qwen3_5 import modeling_qwen3_5

                torch.set_num_threads(4)
                torch.cuda.set_device(0)
                path = os.environ.get(
                    "MODEL_PATH",
                    "/cache/models--Qwen--Qwen3.5-9B/snapshots/c202236235762e1c871ad0ccb60c8ee5ba337b9a",
                )
                tokenizer = AutoTokenizer.from_pretrained(path, local_files_only=True)
                model = (
                    Qwen3_5ForConditionalGeneration.from_pretrained(
                        path,
                        dtype=torch.bfloat16,
                        local_files_only=True,
                        attn_implementation="sdpa",
                    )
                    .eval()
                    .to("cuda")
                )
                for attribute, prefix in [
                    ("causal_conv1d_fn", "causal_conv1d."),
                    ("causal_conv1d_update", "causal_conv1d."),
                    ("torch_chunk_gated_delta_rule", "fla."),
                    ("torch_recurrent_gated_delta_rule", "fla."),
                ]:
                    selected = inspect.getclosurevars(
                        getattr(modeling_qwen3_5, attribute)
                    ).nonlocals.get("implementation")
                    if not getattr(selected, "__module__", "").startswith(prefix):
                        raise RuntimeError("Missing GPU acceleration: " + attribute)
            except Exception as error:
                loop.call_soon_threadsafe(
                    complete, loaded, None, error.with_traceback(None)
                )
                return
            for event in ("backend_loaded", "model_ready"):
                LOG.info(
                    json.dumps({"event": event, "model": "qwen", "time": time.time()})
                )
            loop.call_soon_threadsafe(complete, loaded)
            while not stopping.is_set():
                try:
                    sequence, enqueued, request_id, payload, future = requests.get(
                        timeout=0.1
                    )
                except queue.Empty:
                    continue
                try:
                    if future.cancelled():
                        continue
                    started = time.perf_counter()
                    wait_ms = (started - enqueued) * 1000
                    LOG.info(
                        json.dumps(
                            {
                                "event": "inference_started",
                                "model": "qwen",
                                "sequence": sequence,
                                "request_id": request_id,
                                "time": time.time(),
                                "queue_wait_ms": wait_ms,
                            }
                        )
                    )
                    try:
                        prompt = tokenizer.apply_chat_template(
                            [{"role": "user", "content": payload["text"]}],
                            tokenize=False,
                            add_generation_prompt=True,
                            enable_thinking=False,
                        )
                        inputs = tokenizer(prompt, return_tensors="pt")
                        count = inputs["input_ids"].shape[-1]
                        if count > 2048:
                            raise HTTPException(
                                422, "Input including chat template exceeds 2048 tokens"
                            )
                        with torch.inference_mode():
                            inputs = {k: v.to("cuda") for k, v in inputs.items()}
                            output = model.generate(
                                **inputs,
                                max_new_tokens=payload["max_new_tokens"],
                                do_sample=False,
                                use_cache=True,
                                pad_token_id=tokenizer.eos_token_id,
                            )
                            generated = output[0, count:]
                            result = {
                                "text": tokenizer.decode(
                                    generated, skip_special_tokens=True
                                ),
                                "output_tokens": int(generated.shape[-1]),
                            }
                            torch.cuda.synchronize()
                    except Exception as error:
                        LOG.error(
                            json.dumps(
                                {
                                    "event": "inference_error",
                                    "model": "qwen",
                                    "sequence": sequence,
                                    "request_id": request_id,
                                    "time": time.time(),
                                    "error_type": type(error).__name__,
                                }
                            )
                        )
                        public = (
                            error
                            if isinstance(error, HTTPException)
                            else HTTPException(500, "Inference failed")
                        )
                        loop.call_soon_threadsafe(
                            complete, future, None, public.with_traceback(None)
                        )
                    else:
                        elapsed = (time.perf_counter() - started) * 1000
                        result.update(
                            request_id=request_id,
                            sequence=sequence,
                            queue_wait_ms=wait_ms,
                            processing_ms=elapsed,
                        )
                        LOG.info(
                            json.dumps(
                                {
                                    "event": "inference_finished",
                                    "model": "qwen",
                                    "sequence": sequence,
                                    "request_id": request_id,
                                    "time": time.time(),
                                    "processing_ms": elapsed,
                                }
                            )
                        )
                        loop.call_soon_threadsafe(complete, future, result)
                finally:
                    requests.task_done()
                    del payload

        thread = threading.Thread(target=worker, name="qwen-inference")
        app.state.worker = thread
        thread.start()
        try:
            await loaded
            yield
        finally:
            stopping.set()
            await asyncio.to_thread(thread.join)
            while not requests.empty():
                *_, future = requests.get_nowait()
                future.cancel()
                requests.task_done()

    app = FastAPI(title="Qwen inference", lifespan=lifespan)

    async def submit(request, payload):
        if not app.state.worker.is_alive():
            raise HTTPException(503, "Model is not accepting requests")
        future = asyncio.get_running_loop().create_future()
        job = (
            next(app.state.sequence),
            time.perf_counter(),
            uuid.uuid4().hex,
            payload,
            future,
        )
        try:
            app.state.requests.put_nowait(job)
        except queue.Full:
            future.cancel()
            raise HTTPException(429, "Request queue is full") from None
        try:
            while True:
                done, _ = await asyncio.wait({future}, timeout=0.1)
                if done:
                    return future.result()
                if await request.is_disconnected():
                    raise HTTPException(499, "Client disconnected")
        finally:
            if not future.done():
                future.cancel()
            elif not future.cancelled():
                future.exception()  # Retrieve errors in completion/disconnect races.

    @app.post("/generate")
    async def generate(payload: GenerateRequest, request: Request):
        return await submit(request, payload.model_dump())

    return app


app = create_app()

if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        app,
        host=os.environ.get("HOST", "127.0.0.1"),
        port=int(os.environ.get("PORT", "8001")),
        workers=1,
        access_log=False,
        timeout_graceful_shutdown=180,
    )
