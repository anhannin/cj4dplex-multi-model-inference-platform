# Actual-model Green Context SM sweep

Purpose: reproduce the *method* of the supplied pi0 SM-sensitivity plots with the project's actual Qwen3.5-9B / YOLO26l, not synthetic FMA workloads and not a concurrency/E2E result.

## Fixed workload and measurements
- GB10:48 SM; CUDA13 resource query reports minimum8/alignment8. Points8/16/24/32/40/48 are all real Green Context allocations (including48), with independent ordinary primary-context full-GPU references.
- Qwen: batch1,512 exact GPU input token IDs including chat prefix/suffix; stock greedy generate(), min_new_tokens=max_new_tokens=128, use_cache=True, BF16/SDPA and frozen native FLA/causal-conv dispatch. Fixed-length generation deliberately suppresses early EOS to preserve work. No semantic accuracy or byte-exact output guarantee.
- First root forward must see512 tokens (prefill), next127 forwards exactly1 token each (decode). Device events bracket each native forward; events preinitialized outside timing; read after generation completes. No added per-token synchronization. Device spans may include GPU-idle/CPU-dispatch gaps, not pure kernel active time. Decode statistics use **30 per-generation averages**, not3810 independent token samples.
- Original frozen TokenClock measures generate first-token callback and wall TPOT. Whole generate() wall ends after selected-stream completion. These are not ROS/API E2E/queue timings or client streaming TTFT.
- YOLO: native Torch CUDA FP16, fixed decoded bus.jpg, batch1/640×640/rect=False. Hook underlying stock model.forward, plus full predict() wall through selected-stream completion. Image read/decode and drawing/saving excluded. Native CUDA/FP16 checked. Count/classes plus matched IoU>=.98 and confidence delta<=.02 checked against ordinary full-GPU reference.
- Qwen30 samples/SM (two rounds15), YOLO100/SM (two rounds50). Each point/round warmup3 or10 excluded but preserved. Seeded order `[24,40,48,32,8,16]`, then reverse. Full default references5 Qwen /50 YOLO before and after, separately stored. No CUDA Graph optimization, MPS or TensorRT; no framework code patches, GPU clock lock or global policy changes.
- User reference chart is RTX5090/CUDA Graph ON/different models and inputs. Absolute numbers are **not comparable**.

## Implementation and evidence
- `green_sweep.cu` / `build.sh`: new single-Green pybind adapter, full48 supported explicitly. Does not modify archived GreenPair probe. Verifies actual resource count/stream owner and samples SM IDs; sampled IDs are not GPU activity/occupancy measurements or cross-process isolation guarantees.
- `observer.py`: original Module hooks and CUDA events only; no model-forward replacement.
- `dispatch.py`: exactly the original Qwen node's closure-selected native implementation check (not dispatcher wrapper.__module__). Initial v1 preflight used the wrong wrapper property; its failure and successful rollback are preserved, v2 corrects only the diagnostic guard with a regression test.
- `run_model.py`: stock generate()/predict(), strict token/shape/forward count, raw sample files and default references. Green objects survive until model tensors/events are released and CUDA cache emptied.
- `verify_trace.py`: independent Nsight Systems CUPTI greenContextId check for the actual min/max resource model ROIs. Profiling data is **never pooled into main latency results**. At8/48: YOLO845 kernels/ROI; Qwen251766 kernels/ROI; all nonzero Green IDs. Middle points have the same adapter plus per-forward PyTorch stream check and native resource sampling; not independently traced.
- `controller.py`: local owner, SSH to Spark, backs/restores saved templates/replicas, temporarily quiesces original services, serialized one-model containers, bounded timeouts, cleanup and real native ROS health after restore. Local Slack env used fail-open, no credential copy. `CJ_SM_SWEEP_ROOT` chooses a fresh archived output workspace. **Do not reuse existing output dirs or run GPU jobs concurrently.**
- `plot_results.py`: existing Matplotlib in frozen YOLO image (CPU-only Docker `--runtime=runc`); PNG/SVG figures, CSV and analysis from completed main runs only. Error bars are descriptive population SD, not CI. The "within10%" resource heuristic is descriptive, **not an SLO**.

## Reproduction skeleton (this Spark)

1. Create a new workspace with `src,backup,results,validation,verification,plots,logs,cache`. Save actual original `kubectl get deployment {qwen,yolo} -o json` under backup before applying any changes. Retain whole read-only HF hub mount and original assets.
2. Copy sources; CPU-only build using frozen Qwen ROS image:
   `docker run --rm --runtime runc --network none --user 1000:1000 -v "$R:/experiment" --entrypoint bash cj-qwen-ros:9b-timing-v1 /experiment/src/build.sh`
3. Run native smoke with GPU (8 and48 event/resource checks), outside measured traffic. Ensure no MPS/other inference jobs.
4. From repo on the local host, source local Slack environment quietly if used and run:
   `CJ_SM_SWEEP_ROOT=/home/avees/cj-sm-sweep/NEW_RUN .venv/bin/python -u diagnostics/sm_sweep/controller.py`
5. After PASS and successful original-service restore, generate plots CPU-only:
   `docker run --rm --runtime runc --network none --user 1000:1000 -e HOME=/tmp -e PYTHONPATH=/experiment/src -v "$R:/experiment" --entrypoint python cj-yolo-ros:26l-timing-v1 /experiment/src/plot_results.py --root /experiment`
6. Inspect raw counts, token hash, stream/resources, per-round drift, reference pre/post drift and source/image hashes. Preserve failed attempts. If killed with SIGKILL/host failure, `finally` cannot restore; manually restore exact saved templates and replica counts, verify actual ROS replies.

## Official/version-specific references
- CUDA13 Green resources/streams: https://docs.nvidia.com/cuda/archive/13.0.0/cuda-driver-api/group__CUDA__GREEN__CONTEXTS.html
- CUDA13 primary-context synchronization: https://docs.nvidia.com/cuda/archive/13.0.0/cuda-driver-api/group__CUDA__CTX.html (primary synchronization includes its Green contexts; harness uses selected-stream completion explicitly).
- PyTorch2.9 CUDA event timing: https://docs.pytorch.org/docs/2.9/generated/torch.cuda.Event.html and stream wrapper https://docs.pytorch.org/docs/2.9/generated/torch.cuda.ExternalStream.html . Installed native Torch2.9+NVIDIA build is also directly exercised by smoke/model pilots.

## Interpretation boundaries
A standalone curve answers how sensitive this specific model/stage/input is to its eligible SM resources. It does not establish simultaneous two-Pod execution, global exclusive physical-SM partitioning, combined E2E improvement, business SLO, memory/DRAM saturation or energy efficiency. Ordinary desktop contexts are not disabled. Clock/power/temperature snapshots are recorded; clocks are not fixed. Further concurrency/serving tests are a separate next step.
