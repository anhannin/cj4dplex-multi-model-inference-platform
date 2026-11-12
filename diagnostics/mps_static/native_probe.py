"""Two isolated native CUDA clients must actually run on their static partitions."""

import argparse
import json
from pathlib import Path
import subprocess
from config import static_env

p = argparse.ArgumentParser()
p.add_argument("--root", type=Path, required=True)
p.add_argument("--label", required=True)
a = p.parse_args()
r = a.root
parts = json.loads((r / "verification/partitions.json").read_text())
code = """import torch,json,time,ctypes
c=ctypes.CDLL("libcuda.so.1");v=ctypes.c_int();c.cuDriverGetVersion(ctypes.byref(v))
print(json.dumps({"driver_api":v.value,"loaded_cuda":[line.strip() for line in open("/proc/self/maps") if "/libcuda.so" in line]}),flush=True)
p=torch.cuda.get_device_properties(0)
print(json.dumps({"torch_build_cuda":torch.version.cuda,"visible_sms":p.multi_processor_count,"sum":torch.ones(1024,device="cuda").sum().item()}),flush=True)
time.sleep(10)
"""
children = []
for m, image in (
    ("qwen", "cj-qwen-ros:9b-timing-v1"),
    ("yolo", "cj-yolo-ros:26l-timing-v1"),
):
    out = (r / "verification" / f"{a.label}-{m}-native.log").open("x")
    cmd = [
        "docker",
        "run",
        "--rm",
        "--name",
        "cj-static-" + m + "-probe",
        "--gpus",
        "all",
        "--ipc",
        "host",
        "--pid",
        "host",
        "--user",
        "1000:1000",
        "-e",
        "HOME=/tmp",
    ]
    for k, v in static_env(str(r / "mps-pipe"), parts[m], "/opt/cuda-compat").items():
        cmd += ["-e", k + "=" + v]
    cmd += [
        "-v",
        str(r / "mps-pipe") + ":" + str(r / "mps-pipe"),
        "-v",
        str(r / "compat590/usr/local/cuda-13.1/compat") + ":/opt/cuda-compat:ro",
        "--entrypoint",
        "python",
        image,
        "-u",
        "-c",
        code,
    ]
    children.append(
        (m, subprocess.Popen(cmd, stdout=out, stderr=subprocess.STDOUT), out)
    )
results = []
for m, child, out in children:
    try:
        status = child.wait(timeout=90)
    except subprocess.TimeoutExpired:
        child.terminate()
        child.wait(timeout=10)
        status = 124
    out.close()
    file = r / "verification" / f"{a.label}-{m}-native.log"
    text = file.read_text()
    print(m, status, text, flush=True)
    rows = [json.loads(line) for line in text.splitlines() if line.startswith("{")]
    results.append({"model": m, "exit": status, "records": rows})
(r / "verification" / f"{a.label}-native-summary.json").write_text(
    json.dumps(results, indent=2)
)
assert all(v["exit"] == 0 for v in results), (
    "Actual CUDA client failure; partition creation is not success"
)
for result in results:
    expected = 16 if result["model"] == "qwen" else 32
    assert result["records"][-1]["visible_sms"] == expected
    assert result["records"][-1]["sum"] == 1024
print("STATIC_NATIVE_TWO_CLIENT_PASS")
