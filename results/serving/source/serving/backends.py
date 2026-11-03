"""Thin stock-model adapters. No model imports or GPU allocation at module import."""

import io
import json
import logging
import time
from PIL import Image, UnidentifiedImageError

MAX_FILE_BYTES = 10 * 1024 * 1024
MAX_PIXELS = 16_000_000
LOG = logging.getLogger("serving")


class InputError(Exception):
    def __init__(self, status_code, detail):
        super().__init__(detail)
        self.status_code = status_code
        self.detail = detail


def decode_image(data):
    if len(data) > MAX_FILE_BYTES:
        raise InputError(413, "Image exceeds 10 MiB")
    try:
        with Image.open(io.BytesIO(data)) as image:
            if image.format not in ("PNG", "JPEG"):
                raise InputError(400, "Only JPEG and PNG images are accepted")
            if image.width * image.height > MAX_PIXELS:
                raise InputError(413, "Image exceeds 16 million pixels")
            return image.convert("RGB")
    except (UnidentifiedImageError, OSError, ValueError) as error:
        raise InputError(400, "Invalid or incomplete image") from error
    except Image.DecompressionBombError as error:
        raise InputError(413, "Decoded image is too large") from error


def prepare_qwen_inputs(tokenizer, text):
    prompt = tokenizer.apply_chat_template(
        [{"role": "user", "content": text}],
        tokenize=False,
        add_generation_prompt=True,
        enable_thinking=False,
    )
    encoded = tokenizer(prompt, return_tensors="pt")
    if encoded["input_ids"].shape[-1] > 2048:
        raise InputError(422, "Input including chat template exceeds 2048 tokens")
    return encoded


class QwenBackend:
    def __init__(self, model_path):
        import torch
        from transformers import AutoTokenizer, Qwen3_5ForConditionalGeneration
        from scripts.acceleration import inspect_qwen_bindings

        started = time.perf_counter()
        self.torch = torch
        torch.set_num_threads(4)
        torch.cuda.set_device(0)
        self.tokenizer = AutoTokenizer.from_pretrained(
            model_path, local_files_only=True
        )
        self.model = (
            Qwen3_5ForConditionalGeneration.from_pretrained(
                model_path,
                dtype=torch.bfloat16,
                local_files_only=True,
                attn_implementation="sdpa",
            )
            .eval()
            .to("cuda")
        )
        bindings = inspect_qwen_bindings()
        self({"text": "Reply with one short greeting.", "max_new_tokens": 8})
        LOG.info(
            json.dumps(
                {
                    "event": "backend_loaded",
                    "model": "qwen",
                    "load_and_warmup_seconds": time.perf_counter() - started,
                    "dtype": "bfloat16",
                    "attention": "sdpa",
                    "bindings": bindings,
                }
            )
        )

    def __call__(self, payload):
        torch = self.torch
        with torch.inference_mode():
            encoded = prepare_qwen_inputs(self.tokenizer, payload["text"])
            inputs = {k: v.to("cuda") for k, v in encoded.items()}
            output = self.model.generate(
                **inputs,
                max_new_tokens=payload["max_new_tokens"],
                do_sample=False,
                use_cache=True,
                pad_token_id=self.tokenizer.eos_token_id,
            )
            tokens = output[0, encoded["input_ids"].shape[-1] :]
            text = self.tokenizer.decode(tokens, skip_special_tokens=True)
            torch.cuda.synchronize()
            return {"text": text, "output_tokens": int(tokens.shape[-1])}


class YoloBackend:
    def __init__(self, model_path):
        import torch
        from ultralytics import YOLO
        from scripts.acceleration import inspect_cv_backend

        started = time.perf_counter()
        self.torch = torch
        torch.set_num_threads(4)
        torch.cuda.set_device(0)
        self.model = YOLO(model_path)
        self(Image.new("RGB", (640, 640)))
        precision = inspect_cv_backend(self.model)
        LOG.info(
            json.dumps(
                {
                    "event": "backend_loaded",
                    "model": "yolo",
                    "load_and_warmup_seconds": time.perf_counter() - started,
                    **precision,
                }
            )
        )

    def __call__(self, image):
        with self.torch.inference_mode():
            result = self.model.predict(
                image,
                device=0,
                imgsz=640,
                quantize=16,
                batch=1,
                rect=False,
                verbose=False,
                save=False,
            )[0]
            boxes = result.boxes.data.cpu().tolist()
            detections = [
                {
                    "class_id": int(row[5]),
                    "label": result.names[int(row[5])],
                    "confidence": float(row[4]),
                    "xyxy": row[:4],
                }
                for row in boxes
            ]
            self.torch.cuda.synchronize()
            return {
                "width": image.width,
                "height": image.height,
                "detections": detections,
            }
