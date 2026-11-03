# Five-condition baseline protocol — 2026-11-03

Status: COMPLETE, all five conditions PASS. Results recorded in
results/latency-baseline/comparison.csv and results/latency-baseline/README.ko.md.

## Controlled conditions
One Spark GB10, namespace cj-inference. Recreate Deployments replicas0/1 as condition
requires. Device-plugin shared2; no MPS/Green Context/SM partition/priority changes.
Existing BF16 Qwen3.5-9B / FP16 YOLO26l settings retained. No hard CPU/RAM caps.
Public fixed prompt/image corpus, greedy Qwen max_new_tokens128, output/EOS recorded.
No inference framework/library source patch. New images:
cj-qwen-ros:9b-timing-v1 and cj-yolo-ros:26l-timing-v1.

## Workload and sequence
1. Qwen Pod only, 30 measured requests.
2. YOLO Pod only, 300 measured requests.
3. Both Pods resident, Qwen only, 30 requests.
4. Both Pods resident, YOLO only, 300 requests.
5. Both active, Qwen30, independent sequential YOLO requests until Qwen finishes,
   at least30 YOLO requests. Measure each workload's own start/end interval.

Each condition excludes 5 warmup requests per active model. First Qwen compilation
and Pod model loading are not measured as steady-state request latency.
Initial overhead pilot: six counterbalanced basic/tokens pairs (64 output cap),
five warmups. Token mode selected only if median paired generation overhead <=5%;
verify identical generated text and observed output token count for every pair.
The selected mode is fixed for all five conditions.

The client keeps one ROS participant alive and at most one outstanding request/model.
This is a closed-loop test, NOT fixed offered arrival rate, overload/SLO testing or a
high-concurrency queue stress test. New per-UUID response publishers still exist,
so their discovery/delivery/ACK overhead remains part of the service behavior.

## Reporting rules
Preserve requests.jsonl and server logs, join by request_id, retain warmup flags.
Successful-request mean/linear p50/p95/p99 with N, failed-attempt denominator,
throughput from real window, Qwen input/output tokens and token throughput.
Server TTFT != client TTFT; generate wall != pure GPU; TTFT != prefill.
YOLO predictor inference from result.speed != full predict wall != E2E.
ACK duration may end after client response, so it is not an additive E2E component.
Joined residual != pure network latency. Unsupported GPU memory values stay N/A.

Single ordered pass; limited Qwen N30, short YOLO-only windows, no frequency lock,
no thermal steady-state proof and no run-order randomization. Host util/temperature/
power/memory available sampling is diagnostic only. No statistical significance or
causal GPU-SM bottleneck conclusion is justified solely by this first pass.
Standalone conditions have the other model Pod actually removed, not merely idle.

## Completion
All five manifests PASS; all attempted requests accounted for, actual Pod counts
and no unexpected restarts verified; raw records downloaded; summaries regenerated.
Both model Deployments left replicas1 Ready. Existing Docker model containers stay
stopped/preserved for rollback. Functional UUID and annotated-image clients rechecked.
