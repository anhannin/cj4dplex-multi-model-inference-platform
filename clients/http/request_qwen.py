"""Send one synchronous Qwen request; no ROS or GPU libraries required."""

import argparse
import json
import time
from urllib.error import HTTPError
from urllib.request import Request, urlopen


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("text")
    parser.add_argument("--url", default="http://127.0.0.1:8001/generate")
    parser.add_argument("--max-new-tokens", type=int, default=128)
    parser.add_argument("--timeout", type=float, default=300)
    args = parser.parse_args()
    request = Request(
        args.url,
        data=json.dumps(
            {"text": args.text, "max_new_tokens": args.max_new_tokens}
        ).encode(),
        headers={"Content-Type": "application/json"},
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
