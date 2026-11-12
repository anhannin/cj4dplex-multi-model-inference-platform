# Reversible optimization sweep

Frozen baseline source/manifests/images remain untouched. Plan and evaluator:
`docs/plans/2026-11-04-optimization-sweep.md`. Server workspace:
`~/cj-optimization/20261104-v1`.

`run_sweep.py` runs on Spark after sourcing native ROS2 setup. It backs comparisons with actual template snapshots, raw request records and server logs; restores saved baseline templates in `finally`. Backups must be created from live deployments before first use. Never run multiple sweep/export/profiling jobs concurrently on this GPU. SIGKILL/host loss bypasses Python finally; recover by patching each saved `spec.template` using candidate `control` (do not apply stale resourceVersion/status from full object).

Candidates: unchanged control; fast-core affinity Qwen5–9/YOLO15–19 (actual sysfs max3900MHz, not a portable CPU-ID mapping); uncapped MPS; Qwen MPS75%/50% withYOLO100%; reliable DDS initial heartbeat/ACK timing; stock YOLO TensorRT FP16. MPS client caps are limits, not exclusive SM reservations. No kubelet CPU manager, driver security policy, GPU clock, GPU compute mode, original image or weight changes.

Results are adaptive closed-loop C1/workload, not fixed external offered traffic. A faster CV backend also increases CV offered pressure; compare achieved rates and paced confirmation where relevant. Statistical claims must reflect sample count.

## Reproduce a candidate on this Spark

Prerequisites are the frozen Kubernetes baseline, original local images/weights, and native ROS2 environment already documented in the main README. Workspace layout is `~/cj-optimization/20261104-v1/{backup,config,src,results,engine,mps-pipe,mps-log}`. `backup/{qwen,yolo}.json` contain the original full live Deployment objects; never overwrite those after applying a candidate.

1. Copy this directory's Python scripts into `src/`, and `low-latency.xml` into `config/`. Generate `src/yolo_trt_node.py` locally with `prepare_trt_node.py --output <new-path>`, preserving frozen `ros2/yolo_node.py`. Check actual installed backend `.format` and binding dtype; do not use the old `.engine` flag.
2. If TensorRT is selected, export only outside serving measurements. The `export_after_sweep.sh` Docker command shows mounts, UID, network isolation and environment. Run `export_trt.py`, then `quality_trt.py`; gate on `trt-quality.json` and retain engine hash. This is FP16-enabled TensorRT with FP32 I/O on the installed exporter, not all-FP16 execution. Do not run the scheduler wrappers if another unrelated GPU test is active.
3. For MPS, create private owner-only directories and start the **installed CUDA13 legacy** daemon as the same UID1000 as the Pods:
   ```bash
   R=$HOME/cj-optimization/20261104-v1
   chmod 700 "$R/mps-pipe" "$R/mps-log"
   CUDA_MPS_PIPE_DIRECTORY="$R/mps-pipe" CUDA_MPS_LOG_DIRECTORY="$R/mps-log" nvidia-cuda-mps-control -d
   ```
   First check that this private daemon is not already running; do not start/stop unrelated MPS controllers. `probe_mps.sh` and `mps_caps_probe.py` record actual membership and effective context SM counts.
4. Run one serialized comparison, with a new prefix (existing result directories are never overwritten):
   ```bash
   source ~/.config/cj-ros2/spark-jazzy.bash
   python3 "$R/src/run_sweep.py" control trt-dds-mps-q50 --samples 30 --warmup 5 --prefix replay-UNIQUE
   ```
   `--cv-rate 20` selects the separate paced-C1 protocol. It is a ceiling, not an open-loop fixed-rate generator. Do not pool its results with uncapped C1.
5. The runner restores original complete templates in `finally` using atomic JSON Patch. On SIGKILL/host loss this cannot run; manually call `apply('control')` from `src/run_sweep.py`, compare actual `spec.template` with the backup, and verify real E2E requests. Ready-files alone are insufficient.
6. After MPS clients have exited and both original Pods are restored, inspect private `get_server_list` / each `get_client_list`; only when empty send `quit` to **this private** controller. The runner does not silently shut down an unknown daemon.

`compare.py` emits descriptive per-run CSV; `pool_results.py` rejects duplicate UUIDs/protocol mismatch; `audit_results.py` checks UUIDs, token budget, input contract, response status and publication-log coverage without rewriting raw requests. `final_confirmation.py` records independent fresh controls and the selected combination, including a paced20/s ceiling check. Scheduler shell scripts in this directory describe this run's sequencing, not a general Kubernetes production controller.

## Scope and operational tradeoffs

- MPS limits are not exclusive SM/memory reservations. A shared daemon adds lifecycle/failure-domain concerns; supervision/recovery is not implemented by this experimental runner.
- The framework's actual `predict()`/`generate()` code is unmodified. Only the candidate YOLO node's backend-specific startup assertion is adapted for TensorRT, covered by regression tests; the complete inference/queue/publication body is byte-identical to frozen serving code.
- Two-image TensorRT fidelity smoke (counts/classes/IoU/confidence) is not a dataset accuracy evaluation. Qwen weights/precision/token budget stay fixed; greedy output bytes can differ across restarts even without a backend change.
- Green Context functional capability and synthetic MPS concurrency are separate from production serving latency and global physical SM reservation. Those latter properties are not validated here. No Green serving node replaces the baseline.
- No business SLO is invented. Results cover local native ROS2 clients, C1 per model, one GB10, the fixed corpus and128-token budget; they do not prove multi-user open-loop capacity, LAN latency, OOM recovery, high availability or energy efficiency.

DDS client scope matters: reproducing the short-result tail improvement requires the reader profile on requesting clients, not just the two servers. For a native manual client, use `FASTRTPS_DEFAULT_PROFILES_FILE="$R/config/low-latency.xml" python3 <request-client.py> ...`. This experiment does not change the host's global ROS2 profile or silently change every user's middleware defaults.
