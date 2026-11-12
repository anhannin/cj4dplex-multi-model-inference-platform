# Green Context partition E2E: paired solo-active vs concurrent

**Goal:** Measure real ROS2 request E2E under each Qwen/YOLO Green SM split, compared with the same configured services when only one workload is requested. No inference from synthetic arithmetic or standalone GPU-only plots.
**Approval:** User explicitly approved comparing partition combinations and solo/concurrent E2E following the real-model SM curves. Five complementary splits Qwen/YOLO8/40,16/32,24/24,32/16,40/8, plus fresh unpartitioned default48/48 control.

## Fixed contract before measurements
- Same frozen Qwen3.5-9B BF16/SDPA/native FLA + YOLO26l native Torch FP16, imgsz640,batch1,rect=False. No MPS/TensorRT/DDS tuning or graph optimization.
- Real independent ROS queues/workers in separate original-image Kubernetes Deployments, replicas1 each. Experimental node copies only: wrap unchanged worker lifetime in selected Torch ExternalStream; reuse existing CUDA13 GreenPair split. Both processes split the same full resource by YOLO's requested size, YOLO selects part0 and Qwen part1. Check actual counts, stream owner, sampled SM-ID sets. Empirical disjoint sampling is not a global reservation guarantee.
- Both models resident in ALL conditions. Solo means one model gets requests while the other is idle, NOT absent. Original SM-sweep removed the other model and excluded ROS; its CUDA spans are not comparable directly to this E2E.
- Fixed natural prompt whose normal original tokenizer/chat template yields512 tokens; compare actual input ID SHA to prior sweep where possible. Force128 output tokens with stock min_new_tokens=max_new_tokens=128 in experimental copies only. Fixed bus.jpg. Same corpus/precision/token and message protocol in all phases including unpartitioned control.
- Temporary ROS domain73 for isolated experimental requests, localhost discovery, same UUID result topics/reliable ACK/FIFO8. Original domain42 services are restored after the experiment. Existing templates/images/source/weights/plugin policy remain frozen.
- Each configuration: Qwen-only10 measured requests, YOLO-only300, both Qwen10 with YOLO continuously issuing C1 until Qwen ends. Warmup3/model each phase. Adaptive closed-loop C1/workload, NOT fixed offered rate. Preserve actual achieved rate and counts. Small-N Qwen p95 descriptive only.
- E2E before client JSON encoding/publish to matching response parsed; image file read/decode/base64 preparation, initial discovery and result visualization excluded as original benchmark. Retain inference/generate wall, server TTFT,TPOT,queue/processing and publication ACK logs. No summing nested spans/p95.
- Report concurrent/solo-active ratio per model/config. +/-5% of SOLO mean is a predeclared practical descriptive near-equality band, NOT statistical equivalence/SLO. Faster CV E2E alone can mask GPU slowdown through DDS handshake effects; compare inference and queue/transport components too. Similar E2E is not proof of GPU kernel overlap.
- Pilot actual ROS requests under Green at Qwen16/YOLO32: stream check each request and separate Nsight capture for third request after two warmups, validate actual ROI kernels' nonzero greenContextId. Profiled timings excluded. No claim of physical partition exclusivity or simultaneous GPU execution from response times alone.
- Capture server logs live before traffic to avoid known kubelet rotation loss; audit UUID/event coverage. Save all failures, backups, actual templates/pods and resource metadata. Restore exact original templates/replicas and native domain42 E2E health in finally.

## Execution
1. Tests first for generation/wrapper, complement indices, reversible templates and ratio classification.
2. Prepare exact512-token request text offline with stock tokenizer; archive token IDs and source/image/native-binary hashes.
3. Render separate qwen/yolo experiment node copies, no framework patches. Pilot resource correctness and actual-kernel Green coverage, flush/export before replacing profiled Pods.
4. Fresh default control and five splits, serialized phase runs, stable warmup and no simultaneous unrelated GPU jobs. First split16/32 to test the strongest initial candidate, then24/24,32/16,8/40,40/8.
5. Analyze per-model mean/p95/inference/queue/throughput and slowdown ratios. Plot solo-active vs concurrent means for each partition; caveat counts/rate/uncertainty. If nothing improves, report that, not an assumed Green win.
6. Copy raw data/plots/report and verify hashes/tests/frozen baseline identity/restoration. No external push or permanent deployment promotion.
