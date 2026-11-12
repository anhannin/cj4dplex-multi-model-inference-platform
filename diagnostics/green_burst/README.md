# Fixed simultaneous burst: Green before/after only

This protocol explicitly excludes solo-active trials. Every measured batch submits Qwen10 and YOLO300 without response-gated pacing. All configs use the same workload, buffers and instrumentation. It is not the earlier C1 continuous-traffic experiment.

## Semantics
- Common barrier t0 releases two publisher threads; each records actual JSON-encoding/publish start/return. All310 UUID result subscriptions are prepared before t0; subscriber discovery/settle and input file/base64 preparation excluded. Dispatch spread is measured, not assumed instantaneous.
- Main3 bursts per split, controls3 before+3 after. Warmup is ALSO a simultaneous Q3/Y30 burst. New client process per burst destroys transient history; fully drain/ACK settle before next trial.
- Qwen512 input token IDs exactly match prior SHA, stock greedy min_new_tokens=max_new_tokens=128/cache=True. YOLO fixed bus.jpg/640/batch1/rectFalse/nativeTorchFP16. Qwen9B BF16 SDPA/native FLA. No MPS/TRT/DDS latency tuning/explicit graph optimization.
- Same queue and DDS capacity changes for ordinary full-GPU control and every Green split: appQ16/Y512, request publishers/subscribers reliable transient-local depth512. These changes permit this NEW burst workload, not a Green-specific advantage. Request UUID/result topics and independent worker/FIFO semantics retained.
- Finite completion is only valid when all10+300 unique correlated responses succeed. Missing, duplicate, wrong input/resource/shape or queue overflow invalidates a run; lower completion caused by dropped work is never a win.
- Batch model completion and overall makespan are measured from common t0. Per-request E2E uses actual request send time. Neither is the mean of the other.

## Components
- AppQueue: callback/enqueue to worker dequeue, server-local duration. Precallback DDS backlog/publisher blocking is NOT app Queue.
- Pipeline host wall: stock generate()/predict() through selected-stream completion; records CPU dispatch and GPU waiting as part of model response latency.
- GPU forward/device span: preinitialized CUDA events on actual native Module.forward on selected stream. Qwen512 prefill+127 one-token decode; YOLO1 native1x3x640x640 forward. No added per-token synchronization. This can include GPU scheduling/dispatch gaps, NOT pure SM busy time. GPU span is nested in pipeline wall, NOT added again to E2E.
- Additive accounting: E2E = appQueue + pipeline wall + (serverProcessing-pipelineWall) + (E2E-appQueue-serverProcessing). Do not clamp negative residuals: audit/flag them. ACK wait may occur after the current response and delay later jobs via worker queue; do not blindly add it to that request E2E.
- Host/container perf_counter implementation/time namespace/offset equality is checked before cross-process host pipeline timeline analysis. GPU overlap is not inferred from host timestamps or device durations.

## Ranking
Primary strict fastest = lowest mean whole310-job makespan. Descriptive predeclared practical tie set = within3% of fastest mean; within that set select lowest YOLO300 completion, then total. This is NOT statistical equivalence/SLO. Show all candidates/Pareto tradeoffs, before/after control drift,3 repeats and SD/range. If noGreen wins the balanced rule, say so.

Because CV300 may finish early, last Qwen jobs can run without any remaining CV inference. Record the number of Qwen pipelines starting after final CV model-end. Similar overall makespan does not prove sustained interference isolation or GPU kernel concurrency.

## Code / lifecycle
- `generate.py`: builds on the previously request-path-verified Green wrapper; source copies use existing CUDA13 GreenPair, Qpart1/Ypart0. Two Green objects per process, only selected stream computes. Native counts/owner/sample IDs checked; no global exclusive physical-SM reservation guarantee.
- `gpu_observer.py` and `stage_metrics.py` runtime copies are the previously actual-model-tested SM-sweep ForwardTimer and strict phase checks. Events preinitialized before readiness, observer removed before Green destruction.
- `client.py`: one fixed simultaneous burst; writes raw/final canonical rows, common-origin completion, dispatch spread and failure/missing IDs. Spins responses while publishers issue remaining jobs.
- `runner.py`: original two K8s deployments temporarily switched to domain74 experimental copies; warm+3 measured bursts/config. Exact template/replica/domain42 restore and real ROS health in finally. TERM/HUP handled; SIGKILL/host loss requires manual restore from backup.
- `analyze.py`/`plot.py`: completed audited runs only, CPU-only existing Matplotlib. Components and GPU submetrics visualized separately; no solo ratios.
- `audit.py`: input/output/shape/resource/clock/accounting and full live publication coverage; masks are verified resource allocations, not global GPU isolation claims.
- Initial source-preparation invocation needed repo-root import path; its failed launch evidence is preserved. No measured burst ran before generated sources existed. Startup-only rollback/recreate events are not steady-state sample failures. No SDK/environment/model code patch was used.

## Reproduce
Use a NEW output workspace with `src,backup,metadata,results,warmup,logs,verification,plots,analysis`. Capture original live deployments before patching. Generate two node files locally with `prepare.py --repo <repo> --output <freshdir>`; copy helpers/native architecture-matching bridge, original workload.json and exact source hashes. `base_generate.py` is the earlier Green E2E generator, `gpu_observer.py`/`stage_metrics.py` from SM sweep, `live_logs.py` from optimization. Frozen images/whole HFhub and assets remain mounted read-only as before.

Launch local `GREEN_BURST_ROOT=/home/avees/cj-green-burst/NEW .venv/bin/python -u diagnostics/green_burst/controller.py`. Validate all runtime files exist/compile BEFORE deployment; never run unrelated GPU jobs concurrently. Follow remote logs/controller-status. After PASS/restoration, run audit/analyze and CPU-only runc Docker plot; copy archives/checksums and inspect PNGs. Keep failed attempts; never overwrite prior sample directories. Do not directly compare burst numbers with historical C1 or standalone GPU curves.
