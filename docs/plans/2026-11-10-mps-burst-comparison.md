# Parallel two-model serving: fixed simultaneous burst comparison

User approved the comparison design. This is a finite measurement sweep, not model/framework optimization or a new goal workflow.

## Contract
- Conditions: fresh no-MPS/no-Green control, MPS-only full48/48, MPS+Green Q/Y8/40,16/32,24/24,32/16,40/8.
- Five randomized complete blocks (seed20261110), every condition once per round. Each block entry reloads both models, warms simultaneouslyQ3/Y30, then measured simultaneousQ10/Y300; no solo requests. 35 measured bursts +35 warmups; total12,005 validated responses.
- Same frozen images, baseline application source, native BF16 Qwen9B/SDPA/FLA, FP16 native YOLO26l, exact512input/128forcedoutput, samebus640/b1. Same diagnostic forward-event instrumentation on ALL conditions, same FIFO Q16/Y512, DDS512, domain74. No Nsight in timed runs.
- Preserve existing production templates (MPS+Green,domain42) separately from frozen no-optimization templates used to construct test cases. Keep existing same-UID production MPS service running; no-MPS control must have ZERO connected clients, MPS cases exactlyTWO matching actual host model PIDs. No active-thread percentage env/cap. After each full drain, change condition.
- Inputs/helpers/binary/image/source/hash/import and workload checks BEFORE changing Pods. Maintain exclusive owner lock and PID, live full publication logs, 1Hz lightweight host/GPU sampling, deadlines, fail-open Korean Slack alerts. Finally restore exact production templates/replicas, check same2-client membership and actual native ROS health.
- Expected wall budget ~3hours because complete blocks reload Qwen35times. Temporary normal domain42 service unavailability is part of approved measurements; restore on success/failure/interruption.

## Outputs / evaluation
- Per-trial/model makespan from common burst release, requestE2E/queue/pipeline/hostresidual distributions, Qprefill/decode/TTFT/TPOT and YOLOCUDA-forward/pre/post, allrequest/logfailures. CUDAEvent forward span includes launch/stall effects; nested inside pipeline, not pure active GPU time or additive E2E component.
- Independent input/token/shape/source/UUID/count/timestamp/component/log/ACK audit. Exactly5 valid repetitions each; preserve failed runs, do not silently replace or pool old/profiler data.
- Strict fastest mean total makespan; predefined3% descriptive tie band then fastestYOLOcompletion among near-total ties. Also report Pareto, per-round MPS-only vscontrol and eachGreen vsMPS-only changes, observed dispersion, raw5repetitions. No significance/SLO claims from5trials. Sensitivity/tie-band0/1/3/5%.
- Separate representative finalist Nsight validation after measurements (never add it to timings). Validate actual2client attachment, kernelGreenIDs forGreen and noGreen forMPS-only, no-switch overlap and clock tolerances using existing tested profiler pipeline. Selection is workload-specific; no global exclusive SM reservation claim.
- Local report/CSV/plots/rawartifacts andchecksums. Frozen baseline/sourceimages/previousresults unchanged. No Git push.

## Implementation
1. Tests first for7condition schedule, determinism/completeness, immutabletemplate MPS toggle/noquota/queues/domain and modevalidatedmembership.
2. New bounded runner wraps existing burst apply/batch/restore helpers, using separate baselinetemplates and savedproduction backups. Copy existing generated native nodes/metrics/client; no added framework/library dependencies.
3. Preflight then launch isolated detached runner; monitor statuses/alerts and execute all35trials.
4. Reuse validated per-trial analysis math, generalize grouping via explicit schedule (not name regex), independent audit via schedule, aggregate/plot.
5. Profile finalist(s) separately, restore production, tests/hash audit and final recommendation.
