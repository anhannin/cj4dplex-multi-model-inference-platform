#!/usr/bin/env python3
"""Standalone YOLO HTTP service: own FIFO, one GPU worker, native SDK calls."""

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
import io
from fastapi import File, UploadFile
from fastapi import FastAPI, HTTPException, Request


LOG = logging.getLogger("yolo_api")
LOG.setLevel(logging.INFO)
LOG.propagate = False
if not LOG.handlers:
    LOG.addHandler(logging.StreamHandler())


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
                import torch
                from PIL import Image, UnidentifiedImageError
                from ultralytics import YOLO

                torch.set_num_threads(4)
                torch.cuda.set_device(0)
                model = YOLO(os.environ.get("YOLO_MODEL_PATH", "/assets/yolo26l.pt"))
                options = dict(
                    device=0,
                    imgsz=640,
                    quantize=16,
                    batch=1,
                    rect=False,
                    verbose=False,
                    save=False,
                )
                model.predict(Image.new("RGB", (640, 640)), **options)
                backend = model.predictor.model
                parameter = next(backend.model.parameters())
                if (
                    backend.device.type != "cuda"
                    or not backend.fp16
                    or parameter.dtype != torch.float16
                ):
                    raise RuntimeError("Executing backend is not native CUDA FP16")
            except Exception as error:
                loop.call_soon_threadsafe(
                    complete, loaded, None, error.with_traceback(None)
                )
                return
            for event in ("backend_loaded", "model_ready"):
                LOG.info(
                    json.dumps({"event": event, "model": "yolo", "time": time.time()})
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
                                "model": "yolo",
                                "sequence": sequence,
                                "request_id": request_id,
                                "time": time.time(),
                                "queue_wait_ms": wait_ms,
                            }
                        )
                    )
                    try:
                        try:
                            with Image.open(io.BytesIO(payload)) as source:
                                if source.format not in ("JPEG", "PNG"):
                                    raise HTTPException(
                                        400, "Only JPEG and PNG are accepted"
                                    )
                                if source.width * source.height > 16_000_000:
                                    raise HTTPException(
                                        413, "Image exceeds 16 million pixels"
                                    )
                                image = source.convert("RGB")
                        except Image.DecompressionBombError:
                            raise HTTPException(413, "Image is too large") from None
                        except (UnidentifiedImageError, OSError, ValueError):
                            raise HTTPException(
                                400, "Invalid or incomplete image"
                            ) from None
                        with torch.inference_mode():
                            prediction = model.predict(image, **options)[0]
                            rows = prediction.boxes.data.cpu().tolist()
                            result = {
                                "width": image.width,
                                "height": image.height,
                                "detections": [
                                    {
                                        "class_id": int(row[5]),
                                        "label": prediction.names[int(row[5])],
                                        "confidence": float(row[4]),
                                        "xyxy": row[:4],
                                    }
                                    for row in rows
                                ],
                            }
                            torch.cuda.synchronize()
                    except Exception as error:
                        LOG.error(
                            json.dumps(
                                {
                                    "event": "inference_error",
                                    "model": "yolo",
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
                                    "model": "yolo",
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

        thread = threading.Thread(target=worker, name="yolo-inference")
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

    app = FastAPI(title="YOLO inference", lifespan=lifespan)

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

    @app.post("/detect")
    async def detect(request: Request, file: UploadFile = File(...)):
        try:
            data = await file.read(10 * 1024 * 1024 + 1)
        finally:
            await file.close()
        if len(data) > 10 * 1024 * 1024:
            raise HTTPException(413, "Image exceeds 10 MiB")
        return await submit(request, data)

    return app


app = create_app()

if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        app,
        host=os.environ.get("HOST", "127.0.0.1"),
        port=int(os.environ.get("PORT", "8002")),
        workers=1,
        access_log=False,
        timeout_graceful_shutdown=180,
    )
