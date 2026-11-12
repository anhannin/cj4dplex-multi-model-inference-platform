# Actual concurrent GPU kernel timeline verification

**Goal:** Determine whether actual Qwen/YOLO kernels overlap on GB10 under separate two-Pod Green Q16/Y32, not infer this from host inference windows or E2E. Also capture default full-GPU two-Pod reference and a same-process two-Green synthetic positive control for the overlap analyzer only.
**Approval:** User explicitly requested checking the GPU timeline after learning worker intervals overlap but kernel concurrency is unproven. This is diagnostic profiling, not another performance optimization sweep.

## Fixed design / gates
- Frozen original model images/weights/code; diagnostic burst-node copies only. Same actual512input/128forced output, fixedbus640b1. Same independent queuesQ16/Y512,DDS512,temporary domain76. No MPS, driver/security/clock settings or model framework patches.
- Existing Q16/Y32 GreenPair selected streams and default48/48 code path. Both services resident, no solo workloads. Warmup simultaneousQ3/Y30 then capture actual simultaneous finiteQ10/Y300 as prior protocol.
- Both profilers start from worker idle file gate AFTER warmup. Wait for both start markers before submitting burst. Client writes actual barrier t0 to controller-visible file. Remove gate t0+20s; each worker stops at a request boundary (Q may capture longer). Analyze only common capture intersection and actual burst window. Wait for all310 results and drain before replacing Pods.
- Nsight SystemsCUDA/NVTX trace only, CPU sampling/context switches disabled, no added cross-model synchronization. Per-request NVTX scopes through selected-stream completion.
- Export SQLite using installed same Nsight version, normalized UTC for cross-check. Do NOT simply assume two report-local zero points match. Add CPU-only NVTX clock marks bracketed by host CLOCK_MONOTONIC perf_counter_ns and wall_ns in each process. Record namespace/clock/offset identity. Align report GPU and CPU timestamps to common host monotonic via validated anchors; quantify residuals/bracket uncertainty and test sensitivity to additional1/10/100us tolerances. Profiled wall timings are NOT pooled with prior unprofiled metrics.
- Validate actual model ROI kernel greenContextIds on Green case, default IDs on noGreen. Correlate/contain kernels in per-request scopes; preserve missing/lost-record warnings and invalid crossing events, never hide them.
- Compute per-model kernel union (not sum of nested/overlapping kernels), cross-union overlap, overlap fraction per model, counts/durations, CPU model-window overlap separately. Distinguish observable kernel interval concurrency from actual simultaneous SM instruction issue/occupancy; kernel intervals can include stalls/preemption. Never claim universal GPU serialization from a finite sample.
- Synthetic positive control: same process two known Green streams launch preallocated fixed-work kernels on different partitions simultaneously; profiler must show meaningful overlapping kernel intervals. This validates analysis/tool capability only, NOT actual-model performance or work equivalence between different SM counts.
- Plot common-time actual kernel occupancy overview plus short microsecond-scale zoom, CPU model-call windows and clock alignment evidence. No E2E gain claim or unsupported causal leap to memory saturation.
- Host controller serialized, bounded stages, live logs, preserve failures, exact original template/replica/domain42 restoration and real native ROS health in finally. All old datasets untouched; no external push.

## Execution
1. Unit tests first for interval union/intersection, uncertain-overlap bounds, anchor-clock fitting and source instrumentation (no per-token/global barriers).
2. Prepare diagnostic sources/file-gated profilers and positive-control harness, validate source/runtime prereqs BEFORE deployment.
3. Capture Q16/Y32 actual two-Pod early burst plus unpartitioned reference; validate complete310 responses and both captures; export reports/anchors.
4. Analyze common timeline with clock-error bounds and positive control; inspect plots; report whether kernel overlap is observed and scope/remaining unknowns.
5. Restore/source+image+baseline hash audits, fresh tests/lint, raw archive integrity and local report/PNG/SVG.
