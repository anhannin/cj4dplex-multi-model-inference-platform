FROM cj-spark-base:25.09-cu130
RUN python -m pip install --no-cache-dir --report /opt/qwen-install.json \
    transformers==5.22.1 flash-linear-attention==0.4.2 fla-core==0.4.2 einops==0.8.1 && \
    python -m pip install --no-cache-dir --no-deps \
    'https://github.com/Dao-AILab/causal-conv1d/releases/download/v1.7.0/causal_conv1d-1.7.0%2Bcu13torch2.9cxx11abiTRUE-cp312-cp312-linux_aarch64.whl' && \
    python -m pip freeze > /opt/requirements-resolved.txt
COPY scripts /app/scripts
RUN python -c "import torch, triton; from transformers import Qwen3_5ForConditionalGeneration; import causal_conv1d, fla; print(torch.__version__, triton.__version__)"
ENTRYPOINT ["python", "/app/scripts/worker.py", "llm", "--require-acceleration"]
