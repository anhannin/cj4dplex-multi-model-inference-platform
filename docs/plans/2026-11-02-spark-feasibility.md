# Spark 9B + YOLO26l feasibility plan

Goal: validate the approved model pair without changing existing research environments.
Scope: exploration, not production serving or final SLO evidence.
Architecture: two independent Python worker processes in a disposable GPU container,
using a project-specific Python environment; cached Qwen weights mounted read-only.
Compare standalone, co-resident idle, and simultaneous inference. No MPS/partitioning.

1. Capture OS, GPU, memory, image digest and dependency versions.
2. Isolate dependencies; validate CUDA and required model imports.
3. Test summary math and overlap checks before implementing benchmark utilities.
4. Smoke each model, recording correctness sanity checks, settings, hashes and warnings.
5. Warm up, then bounded closed-loop single-request-per-worker experiments.
   Record per-request wall time, token timing (synchronized token callbacks),
   CV pipeline latency and framework stage times, process/GPU resource samples.
6. Compare only overlapping simultaneous samples. Retain raw failures and logs.
7. Copy results locally, inspect and report measured limits honestly.

Stop on unsupported kernels, OOM, foreign GPU compute jobs, or per-phase timeout.
Do not modify existing containers, model files, drivers or research code.
Later work: API/queue instrumentation, open-loop traffic, repeated trials, SLO and failure recovery.
