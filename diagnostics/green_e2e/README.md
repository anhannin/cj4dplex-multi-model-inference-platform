# Actual two-Pod Green Context E2E combinations

This experiment measures **ROS2 client request E2E**, not the prior standalone CUDA-event curves or synthetic arithmetic. Conditions are matched **within each configured partition**: both models resident, Qwen-only traffic, YOLO-only traffic, then both active.

## Scope / fixed work
- GB10 single48-SM GPU, frozen original Qwen3.5-9B BF16/SDPA/native FLA and YOLO26l Torch FP16 images. No MPS, TensorRT, DDS tuning or CUDA Graph optimization.
- Fresh default48/48 control with ordinary primary contexts, plus Qwen/YOLO16/32,24/24,32/16,8/40,40/8. q/y labels are in that order. All five complementary splits are measured, not assumed to reproduce standalone performance.
- Same exact512 token IDs as prior standalone sweep (stock chat tokenizer round-trip verified SHA `6095b3535875488ee3f7934344507bfeb77ed3f68b2c210489f188957fc6ec2a`). Original message text API, no input-ID bypass. Output forced128 with stock min_new_tokens=max_new_tokens, greedy/cache enabled. Experimental copies only; normal serving generation budget is restored.
- Fixed original bus.jpg,640×640/batch1/rect=False. Each configuration QwenSolo10,YOLOSolo300,BothQwen10 with C1 YOLO until Qwen ends. Warmup3 each model/phase. These are **adaptive closed-loop achieved rates**, not equal fixed offered traffic. Show actual rates/counts.
- Original independent FIFO8 and worker/request UUID/result topics preserved. Only worker lifetime is wrapped in selected Torch CUDA stream; model APIs untouched. Read-only input hash/resource fields and controlled fixed-generation option are added. AST tests verify all nonworker node methods unchanged.
- Experimental ROS domain73 prevents mixing with old domain42 clients. Localhost discovery and original reliable/durability/ACK semantics retained. Initial discovery, input image file read/base64 preparation and visualization excluded as frozen benchmark; JSON serialization and response parsing included in E2E.
- Solo-active means **other model resident but idle**, not absent. Historical SM curves excluded ROS and removed other AI services; do not compare their durations directly to these E2Es.

## CUDA implementation / validation
`green_bridge.GreenPair(YOLO_SM)` is the existing CUDA13 splitter. Each separate worker process constructs the same split; YOLO uses part0 and Qwen part1. Both Green objects exist per process, but only the selected stream is used for model GPU work. The unselected complementary context is idle. This is one specific implementation, not a universal Green Context performance limit.

Actual selected SM counts, stream owner and native SM-ID samples are saved. The observed sample sets can be disjoint; **cross-process global physical ownership/isolation is not guaranteed by that observation**. Other GPU resources, especially memory and scheduling, are not partitioned by this experiment.

Pilot separate actual ROS requests under profiled Nodes atQ16/Y32 record the third request after two warmups. Nsight CUDA/NVTX validates actual request model kernels' nonzero greenContextId. The pilot proves request-path binding, **not simultaneous GPU kernel overlap**: capture timing and scopes are not an overlap experiment. Profiled request latencies are excluded from the comparison.

The main controller uses nonprofiled copies. Selected-stream assertions run before each request's GPU inference. CUDA13 primary-context synchronization also includes its Green contexts; original stock calls remain. Each request audits expected SM/input512/output128/hash at the client.

## Files and execution
- `generate.py`: copied nodes and atomic-template overlay construction; no frozen source edits.
- `prepare_sources.py`: generate separate qwen/yolo normal/profile files and a small fixed-corpus copy of the existing benchmark.
- `prepare_workload.py`: CPU-only tokenizer round-trip against prior SM manifest; no model inference or library patch.
- `launch_profile.sh`: lifecycle-safe profiled child with no-kill mode and readiness PID cleanup. `runner.py` flushes sessions if necessary and verifies reports before replacement; return codes alone do not substitute for trace validation.
- `runner.py`: Spark-native orchestration, real live logs before traffic, exact template/replica restore in finally, actual domain42 ROS health. Handles TERM/HUP; SIGKILL or host failure bypasses finally and needs manual backup restoration.
- `controller.py`: local SSH owner and fail-open Korean Slack alerts; no secret copied remotely.
- `analyze.py`: paired E2E/generate/inference/queue changes and absolute values; +/-5% descriptive band is **not statistical equivalence or an SLO**. A smaller slowdown ratio does not mean better absolute performance when the solo baseline itself is slower.
- `audit.py`: raw UUID/status/work/resource and post-response publication coverage without rewriting original files.
- `plot.py`: CPU-only existing Matplotlib/Numpy, E2E and internal-stage comparison PNG/SVG. No new packages required.

Spark workspace `/home/avees/cj-green-e2e/20261109-v1`, sources/src, backups/backup, workload.json, results, metadata, validation, verification, logs and plots. Source snapshots are authoritative: canonical formatting was cleaned separately after launching, with no remote runtime changes.

For replay, use a new workspace/output labels, never overwrite prior results. Back up actual original deployments first. Set `GREEN_E2E_ROOT` on local controller and the remote launch shell, source native ROS setup, then run the local controller. The remote runner owns Kubernetes changes and rollback. Both baseline images already contain all frameworks; copy the existing architecture-matching native bridge plus its exact source and checksum. Profile/export tools must match the collection image version.

## Interpretation
- E2E near equality does not prove GPU parallel execution. Conversely, higher delay is observed interference, but alone cannot identify CUDA context serialization vs memory bandwidth/cache/dispatch effects.
- Reliable per-request endpoints have known handshake tails. A lower concurrent p95/mean can mask a worse GPU stage; compare internal timings, queue and publication ACK data as well.
- Counts differ between solo and concurrent CV; changed achieved CV rates can change LLM pressure. No multi-user open-loop capacity/high-availability/SLO/energy/memory-isolation claim.
- All failures, available logs and raw response timings are preserved. Original source/images/weights/plugin policies remain unchanged and original domain42 deployments are restored after completion.
