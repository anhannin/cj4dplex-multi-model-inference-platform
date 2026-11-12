#!/usr/bin/env bash
set -euo pipefail
cd /experiment/src
nvcc -O2 -std=c++17 -shared --cudart=shared -Xcompiler=-fPIC -arch=sm_121 $(python -m pybind11 --includes) green_sweep.cu -L/usr/local/cuda/lib64/stubs -lcuda -o "_green_sweep$(python3-config --extension-suffix)"
