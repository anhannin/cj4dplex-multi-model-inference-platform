# CJ 4DPLEX Multi-Model Inference Platform — Baseline v1

**현재 브랜치: baseline (최적화 전 기준선 보존본).**
Qwen3.5-9B + YOLO26l, 단일 DGX Spark, Kubernetes/ROS 2 독립 서빙.

- [보존 내역·실제 이미지 백업·복원 절차](baseline/README.ko.md)
- [5조건 기본 성능 측정 결과](results/latency-baseline/README.ko.md)
- [계측·반복 측정 코드](benchmark/README.ko.md)
- [고정 이미지 ID·SHA-256 manifest](baseline/MANIFEST.json)

아래 내용은 이전 구현·초기 탐색 기록이다. 현재 기준선은 위 문서를 우선한다.

---

> **Current ROS v2 clients:** [request_qwen.py](clients/request_qwen.py), [request_yolo.py](clients/request_yolo.py), [usage](clients/README.md). Fixed requests, UUID-specific result channels; native Spark execution.

> **Spark host now has native ROS 2 Jazzy:** [direct ros2 requests without Docker](ros2/SPARK_HOST.md).

> **Standalone FastAPI files:** [api/qwen_api.py](api/qwen_api.py), [api/yolo_api.py](api/yolo_api.py), [guide](api/README.md). Verified images/containers are retained, stopped after tests; existing ROS runtime unchanged.

> **Current runtime: ROS 2** — [two standalone nodes](ros2/README.md).
> ROS nodes are resident; the existing FastAPI containers are retained but stopped.

> **HTTP serving is now implemented:** [minimal API guide](docs/minimal-serving.md).
> Qwen and YOLO have separate resident models and independent FIFO queues on Spark.

> Current environment: separate accelerated Qwen/YOLO images and named development
> containers are ready. Start with [container instructions](containers/README.ko.md).
> The initial exploration below is historical; its exact scripts are archived under
> `results/source-20261102-initial/`. Do not run the old launcher with the current worker.

# CJ Multi-Model Serving — initial feasibility exploration

This workspace currently contains **model-level experiments**, not a completed API
service or final assignment implementation. Approved candidates: Qwen3.5-9B
(text-only usage) and YOLO26l (object detection), sharing one DGX Spark GB10.

## Files and tests

- `scripts/worker.py`: independent GPU model workers, warmup, raw request timings.
- `scripts/run_preflight.py`: bounded standalone / co-resident / concurrent trials.
- `scripts/metrics.py`: dependency-free statistics and shared-window filtering.
- `scripts/launch_remote.sh`: GPU-idle guard and disposable container launch.
- `results/`: captured evidence and exploration reports, when available.

```bash
python3 -m unittest discover -s tests -v
python3 -m compileall -q scripts tests
```

## Experiment environment and reproduction

The initial exploration uses an already installed NVIDIA PyTorch container
`dmd-qwen35:no-torchao`, whose immutable image ID is captured in results. The local
image is not a publicly reproducible distribution; a clean public image build is
future work. Host Python, drivers, existing research environments and cached model
weights are not modified. Dependencies are installed only into the project venv
under `/home/avees/cj-preflight`, inside this image, with system packages inherited.

Remote layout: `~/cj-preflight/{scripts,assets,results,venv}`. Cached Qwen snapshot:
`c202236235762e1c871ad0ccb60c8ee5ba337b9a`.
YOLO weights: https://github.com/ultralytics/assets/releases/download/v8.4.0/yolo26l.pt
Demo images: https://ultralytics.com/images/bus.jpg and
https://ultralytics.com/images/zidane.jpg (smoke/performance only, no accuracy claim).
Download log, input hashes, environment and package versions are saved with results.
Do not redistribute cached weights or demo images without checking their terms.
Qwen model license: Apache-2.0. Ultralytics code/model licensing: AGPL-3.0 / Enterprise;
final project distribution must be reviewed for applicable requirements.

After restoring the recorded project dependencies and assets inside the recorded
image, copying scripts to the remote project directory, and confirming GPU idleness:

```bash
bash ~/cj-preflight/scripts/launch_remote.sh
```

The script uses a uniquely named, disposable container, network disabled and model
cache mounted read-only. It refuses startup if compute workloads are present.
A run lasts up to 30 minutes, with a 6-minute worker-ready timeout and bounded
per-phase waits. The launcher must not be run concurrently with itself.

## Measurement contract

- One synchronous, closed-loop request per active worker; no API, queue or network.
- Both workers use the same settings across conditions, no MPS or resource partition.
- LLM: BF16, SDPA, fixed synthetic prompt (actual token count recorded), greedy
  generation, exactly 128 new tokens (forced length for controlled comparison).
- CV: FP16, batch 1, 640 square input, alternating two predecoded demo images.
- Three warmup calls per fresh worker; model loading and warmup excluded from trials.
- Wall-clock call latency includes host-to-device work and synchronized completion;
  CV includes preprocessing, inference, postprocessing and CPU box retrieval, but
  excludes image-file decoding. LLM excludes prompt tokenization and output decoding.
- TTFT/TPOT are generation callback timestamps, **not HTTP streaming metrics**.
  Framework callback / per-token CPU-copy overhead is present in every condition.
- Each phase starts at a common timestamp and runs 60 seconds; only requests fully
  inside the shared time window enter summary latency/throughput. Boundary requests
  remain in raw JSONL. Throughput is a conservative contained-request window rate.
- Percentiles use linear interpolation. Small LLM sample counts are exploratory,
  not sufficient for SLO claims. No repeated-trial confidence intervals yet.
- Resource samples include GPU utilization/power/temperature, host available memory,
  CPU utilization and process RSS. Torch allocation/reservation is recorded per
  request. GB10 `nvidia-smi` aggregate device-memory usage is unavailable; do not
  call host RAM or RSS a measured discrete VRAM value or sum shared-memory metrics.

## Boundaries

These trials establish feasibility and initial interference evidence only. They do
not establish production readiness, correctness accuracy, SLO, queue behavior,
open-loop overload behavior, recovery performance or the benefit of SM partitioning.
AI Coding Assistant use: Codex authored the exploration harness, tests and notes;
all experimental results must come from recorded execution, not generated values.

## Separate accelerated model images

The next environment iteration provides distinct Qwen and YOLO images from a pinned
public NVIDIA base. See [container instructions](containers/README.ko.md) for the
build, acceleration validation, development shell and independent-container tests.
The old `run_preflight.py` and `source-20261102-initial/` preserve the initial fallback
experiment; they are not the accelerated-container launch path.
