"""Independent raw-event audit; idle-process recovery only, not a normal-load SLO claim."""

import argparse
import csv
import json
from pathlib import Path
import statistics

p = argparse.ArgumentParser()
p.add_argument("--root", required=True, type=Path)
a = p.parse_args()
root = a.root
state = json.loads((root / "verification/controller-status.json").read_text())
assert state["state"] == state["restoration"] == "PASS" and len(state["trials"]) == 3
results = []
seenpods = set()
qids = set()
mpsids = set()
for index in range(3):
    folder = root / "results" / f"trial{index}"
    s = json.loads((folder / "summary.json").read_text())
    fault = json.loads((folder / "fault.json").read_text())
    ack = json.loads((folder / "idle-barrier.json").read_text())
    result = json.loads((folder / "probe-result.json").read_text())
    t0 = fault["fault_before_ns"]
    old = s["before"]
    new = s["after"]
    assert s["state"] == result["state"] == "PASS"
    assert (
        ack["nonce"] == fault["idle_nonce"]
        and ack["gpu_synchronized"]
        and ack["queue_empty"]
        and ack["perf_ns"] <= t0
    )
    assert (
        fault["kind"] == "SIGKILL_GPU_IDLE_ROS_NODE"
        and fault["target_uid"] == 1000
        and fault["not_inflight_gpu_crash"]
    )
    assert old["pod_uid"] == new["pod_uid"] and old["pod_uid"] not in seenpods
    seenpods.add(old["pod_uid"])
    assert (
        old["container_id"] != new["container_id"]
        and old["restart_count"] == 0
        and new["restart_count"] == 1
    )
    assert (
        new["last_state"]["terminated"]["exitCode"] == 137
        and new["last_state"]["terminated"]["reason"] == "Error"
    )
    assert s["mps_before"]["server"] == s["mps_after"]["server"]
    mpsids.add(s["mps_before"]["server"])
    assert s["mps_before"]["models"]["qwen"] == s["mps_after"]["models"]["qwen"]
    qids.add(s["mps_before"]["models"]["qwen"])
    assert (
        s["mps_before"]["models"]["yolo"] == fault["target_host_pid"]
        and s["mps_after"]["models"]["yolo"] != fault["target_host_pid"]
    )
    rows = [
        json.loads(v)
        for v in (folder / "pod-observations.jsonl").read_text().splitlines()
    ]
    assert all(v["exit"] == 0 and v["snapshot"] is not None for v in rows)
    rows = [v for v in rows if v["poll_after_ns"] >= t0]

    # Recompute from raw states instead of calling the controller's transition helper.
    def detected(v):
        q = v["snapshot"]
        return (
            q["pod_uid"] != old["pod_uid"]
            or not q["ready"]
            or q["restart_count"] > 0
            or "terminated" in q["state"]
            or "waiting" in q["state"]
            or q["container_id"] not in ("", old["container_id"])
        )

    def restarted(v):
        q = v["snapshot"]
        return (
            q["pod_uid"] == old["pod_uid"]
            and q["container_id"] not in ("", old["container_id"])
            and "running" in q["state"]
            and q["restart_count"] == 1
        )

    d = next(v for v in rows if detected(v))
    n = next(v for v in rows if restarted(v))
    ready = next(v for v in rows if restarted(v) and v["snapshot"]["ready"])
    assert (
        result["publish_count"] == 1
        and result["application_retries"] == 0
        and result["sent_ns"] >= fault["fault_after_ns"]
    )
    assert (
        result["response"]["status"] == "ok"
        and result["response"]["assigned_sms"] == 40
        and not result["response"]["green_enabled"]
        and len(result["response"]["detections"]) == 5
    )
    assert result["response"]["server_enqueued_perf_ns"] > t0
    assert result["request_id"] == result["response"]["request_id"]
    values = {
        "trial": index,
        "detect_observed_ms": (d["poll_after_ns"] - t0) / 1e6,
        "container_start_observed_ms": (n["poll_after_ns"] - t0) / 1e6,
        "ready_observed_ms": (ready["poll_after_ns"] - t0) / 1e6,
        "first_valid_response_ms": (result["received_ns"] - t0) / 1e6,
        "probe_e2e_ms": (result["received_ns"] - result["sent_ns"]) / 1e6,
        "probe_publish_after_fault_ms": (result["sent_ns"] - t0) / 1e6,
        "observer_max_query_ms": max(v["poll_elapsed_ms"] for v in rows),
    }
    for k, v in values.items():
        if k in s and k != "trial":
            assert abs(v - s[k]) < 1e-6
    publications = []
    for line in (folder / "yolo-restarted.log").read_text().splitlines():
        i = line.find('{"event"')
        if i < 0:
            continue
        try:
            e = json.loads(line[i:])
        except ValueError:
            continue
        if (
            e.get("event") == "publication_finished"
            and e.get("request_id") == result["request_id"]
        ):
            publications.append(e)
    assert publications and all(e["acknowledged"] for e in publications)
    values.update(
        same_pod_uid=True,
        new_container=True,
        restart_count=1,
        exit_code=137,
        mps_server_unchanged=True,
        qwen_host_pid_unchanged=True,
    )
    results.append(values)
assert len(qids) == len(mpsids) == 1
qrows = [
    json.loads(v)
    for v in (root / "results/qwen-requests.jsonl").read_text().splitlines()
]
qstate = json.loads((root / "verification/qwen-monitor-status.json").read_text())
assert qstate["state"] == "PASS" and not qstate["errors"]
assert len({v["request_id"] for v in qrows}) == len(qrows)
for v in qrows:
    r = v["response"]
    assert (
        r["status"] == "ok"
        and r["assigned_sms"] == 8
        and not r["green_enabled"]
        and r["input_tokens"] == 512
        and r["output_tokens"] == 128
    )
    assert abs(v["request_e2e_ms"] - (v["received_ns"] - v["sent_ns"]) / 1e6) < 1e-6
faults = [
    json.loads((root / "results" / f"trial{i}" / "fault.json").read_text())[
        "fault_before_ns"
    ]
    for i in range(3)
]
endpoints = [faults[i] + results[i]["first_valid_response_ms"] * 1e6 for i in range(3)]
measured = [v for v in qrows if not v["warmup"]]
first = faults[0]
last = endpoints[-1]
cohorts = {
    "before_first_fault": [v for v in measured if v["received_ns"] < first],
    "overlap_fault_recovery": [
        v
        for v in measured
        if any(
            v["sent_ns"] < b and v["received_ns"] > a for a, b in zip(faults, endpoints)
        )
    ],
    "after_last_functional_recovery": [v for v in measured if v["sent_ns"] > last],
}
for i, (begin, end) in enumerate(zip(faults, endpoints)):
    assert any(v["sent_ns"] < end and v["received_ns"] > begin for v in measured), (
        "No concurrent Qwen request",
        i,
    )


def describe(values):
    return (
        {
            "n": len(values),
            "mean": statistics.mean(values),
            "median": statistics.median(values),
            "min": min(values),
            "max": max(values),
        }
        if values
        else None
    )


summary = {
    "scope": "GPU-IDLE YOLO ROS Node SIGKILL only;3independentPodUIDs;notbusyGPUfault/notthreadhang/notqueuepersistence",
    "trials": results,
    "recovery": {
        k: describe([v[k] for v in results])
        for k in (
            "detect_observed_ms",
            "container_start_observed_ms",
            "ready_observed_ms",
            "first_valid_response_ms",
        )
    },
    "qwen": {
        "requests": len(qrows),
        "warmup": sum(v["warmup"] for v in qrows),
        "measured": len(measured),
        "errors": 0,
        "host_pid": next(iter(qids)),
        "cohorts": {
            k: describe([v["request_e2e_ms"] for v in values])
            for k, values in cohorts.items()
        },
    },
    "mps_server_pid": next(iter(mpsids)),
    "patient_probe_successes": 3,
    "no_application_retry": True,
    "outage_success_rate_not_established": True,
    "rto_slo_not_defined": True,
    "restoration": "PASS",
}
probes = []
for file in sorted((root / "results").glob("*/probe-result.json")):
    v = json.loads(file.read_text())
    assert v["state"] == "PASS" and v["publish_count"] == 1
    probes.append(
        {
            "run": file.parent.name,
            "request_id": v["request_id"],
            "e2e_ms": v["request_e2e_ms"],
        }
    )
summary["all_yolo_requests"] = len(probes)
summary["all_result_count"] = len(probes) + len(qrows)
(root / "analysis/summary.json").write_text(json.dumps(summary, indent=2))
(root / "verification/independent-audit.json").write_text(
    json.dumps(
        {
            "state": "PASS",
            "trials": 3,
            "same_uid_per_trial": True,
            "independent_uid_across_trials": True,
            "exit137": True,
            "all_result_count": summary["all_result_count"],
            "qwen_results": len(qrows),
            "yolo_results": len(probes),
            "idle_sync_ack_verified": True,
            "timestamps_recomputed": True,
            "mps_qwen_pid_preserved": True,
            "publication_ack_verified": True,
        },
        indent=2,
    )
)
with (root / "analysis/trials.csv").open("w") as f:
    writer = csv.DictWriter(f, fieldnames=list(results[0]))
    writer.writeheader()
    writer.writerows(results)
print(json.dumps(summary, indent=2))
