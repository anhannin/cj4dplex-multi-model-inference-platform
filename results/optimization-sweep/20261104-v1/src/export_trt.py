"""Stock Ultralytics FP16 export; inputs copied to a separate writable experiment path."""
import hashlib
import json
from pathlib import Path
import shutil
from ultralytics import YOLO

root = Path('/experiment/engine')
root.mkdir(exist_ok=True)
shutil.copyfile('/assets/yolo26l.pt', root / 'yolo26l.pt')
result = YOLO(str(root / 'yolo26l.pt')).export(
    format='engine', device=0, imgsz=640, batch=1, quantize=16,
    dynamic=False, simplify=False, workspace=2, verbose=False,
)
p = Path(result)
print(json.dumps({'engine': str(p), 'bytes': p.stat().st_size, 'sha256': hashlib.sha256(p.read_bytes()).hexdigest()}))
