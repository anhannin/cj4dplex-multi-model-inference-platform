FROM nvcr.io/nvidia/pytorch:25.09-py3@sha256:f3b4a33fd60d5e0358287bb44d57e91eda45e8f1681fef1bfd6c969371417130
# Drop the unused training-resiliency extension that requires deprecated pynvml.
# Replace pynvml with maintained nvidia-ml-py; no warning filters or fake dependencies.
RUN python -m pip uninstall -y pynvml nvidia-resiliency-ext && \
    python -m pip install --no-cache-dir --force-reinstall nvidia-ml-py==13.580.82
WORKDIR /app
ENV PYTHONUNBUFFERED=1 TOKENIZERS_PARALLELISM=false OMP_NUM_THREADS=4
RUN python -c "import torch; print(torch.__version__); assert torch.version.cuda == '13.0'"
