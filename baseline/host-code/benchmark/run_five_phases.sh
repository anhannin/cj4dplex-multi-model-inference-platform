#!/usr/bin/env bash
# Spark-only controller. Existing Docker model containers remain stopped.
set -eo pipefail
source "$HOME/.config/cj-ros2/spark-jazzy.bash"
export PYTHONUNBUFFERED=1
root="$HOME/cj-latency"
src="$HOME/cj-ros2"
mkdir -p "$root/phases" "$root/evidence"
cd "$src"
monitor=""
cleanup() {
  if [[ -n "$monitor" ]]; then kill "$monitor" 2>/dev/null || true; wait "$monitor" 2>/dev/null || true; monitor=""; fi
}
on_exit() {
  local code=$?
  cleanup
  if [[ "$code" != 0 ]]; then echo "FAIL exit=$code" > "$root/evidence/five-phases-status.txt"; fi
}
trap on_exit EXIT
snapshot() {
    local phase="$1"
    kubectl -n cj-inference get pods -o json > "$root/phases/$phase/pods.json"
    kubectl -n cj-inference get deployments -o json > "$root/phases/$phase/deployments.json"
    nvidia-smi > "$root/phases/$phase/nvidia-smi.txt"
}
state() {
    local q="$1" y="$2"
    echo "$(date -Is) desired replicas: qwen=$q yolo=$y"
    kubectl -n cj-inference scale deployment/qwen --replicas="$q"
    kubectl -n cj-inference scale deployment/yolo --replicas="$y"
    for model in qwen yolo; do
        local want="$q"; [[ "$model" == yolo ]] && want="$y"
        if [[ "$want" == 0 ]]; then
            kubectl -n cj-inference wait --for=delete pod -l app="$model" --timeout=360s
        else
            kubectl -n cj-inference rollout status deployment/"$model" --timeout=660s
        fi
    done
}
run() {
    local phase="$1" models="$2" n="$3" mode="$4" tokens="$5"
    echo "$(date -Is) START $phase"
    python3 benchmark/bench_ros2.py --models "$models" --output "$root/phases/$phase"        --samples "$n" --warmup 5 --timing-mode "$mode" --max-new-tokens "$tokens" > "$root/evidence/$phase.log" 2>&1 &
    local bench=$!
    # Wait for bench to create its new output directory.
    for i in $(seq 1 100); do
        [[ -d "$root/phases/$phase" ]] && break
        kill -0 "$bench" 2>/dev/null || break
        sleep .1
    done
    if [[ -d "$root/phases/$phase" ]]; then
        python3 benchmark/monitor_host.py --output "$root/phases/$phase/host-metrics.jsonl" &
        monitor=$!
    fi
    local code=0
    wait "$bench" || code=$?
    cleanup
    sleep 1
    snapshot "$phase"
    for model in qwen yolo; do
        if kubectl -n cj-inference get pod -l app="$model" -o name | grep -q .; then
            kubectl -n cj-inference logs deployment/"$model" > "$root/phases/$phase/$model-server.log"
        fi
    done
    python3 benchmark/join_server_timings.py "$root/phases/$phase" > "$root/evidence/$phase-summary.log"
    cat "$root/evidence/$phase.log"
    [[ "$code" == 0 ]] || return "$code"
    echo "$(date -Is) PASS $phase"
}
kubectl -n cj-inference get deployments -o json > "$root/evidence/deployments-before.json"
kubectl get node spark-e6d6 -o json > "$root/evidence/node-config.json"
# Recreate and actual removal before changing images; never run duplicate model subscribers.
state 0 0
kubectl -n cj-inference set image deployment/qwen qwen=docker.io/library/cj-qwen-ros:9b-timing-v1
kubectl -n cj-inference set image deployment/yolo yolo=docker.io/library/cj-yolo-ros:26l-timing-v1
state 1 0
# Verify real queue behavior and client functionality in later both-model smoke.
run overhead-qwen qwen 12 alternating 64
python3 - "$root" <<'PY'
import json,statistics,sys
from pathlib import Path
root=Path(sys.argv[1])
rows=[json.loads(x) for x in (root/'phases/overhead-qwen/requests.jsonl').read_text().splitlines()]
rows=[r for r in rows if not r['warmup']]
ratios=[]
for i in range(0,len(rows),2):
    pair=rows[i:i+2]
    assert len(pair)==2 and pair[0]['input_hash']==pair[1]['input_hash']
    assert pair[0]['response']['text']==pair[1]['response']['text'], 'Token observation changed output'
    b=next(r for r in pair if r['timing_mode']=='basic')
    t=next(r for r in pair if r['timing_mode']=='tokens')
    assert len(t['response']['itl_ms'])==t['response']['output_tokens']-1
    ratios.append(t['response']['timings_ms']['generate_wall_ms']/b['response']['timings_ms']['generate_wall_ms']-1)
median=statistics.median(ratios)
# Token observation is diagnostic only if median generation overhead exceeds 5%.
mode='basic' if median>.05 else 'tokens'
(root/'timing-mode.txt').write_text(mode)
(root/'evidence/overhead.json').write_text(json.dumps({'paired_samples':len(ratios),'paired_generation_overhead_fraction':ratios,'median_overhead_fraction':median,'selected_mode':mode,'selection_rule':'tokens if median paired generate overhead <= 5%; otherwise basic','identical_text_per_pair':True},indent=2))
print('Selected timing mode:',mode,'median overhead:',median)
PY
mode=$(cat "$root/timing-mode.txt")
run 01-qwen-only qwen 30 "$mode" 128
state 0 1
run 02-yolo-only yolo 300 "$mode" 128
state 1 1
run 03-both-resident-qwen qwen 30 "$mode" 128
run 04-both-resident-yolo yolo 300 "$mode" 128
run 05-concurrent both 30 "$mode" 128
# Existing native CLI functional routing test also covers queued Qwen requests.
python3 tests/test_uuid_clients.py --output "$root/uuid-functional" > "$root/evidence/uuid-functional.log" 2>&1
echo PASS > "$root/evidence/five-phases-status.txt"
echo "$(date -Is) ALL_FIVE_PHASES_PASS"
