FROM cj-spark-base:25.09-cu130
RUN python -m pip install --no-cache-dir --report /opt/yolo-install.json \
    ultralytics-opencv-headless==8.4.198 && \
    python -m pip freeze > /opt/requirements-resolved.txt
COPY scripts /app/scripts
RUN python -c "import torch, torchvision, ultralytics; print(torch.__version__, torchvision.__version__, ultralytics.__version__)"
ENTRYPOINT ["python", "/app/scripts/worker.py", "cv"]
