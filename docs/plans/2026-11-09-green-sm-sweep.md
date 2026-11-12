# Real-model Green Context SM sensitivity experiment

**Goal:** Plot latency vs actual Green Context SM allocation for Qwen3.5-9B and YOLO26l on the existing GB10, not synthetic arithmetic and not an E2E/concurrency claim.
**Architecture:** Isolated diagnostic containers from frozen baseline images, one active model at a time, stock framework APIs and weights unmodified. Back up live deployments, temporarily scale original two services to zero, restore exact saved templates/replica counts in finally. No MPS, TensorRT, CUDA Graph capture, driver/clock/security-policy changes.
**Approval context:** User requested the real-model SM sweep after agreeing the shown graph's interpretation and prefill/decode distinction. This document fixes reproducible measurement details before implementation.

## Evaluator contract
- GB10 expected48 SM, minimum/alignment queried from CUDA13 Driver API. Sweep8/16/24/32/40/48; verify requested==actual, Green stream owner and sampled SM set size. Full48 must itself be Green, plus independent default-context full48 reference.
- Qwen9B BF16 SDPA + pinned stock FLA/causal-conv kernels, batch1. Exactly512 input tokens including the chat template, forced128 generated tokens using stock min_new_tokens=max_new_tokens=128. Same GPU input IDs at every point; save SHA and exact IDs. Greedy, use_cache=True, no sampling. No accuracy/byte-equality guarantee from floating-point variations.
- Qwen measures first forward(Prefill) and127 subsequent one-token forwards(Decode). CUDA events recorded on selected stream, preinitialized outside timed calls, one final synchronization per generation (no added per-token sync). Plot mean per-run prefill device-timeline span and mean decode forward span per token. Also retain generate wall, server-independent generate TTFT and wall TPOT from original TokenClock. These are NOT pure kernel busy time, API E2E or whole-service latency.
- YOLO26l original PyTorch FP16, fixed bus.jpg, imgsz640, rect=False,batch1. Stock predict() with CUDA events on native underlying model forward, plus predict wall measured through selected-stream completion. Image read/decode and result drawing/saving excluded. Verify native CUDA FP16 and detections against full default reference (same classes/counts, IoU>=.98/confidence delta<=.02); preserve outputs.
- Main sample counts: Qwen30 generations/SM, YOLO100 images/SM, split two counterbalanced rounds (15/50 each), warmup3/10 per point/round. Fixed seeded SM order then reverse. Separate default full-GPU references before/after with5 Qwen and50 YOLO measured calls and equivalent warmup. Report raw rows, mean/std/median/p95/count, per-round drift, no invented SLO or population-tail confidence.
- CUDA Graph OFF (stock eager); user image uses RTX5090 and CUDA Graph ON, so only plot concept is reproduced, not numerical comparability.
- Structural validation separate from performance: Nsight Systems CUPTI greenContextId for actual model kernels at minimum/maximum SM, profiled data never pooled into curves. At minimum verify stream handles, allocated resource and native event operation before long runs.
- Limits: small handful of SM points constrained by hardware; shape-specific, one model active, no conclusion about simultaneous two-Pod speedup/global physical ownership/MPS or transport optimization.

## Implementation sequence
1. Unit tests first for metric stage decomposition, exact-token prompt construction, schedule, aggregation and fixed-work validation.
2. New native single-Green binding supporting full48 (do not modify archived GreenPair source); build in existing ARM64 container. Runtime event/SM-ID smoke on8 and48.
3. Implement stock-model diagnostic runners and restoreable serialized host controller with fail-open Slack alerts and bounded process timeouts. Preserve failures and backups.
4. Pilot short Qwen/YOLO runs to verify hook counts, shapes, output count, CUDA event timings and native precision before main sweep; verify all-kernel Green binding separately.
5. Execute full fixed-corpus sweep and restore original two services with real ROS E2E health verification.
6. Plot means and variability with existing plotting libraries (no package installs), inspect figures, analyze marginal gains/plateaus from actual data. Archive raw samples, environment, source/image/input hashes and checksums locally and on Spark. Run tests/Ruff/compile and frozen baseline SHA checks.
