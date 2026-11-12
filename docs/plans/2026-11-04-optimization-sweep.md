# Multi-model optimization experiment plan

**Goal:** Recommend measured two-Pod improvements without modifying frozen baseline.
**Architecture:** Restoreable deployment-template overlays, same frozen images unless an explicitly labeled backend candidate requires a derived copy. Independent model queues and per-request result topics remain.
**Tech Stack:** Kubernetes, native ROS2/FastDDS, NVIDIA MPS, PyTorch and TensorRT.

## Evaluator contract (fixed before experimentation)
- Control: fresh co-resident baseline after per-user linger operational fix; historical v1 is reference only.
- Same Qwen3.5-9B BF16/SDPA, YOLO26l FP16 640x640 batch1, fixed five prompts/two public images, 128 generated-token cap, timing mode tokens.
- Primary workload: original benchmark, one outstanding request per model, YOLO runs until Qwen finishes (adaptive achieved rate, NOT fixed offered rate).
- Screening: five Qwen samples / five warmups, report YOLO actual sample count and throughput. Candidate order and warmup are recorded. Small-N p95 is exploratory, not an SLO guarantee.
- Finalists: fresh repeated control versus best; compare only equal protocols. Secondary paced CV test if faster CV materially changes achieved rate.
- Functional gates: zero measured errors, same model/precision/input/output contract, UUID routing, independent queues. TensorRT requires detection fidelity smoke checks; not a COCO mAP claim.
- Report mean/p95 E2E, Qwen TPOT/TTFT, YOLO inference and throughput, queue wait, failures. Do not add nested timing spans. Do not infer VRAM from unified host memory.
- Recommend Pareto improvement with low complexity; if tradeoffs remain, show CV-priority alternative, no invented business SLO. No automatic claim that lower latency at different load is isolation improvement.

## Sequential steps
1. Back up actual deployment templates; verify original baseline hashes. Verify E2E and fresh control.
2. Probe MPS actual client attachment (not merely daemon existence); unsupported/fallback is exclusion, not success. No global compute mode, clock, security or plugin policy changes.
3. Test CPU-affinity overlay based on measured fast-core IDs, preserve thread count.
4. Verify installed FastDDS schema; test reliable initial heartbeat/ACK delay XML without dropping reliability or destroying result publishers early. Apply to server AND clients.
5. Export separate YOLO TensorRT FP16 engine with stock exporter, never overwrite original weights. Test same original predict interface and detection quality before serving.
6. Screen supported candidates one at a time, GPU experiments never overlap. Combine only independently useful methods, remeasure.
7. Repeat control/finalist, retain raw data, summarize limitations and restore original templates. Stop own MPS daemon only after its clients exit. Leave working baseline, runnable candidate overlays, and recommendation.

## Validation
Tests cover overlay reversibility/preservation and summary calculation before changes. Fresh real benchmark responses prove service health, not ready-file alone. Validate 677 frozen file hashes after work. Preserve failed trials. Export logs/templates/env/tool versions for every candidate, and retrieve results locally. No commits or registry pushes required.

## Pre-export precision qualification
Installed stock8.4.198 `export_engine()` exports an FP32 ONNX graph and enables TensorRT FP16 tactics. Engine I/O may remain FP32; this is **FP16-enabled mixed precision**, not proof every layer and I/O are FP16. Candidate startup must verify actual TensorRT CUDA backend and log actual binding dtype, not falsely require/claim fp16 I/O. Baseline PyTorch native FP16 remains unchanged. Quality gate and precision-policy difference must be disclosed; this is a backend optimization, not pure resource partitioning isolation. No INT8/FP4.

## Screening follow-up
- Complete the eight cells of control / DDS / TensorRT / MPS-q50 combinations to distinguish marginal value of an engine/backend change from resource and transport changes. Extra uncapped/q75/CPU-affinity screens are alternatives, not pooled into the selected-combination result.
- Green+MPS synthetic concurrent progress passed, but cross-client disjoint physical-SM ownership is not validated; observed per-client SM-ID spaces overlap and their namespace semantics are not established. Do not deploy or rank Green as a serving optimization without lifecycle, synchronization and actual model/physical partition evidence.
- Preserve initial TensorRT startup integration failure: installed AutoBackend uses `.format == 'engine'`, not old `.engine` boolean. Failed source and startup traces are retained; corrected startup guard regression-tested before any successful measurement. This is not a baseline-image change, nor a steady-state request failure.
- Atomic JSON Patch replaces the entire saved deployment template during restore; JSON Merge Patch can retain experiment-only restart annotations. Verify exact live-vs-backup template equality, not just image names/readiness.

## Final audit logging finding
Raw request/timing JSONL is complete. The previous end-of-run server-log snapshot loses rotated history: confirm-a2-control YOLO publication coverage4020/8015; confirm-b winner131/16089. This does not remove E2E/inference/queue data embedded in every response, but it prevents complete primary-run post-response ACK analysis. Old Pod log directories were already deleted; do not reconstruct or fabricate missing events. Preserve this gap and original source version. Add pre-traffic log-follow capture, regression-test lifecycle, and validate separately on an original-baseline YOLO-only5000-frame run across actual log rotation. Do not pool that logging validation into before/after performance comparisons.
