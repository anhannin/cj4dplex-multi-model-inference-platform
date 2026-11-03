"""Upload one JPEG/PNG. Uses Python standard library only."""

import argparse
import json
from pathlib import Path
import time
from urllib.error import HTTPError
from urllib.request import Request, urlopen
import uuid


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("image", type=Path)
    parser.add_argument("--url", default="http://127.0.0.1:8002/detect")
    parser.add_argument("--timeout", type=float, default=300)
    args = parser.parse_args()
    data = args.image.read_bytes()
    if len(data) > 10 * 1024 * 1024:
        raise SystemExit("Image exceeds 10 MiB")
    boundary = uuid.uuid4().hex
    body = (
        (
            f'--{boundary}\r\nContent-Disposition: form-data; name="file"; filename="image"\r\n'
            "Content-Type: application/octet-stream\r\n\r\n"
        ).encode()
        + data
        + f"\r\n--{boundary}--\r\n".encode()
    )
    request = Request(
        args.url,
        data=body,
        headers={"Content-Type": "multipart/form-data; boundary=" + boundary},
        method="POST",
    )
    started = time.perf_counter()
    try:
        with urlopen(request, timeout=args.timeout) as response:
            result = json.load(response)
    except HTTPError as error:
        raise SystemExit(f"HTTP {error.code}: {error.read().decode()}") from None
    print(
        json.dumps(
            {"http_e2e_ms": (time.perf_counter() - started) * 1000, "response": result},
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
