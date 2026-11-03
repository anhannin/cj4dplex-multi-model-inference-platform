"""Exploratory model worker. File-controlled, closed loop, no API or queue."""
import argparse
import hashlib
import importlib.metadata
import json
import os
from pathlib import Path
import time
import traceback


def write(path, data):
    path = Path(path)
    tmp = path.with_suffix('.tmp')
    tmp.write_text(json.dumps(data, indent=2))
    tmp.replace(path)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('kind', choices=['llm', 'cv'])
    parser.add_argument('--out', required=True)
    parser.add_argument('--model', default='/cache/models--Qwen--Qwen3.5-9B/snapshots/c202236235762e1c871ad0ccb60c8ee5ba337b9a')
    args = parser.parse_args()
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    import torch
    import psutil
    torch.set_num_threads(4)
    torch.manual_seed(42)
    load_start = time.perf_counter()
    metadata = {'kind': args.kind, 'pid': os.getpid(), 'torch': torch.__version__,
                'cuda_runtime': torch.version.cuda, 'gpu': torch.cuda.get_device_name(),
                'capability': torch.cuda.get_device_capability(), 'cpu_threads': 4}
    if args.kind == 'llm':
        from transformers import AutoTokenizer, Qwen3_5ForConditionalGeneration
        from transformers.generation.streamers import BaseStreamer
        tokenizer = AutoTokenizer.from_pretrained(args.model, local_files_only=True)
        model = Qwen3_5ForConditionalGeneration.from_pretrained(
            args.model, dtype=torch.bfloat16, local_files_only=True,
            attn_implementation='sdpa').eval().to('cuda')
        text = ('A film studio runs text summarization and object detection on one GPU. '
                'The platform records latency, throughput, queue wait and failures. '
                'Requests can compete for computing resources. ' * 40)
        body = tokenizer.decode(tokenizer.encode(text, add_special_tokens=False)[:450])
        prompt = tokenizer.apply_chat_template(
            [{'role': 'user', 'content': body + '\nSummarize the operational risks in this passage.'}],
            tokenize=False, add_generation_prompt=True, enable_thinking=False)
        encoded = tokenizer(prompt, return_tensors='pt')
        metadata.update(input_tokens=encoded.input_ids.shape[1], output_tokens=128,
                        dtype='bfloat16', attention='sdpa',
                        prompt_sha256=hashlib.sha256(prompt.encode()).hexdigest(),
                        prompt=prompt, revision=Path(args.model).name,
                        transformers=importlib.metadata.version('transformers'),
                        forced_length=True)

        class Timer(BaseStreamer):
            def __init__(self):
                self.prompt = True
                self.times = []
            def put(self, value):
                if self.prompt:
                    self.prompt = False
                else:
                    self.times.append(time.perf_counter())
            def end(self):
                pass

        @torch.inference_mode()
        def infer(tokens=128):
            torch.cuda.synchronize()
            start = time.perf_counter()
            inputs = {k: v.to('cuda') for k, v in encoded.items()}
            timer = Timer()
            output = model.generate(**inputs, min_new_tokens=tokens, max_new_tokens=tokens,
                                    do_sample=False, use_cache=True, streamer=timer,
                                    pad_token_id=tokenizer.eos_token_id)
            torch.cuda.synchronize()
            end = time.perf_counter()
            count = output.shape[1] - encoded.input_ids.shape[1]
            return {'latency_ms': (end-start)*1000,
                    'ttft_ms': (timer.times[0]-start)*1000 if timer.times else None,
                    'tpot_ms': (timer.times[-1]-timer.times[0])*1000/(count-1) if count > 1 else None,
                    'output_tokens': count,
                    'text': tokenizer.decode(output[0, encoded.input_ids.shape[1]:], skip_special_tokens=True)}
    else:
        import cv2
        from ultralytics import YOLO
        model_path = Path('/work/assets/yolo26l.pt')
        model = YOLO(str(model_path))
        images = [cv2.imread(str(p)) for p in sorted(Path('/work/assets').glob('*.jpg'))]
        if not images or any(image is None for image in images):
            raise ValueError('Missing or invalid test image')
        metadata.update(dtype='float16', imgsz=640, batch=1,
                        ultralytics=importlib.metadata.version('ultralytics'),
                        image_decode_in_timing=False,
                        model_sha256=hashlib.sha256(model_path.read_bytes()).hexdigest())
        index = 0

        @torch.inference_mode()
        def infer(tokens=None):
            nonlocal index
            image = images[index % len(images)]
            index += 1
            torch.cuda.synchronize()
            start = time.perf_counter()
            result = model.predict(image, device=0, imgsz=640, half=True,
                                   batch=1, rect=False, verbose=False)[0]
            boxes = result.boxes.data.cpu()
            torch.cuda.synchronize()
            end = time.perf_counter()
            return {'latency_ms': (end-start)*1000, 'detections': len(boxes),
                    'stages_ms': result.speed}
    torch.cuda.synchronize()
    metadata['load_seconds'] = time.perf_counter() - load_start
    smoke = infer(16)
    for _ in range(2):
        infer()
    metadata.update(smoke=smoke, allocated_bytes=torch.cuda.memory_allocated(),
                    reserved_bytes=torch.cuda.memory_reserved(),
                    rss_bytes=psutil.Process().memory_info().rss)
    write(out / (args.kind + '-ready.json'), metadata)
    last = None
    while True:
        command_path = out / (args.kind + '-command.json')
        if not command_path.exists():
            time.sleep(.05)
            continue
        command = json.loads(command_path.read_text())
        if command['id'] == last:
            time.sleep(.05)
            continue
        last = command['id']
        if command.get('stop'):
            return
        while time.time() < command['start']:
            time.sleep(.005)
        with (out / (args.kind + '-' + last + '.jsonl')).open('w') as stream:
            while command['active'] and time.time() < command['end']:
                start = time.time()
                try:
                    metrics = infer()
                    row = {'ok': True, **metrics}
                except Exception:
                    row = {'ok': False, 'error': traceback.format_exc()}
                row.update(start=start, end=time.time(),
                           allocated_bytes=torch.cuda.memory_allocated(),
                           reserved_bytes=torch.cuda.memory_reserved())
                stream.write(json.dumps(row) + '\n')
                stream.flush()
                if not row['ok']:
                    raise RuntimeError(row['error'])
        write(out / (args.kind + '-' + last + '-done.json'), {'time': time.time()})


if __name__ == '__main__':
    main()
