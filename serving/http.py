"""Shared HTTP lifecycle/transport only; queue state is owned by each app instance."""

import asyncio
from contextlib import asynccontextmanager, suppress
import json
import logging
import os
import time
from fastapi import FastAPI, HTTPException, Request
from pydantic import BaseModel, ConfigDict
from serving.backends import InputError
from serving.queue import InferenceQueue, QueueFull, QueueClosed

LOG = logging.getLogger("serving")


class Timing(BaseModel):
    model_config = ConfigDict(allow_inf_nan=False)
    request_id: str
    sequence: int
    queue_wait_ms: float
    processing_ms: float


class RequestLogMiddleware:
    """Pure ASGI: leave the original receive/disconnect channel untouched."""

    def __init__(self, app, model):
        self.app = app
        self.model = model

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        started = time.perf_counter()
        status = 500

        async def logged_send(message):
            nonlocal status
            if message["type"] == "http.response.start":
                status = message["status"]
            await send(message)

        try:
            await self.app(scope, receive, logged_send)
        finally:
            LOG.info(
                json.dumps(
                    {
                        "event": "http_request",
                        "model": self.model,
                        "method": scope["method"],
                        "path": scope["path"],
                        "status": status,
                        "elapsed_ms": (time.perf_counter() - started) * 1000,
                    }
                )
            )


def base_app(name, factory, capacity):
    capacity = (
        int(os.environ.get("QUEUE_CAPACITY", "8")) if capacity is None else capacity
    )

    @asynccontextmanager
    async def lifespan(app):
        queue = InferenceQueue(factory, capacity=capacity, name=name)
        app.state.queue = queue
        try:
            await queue.start()
            yield
        finally:
            await queue.close()

    app = FastAPI(title=name + " inference", lifespan=lifespan)

    app.add_middleware(RequestLogMiddleware, model=name)

    return app


async def submit(request: Request, payload):
    task = asyncio.create_task(request.app.state.queue.submit(payload))
    try:
        while True:
            done, _ = await asyncio.wait({task}, timeout=0.1)
            if done:
                return task.result()
            if await request.is_disconnected():
                raise HTTPException(499, "Client disconnected")
    except QueueFull:
        raise HTTPException(429, "Request queue is full") from None
    except QueueClosed:
        raise HTTPException(503, "Model is not accepting requests") from None
    except InputError as error:
        raise HTTPException(error.status_code, error.detail) from None
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(500, "Inference failed") from None
    finally:
        if not task.done():
            task.cancel()
        with suppress(asyncio.CancelledError, Exception):
            # Always retrieve exceptions, including completion/disconnect races.
            await task
