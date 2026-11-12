"""Two-image stock PyTorch-FP16 vs TensorRT-FP16 fidelity smoke, not mAP validation."""
import json
from pathlib import Path
from PIL import Image
import torch
from ultralytics import YOLO


def iou(a, b):
    area = max(0, min(a[2], b[2]) - max(a[0], b[0])) * max(0, min(a[3], b[3]) - max(a[1], b[1]))
    union = (a[2]-a[0])*(a[3]-a[1]) + (b[2]-b[0])*(b[3]-b[1]) - area
    return area / union if union else 0


torch.set_num_threads(4)
options = dict(device=0, imgsz=640, quantize=16, batch=1, rect=False, verbose=False, save=False)
pt = YOLO('/assets/yolo26l.pt')
trt = YOLO('/experiment/engine/yolo26l.engine', task='detect')
records = []
with torch.inference_mode():
    for name in ('bus.jpg', 'zidane.jpg'):
        image = Image.open('/assets/' + name).convert('RGB')
        a = pt.predict(image, **options)[0].boxes.data.cpu().tolist()
        b = trt.predict(image, **options)[0].boxes.data.cpu().tolist()
        matches, unused = [], set(range(len(b)))
        for box in a:
            eligible = [j for j in unused if int(b[j][5]) == int(box[5])]
            if not eligible:
                matches.append({'iou': 0, 'confidence_delta': None})
                continue
            j = max(eligible, key=lambda j: iou(box, b[j]))
            unused.remove(j)
            matches.append({'iou': iou(box, b[j]), 'confidence_delta': abs(box[4] - b[j][4])})
        passed = len(a) == len(b) and not unused and all(m['iou'] >= .98 and m['confidence_delta'] is not None and m['confidence_delta'] <= .02 for m in matches)
        records.append({'image': name, 'torch': a, 'tensorrt': b, 'matches': matches, 'pass': passed})
result = {'scope': 'two-image fidelity smoke only, not COCO mAP', 'criteria': 'same counts/classes, matched IoU>=0.98/confidence delta<=0.02', 'records': records, 'pass': all(r['pass'] for r in records)}
Path('/experiment/results/trt-quality.json').write_text(json.dumps(result, indent=2))
print(json.dumps(result, indent=2))
if not result['pass']:
    raise RuntimeError('TensorRT fidelity gate failed')
