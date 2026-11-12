"""Both immutable model images use native595 driver + actually loaded13.1 runtime."""

import argparse, json, subprocess
from pathlib import Path
from config import parse_partition

p = argparse.ArgumentParser()
p.add_argument("--root", required=True, type=Path)
a = p.parse_args()
r = a.root
parts = {
    m: parse_partition((r / "verification" / file).read_text())
    for m, file in (("qwen", "q16-partition.txt"), ("yolo", "y32-partition.txt"))
}
(r / "verification/native-partitions.json").write_text(json.dumps(parts, indent=2))
code = """import torch,ctypes,json,time
v=ctypes.c_int();ctypes.CDLL("libcudart.so.13").cudaRuntimeGetVersion(ctypes.byref(v))
p=torch.cuda.get_device_properties(0)
print(json.dumps({"cuda_runtime":v.value,"torch_build_cuda":torch.version.cuda,"sms":p.multi_processor_count,"sum":torch.ones(1024,device="cuda").sum().item()}),flush=True)
time.sleep(15)
"""
children = []
for m, image in (
    ("qwen", "cj-qwen-ros:9b-timing-v1"),
    ("yolo", "cj-yolo-ros:26l-timing-v1"),
):
    f = (r / "verification" / f"docker-native-{m}.log").open("x")
    cmd = [
        "docker",
        "run",
        "--rm",
        "--name",
        f"cj-static-native-{m}",
        "--gpus",
        "all",
        "--ipc",
        "host",
        "--user",
        "1000:1000",
        "-e",
        "HOME=/tmp",
        "-e",
        "CUDA_MPS_PIPE_DIRECTORY=" + str(r / "native-pipe"),
        "-e",
        "CUDA_MPS_SM_PARTITION=" + parts[m],
        "-e",
        "LD_LIBRARY_PATH=/usr/local/cuda-13.1/lib64:/usr/local/cuda/lib64:/usr/local/nvidia/lib64",
        "-v",
        str(r / "native-pipe") + ":" + str(r / "native-pipe"),
        "-v",
        "/usr/local/cuda-13.1:/usr/local/cuda-13.1:ro",
        "--entrypoint",
        "python",
        image,
        "-u",
        "-c",
        code,
    ]
    children.append((m, subprocess.Popen(cmd, stdout=f, stderr=subprocess.STDOUT), f))
results = []
for m, c, f in children:
    status = c.wait(timeout=90)
    f.close()
    data = (r / "verification" / f"docker-native-{m}.log").read_text()
    print(m, status, data)
    assert status == 0
    result = json.loads(data.strip())
    assert (
        result["cuda_runtime"] == 13010
        and result["sum"] == 1024
        and result["sms"] == (16 if m == "qwen" else 32)
    )
    results.append({"model": m, **result})
(r / "verification/docker-native-summary.json").write_text(
    json.dumps(results, indent=2)
)
print("NATIVE_DOCKER_TWO_CLIENT_PASS")
