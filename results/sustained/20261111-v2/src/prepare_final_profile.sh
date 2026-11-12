#!/usr/bin/env bash
# File-only preparation. Does not start Pods, MPS, or profiling.
set -euo pipefail
name="$1"
R="$HOME/cj-static-profile/20261110-final-$name"
B="$HOME/cj-static-eval/20261110-v1"
P="$HOME/cj-static-profile/20261110-native-q16-y32"
[[ ! -e "$R" ]]
mkdir -p "$R"/{src,backup,baseline,logs,metadata,verification,validation,results,warmup,analysis,control,clocks}
chmod 700 "$R"
cp -a "$B/src/." "$R/src/"
cp "$B/backup/"*.json "$R/backup/"
cp "$B/baseline/"*.json "$R/baseline/"
cp "$B/workload.json" "$R/"
cp "$B/verification/docker-native-summary.json" "$R/verification/"
for f in qwen_burst_node.py yolo_burst_node.py client.py base_runner.py burst_runner.py trace_owner.py launch_profile.sh clock_marks.py scheduler_marks2.py analysis.py analyze_reports.py scheduler_analysis.py evidence.py; do
  cp "$P/src/$f" "$R/src/"
done
printf '%s\n' "$R"
