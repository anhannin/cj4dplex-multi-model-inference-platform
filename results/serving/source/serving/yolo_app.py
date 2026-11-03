import asyncio
import os
from fastapi import File, HTTPException, Request, UploadFile
from pydantic import BaseModel
from serving.backends import MAX_FILE_BYTES, InputError, YoloBackend, decode_image
from serving.http import Timing, base_app, submit


class Detection(BaseModel):
    model_config = {"allow_inf_nan": False}
    class_id: int
    label: str
    confidence: float
    xyxy: tuple[float, float, float, float]


class DetectResponse(Timing):
    width: int
    height: int
    detections: list[Detection]


def create_app(backend_factory=None, queue_capacity=None):
    factory = (
        backend_factory
        if backend_factory is not None
        else lambda: YoloBackend(
            os.environ.get("YOLO_MODEL_PATH", "/assets/yolo26l.pt")
        )
    )
    app = base_app("yolo", factory, queue_capacity)

    @app.post("/detect", response_model=DetectResponse)
    async def detect(request: Request, file: UploadFile = File(...)):
        try:
            data = await file.read(MAX_FILE_BYTES + 1)
            image = await asyncio.to_thread(decode_image, data)
        except InputError as error:
            raise HTTPException(error.status_code, error.detail) from None
        finally:
            await file.close()
        return await submit(request, image)

    return app


app = create_app()
