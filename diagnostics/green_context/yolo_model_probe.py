"""Functional stock YOLO predict on a Green stream, isolated from serving."""

import argparse
import gc
import json
from pathlib import Path
import torch
from PIL import Image
from ultralytics import YOLO
import green_bridge

p = argparse.ArgumentParser()
p.add_argument("--output", type=Path, required=True)
p.add_argument("--sms", type=int, default=16)
a = p.parse_args()
torch.set_num_threads(4)
torch.cuda.set_device(0)
pair = None
stream = None
result = {
    "state": "running",
    "model": "YOLO26l",
    "scope": "functional binding only, not latency baseline",
}
try:
    model = YOLO("/assets/yolo26l.pt")
    with Image.open("/assets/bus.jpg") as source:
        image = source.convert("RGB")
    options = dict(
        device=0, imgsz=640, quantize=16, batch=1, rect=False, verbose=False, save=False
    )
    with torch.inference_mode():
        reference = model.predict(image, **options)[0].boxes.data.cpu()
        assert model.predictor.model.fp16
        assert next(model.predictor.model.model.parameters()).dtype == torch.float16
        torch.cuda.synchronize()
        pair = green_bridge.GreenPair(a.sms)
        stream = torch.cuda.ExternalStream(pair.stream_ptr(0), device=0)
        stream.wait_stream(torch.cuda.current_stream())
        result["green_allocation"] = pair.metadata()
        torch.cuda.profiler.start()
        with torch.cuda.nvtx.range("yolo.green.predict"):
            with torch.cuda.stream(stream):
                prediction = model.predict(image, **options)[0]
            stream.synchronize()
        torch.cuda.profiler.stop()
        actual = prediction.boxes.data.cpu()
        torch.testing.assert_close(actual, reference, rtol=1e-3, atol=1e-3)
        result.update(
            state="PASS",
            detections=int(actual.shape[0]),
            same_classes=bool(torch.equal(actual[:, 5], reference[:, 5])),
            max_abs_error=float((actual - reference).abs().max()),
        )
        del prediction, actual, reference, model
    gc.collect()
    torch.cuda.synchronize()
    torch.cuda.empty_cache()
except Exception as error:
    result.update(state="FAIL", error=repr(error))
    raise
finally:
    if pair is not None:
        del stream
        pair.close()
    a.output.write_text(json.dumps(result, indent=2) + "\n")
print(json.dumps(result, indent=2))
