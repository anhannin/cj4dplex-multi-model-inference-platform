import os
from fastapi import Request
from pydantic import BaseModel, Field, field_validator
from serving.backends import QwenBackend
from serving.http import Timing, base_app, submit

DEFAULT_MODEL = (
    "/cache/models--Qwen--Qwen3.5-9B/snapshots/c202236235762e1c871ad0ccb60c8ee5ba337b9a"
)


class GenerateRequest(BaseModel):
    text: str = Field(min_length=1, max_length=32768)
    max_new_tokens: int = Field(default=128, ge=1, le=512)

    @field_validator("text")
    @classmethod
    def not_blank(cls, value):
        if not value.strip():
            raise ValueError("Text must not be blank")
        return value


class GenerateResponse(Timing):
    text: str
    output_tokens: int


def create_app(backend_factory=None, queue_capacity=None):
    factory = (
        backend_factory
        if backend_factory is not None
        else lambda: QwenBackend(os.environ.get("MODEL_PATH", DEFAULT_MODEL))
    )
    app = base_app("qwen", factory, queue_capacity)

    @app.post("/generate", response_model=GenerateResponse)
    async def generate(payload: GenerateRequest, request: Request):
        return await submit(request, payload.model_dump())

    return app


app = create_app()
