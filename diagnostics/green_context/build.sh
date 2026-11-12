#!/usr/bin/env bash
set -euo pipefail
cd /diag/src
arch=sm_120
if nvcc --list-gpu-code | grep -q sm_121; then arch=sm_121; fi
nvcc -O2 -std=c++17 -shared --cudart=shared -Xcompiler=-fPIC -arch="$arch"   $(python -m pybind11 --includes) green_bridge.cu   -L/usr/local/cuda/lib64/stubs -lcuda   -o "green_bridge$(python3-config --extension-suffix)"
echo "COMPILED_ARCH=$arch"
