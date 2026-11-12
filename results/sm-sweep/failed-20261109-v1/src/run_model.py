#!/usr/bin/env python3
"""Real stock-model SM sweep. No ROS, MPS, TensorRT, framework patches or CUDA Graphs."""
import argparse
import ast
import gc
import hashlib
import json
import os
from pathlib import Path
import subprocess
import time

from metrics import fixed_prompt_ids, summarize_forward, summarize_rows, sweep_order
from observer import ForwardTimer

MODEL='/cache/models--Qwen--Qwen3.5-9B/snapshots/c202236235762e1c871ad0ccb60c8ee5ba337b9a'


def sensor():
    p=subprocess.run(['nvidia-smi','--query-gpu=temperature.gpu,clocks.sm,power.draw,utilization.gpu','--format=csv,noheader'],capture_output=True,text=True)
    return p.stdout.strip() if p.returncode==0 else p.stderr.strip()


def token_clock():
    source=Path('/app/ros2/qwen_node.py').read_text()
    tree=ast.parse(source)
    node=next(n for n in tree.body if isinstance(n,ast.ClassDef) and n.name=='TokenClock')
    scope={'time':time}
    exec(compile(ast.Module(body=[node],type_ignores=[]),'<frozen TokenClock>','exec'),scope)
    return scope['TokenClock'], hashlib.sha256(source.encode()).hexdigest()


class Streams:
    def __init__(self, torch):
        self.torch=torch
        self.default=torch.cuda.current_stream()
        self.greens={}
        self.streams={}
        self.metadata={}

    def get(self, sm):
        from _green_sweep import Green
        if sm is None:
            return self.default
        if sm not in self.greens:
            g=Green(sm)
            meta=dict(g.metadata())
            meta['observed_smids']=g.sample_smids()
            if meta['actual_sms']!=sm or not 0<len(meta['observed_smids'])<=sm:
                raise RuntimeError('SM allocation/sample check failed')
            stream=self.torch.cuda.ExternalStream(g.stream_ptr(),device=0)
            stream.wait_stream(self.default)
            self.greens[sm],self.streams[sm],self.metadata[sm]=g,stream,meta
        return self.streams[sm]

    def close(self):
        for stream in self.streams.values():
            stream.synchronize()
        self.streams.clear()
        for green in self.greens.values():
            green.close()
        self.greens.clear()


class Qwen:
    metrics=['prefill_forward_ms','decode_forward_ms_per_token','decode_forward_total_ms','generate_wall_ms','generate_ttft_ms','tpot_ms']

    def __init__(self, torch, a):
        from transformers import AutoTokenizer,Qwen3_5ForConditionalGeneration
        from transformers.models.qwen3_5 import modeling_qwen3_5
        self.torch,self.a=torch,a
        self.Clock,source_hash=token_clock()
        tokenizer=AutoTokenizer.from_pretrained(MODEL,local_files_only=True)
        placeholder='CJ_FIXED_USER_CONTENT_784513'
        template=tokenizer.apply_chat_template([{'role':'user','content':placeholder}],tokenize=False,add_generation_prompt=True,enable_thinking=False)
        prefix,suffix=template.split(placeholder)
        body=('Explain GPU resource contention and reliable multi-model inference serving. Discuss scheduling, latency, throughput, resource allocation, queues, monitoring, and deployment. Write a detailed explanation with many examples. '*100)
        ids=fixed_prompt_ids(tokenizer.encode(prefix,add_special_tokens=False),tokenizer.encode(suffix,add_special_tokens=False),tokenizer.encode(body,add_special_tokens=False),a.input_tokens)
        self.inputs={'input_ids':torch.tensor([ids],dtype=torch.long,device='cuda'),'attention_mask':torch.ones((1,len(ids)),dtype=torch.long,device='cuda')}
        self.model=Qwen3_5ForConditionalGeneration.from_pretrained(MODEL,dtype=torch.bfloat16,local_files_only=True,attn_implementation='sdpa').eval().to('cuda')
        assert next(self.model.parameters()).dtype==torch.bfloat16
        bindings={name:getattr(modeling_qwen3_5,name).__module__ for name in ('causal_conv1d_fn','causal_conv1d_update','torch_chunk_gated_delta_rule','torch_recurrent_gated_delta_rule')}
        if not all(bindings[n].startswith('causal_conv1d.' if n.startswith('causal') else 'fla.') for n in bindings):
            raise RuntimeError('Missing pinned native inference kernels')
        self.options=dict(min_new_tokens=a.output_tokens,max_new_tokens=a.output_tokens,do_sample=False,use_cache=True,pad_token_id=tokenizer.eos_token_id)
        self.observer=ForwardTimer(torch,self.model,'qwen')
        self.info={'model':'Qwen3.5-9B','dtype':'bfloat16','attention':'sdpa','native_bindings':bindings,'frozen_source_sha256':source_hash,'input_ids':ids,'input_tokens':len(ids),'input_ids_sha256':hashlib.sha256(json.dumps(ids).encode()).hexdigest(),'rendered_input':tokenizer.decode(ids),'output_tokens_forced':a.output_tokens,'graph_capture':False}

    def configure(self,stream):
        self.stream=stream
        self.observer.configure(stream,self.a.output_tokens)

    def call(self):
        torch=self.torch
        self.observer.reset()
        clock=self.Clock()
        with torch.inference_mode(),torch.cuda.stream(self.stream):
            self.stream.synchronize()
            start=time.perf_counter_ns()
            output=self.model.generate(**self.inputs,**self.options,streamer=clock)
            self.stream.synchronize()
            wall=(time.perf_counter_ns()-start)/1e6
        actual=int(output.shape[-1]-self.a.input_tokens)
        if actual!=self.a.output_tokens or len(clock.times)!=actual:
            raise RuntimeError('Generated token work changed')
        times=self.observer.elapsed()
        metrics=summarize_forward(self.observer.lengths,times,self.a.input_tokens,self.a.output_tokens)
        tokens=output[0,self.a.input_tokens:].tolist()
        timing=clock.metrics(start,start)
        del output
        return {**metrics,'generate_wall_ms':wall,'generate_ttft_ms':timing['generate_ttft_ms'],'tpot_ms':timing['tpot_ms'],'output_tokens':actual,'output_ids_sha256':hashlib.sha256(json.dumps(tokens).encode()).hexdigest(),'forward_event_ms':times,'forward_input_lengths':list(self.observer.lengths)}

    def close(self):
        self.observer.close()
        self.observer=None
        self.stream=None
        self.model=None
        self.inputs=None


class Yolo:
    metrics=['model_forward_ms','predict_wall_ms']

    def __init__(self,torch,a):
        from ultralytics import YOLO
        from PIL import Image
        self.torch=torch
        self.image=Image.open('/assets/bus.jpg').convert('RGB')
        self.model=YOLO('/assets/yolo26l.pt')
        self.options=dict(device=0,imgsz=640,quantize=16,batch=1,rect=False,verbose=False,save=False)
        with torch.inference_mode():
            self.reference=self.model.predict(self.image,**self.options)[0].boxes.data.cpu().tolist()
        backend=self.model.predictor.model
        assert backend.device.type=='cuda' and backend.fp16 and next(backend.model.parameters()).dtype==torch.float16
        self.observer=ForwardTimer(torch,backend.model,'yolo')
        self.info={'model':'YOLO26l','dtype':'float16','backend':'native PyTorch','imgsz':640,'batch':1,'rect':False,'image_sha256':hashlib.sha256(Path('/assets/bus.jpg').read_bytes()).hexdigest(),'reference_detections':self.reference,'graph_capture':False}

    def configure(self,stream):
        self.stream=stream
        self.observer.configure(stream,1)

    def call(self):
        self.observer.reset()
        with self.torch.inference_mode(),self.torch.cuda.stream(self.stream):
            self.stream.synchronize()
            start=time.perf_counter_ns()
            result=self.model.predict(self.image,**self.options)[0]
            self.stream.synchronize()
            wall=(time.perf_counter_ns()-start)/1e6
        times=self.observer.elapsed()
        if len(times)!=1 or self.observer.lengths!=[[1,3,640,640]]:
            raise RuntimeError('Native YOLO forward shape/count changed')
        actual=result.boxes.data.cpu().tolist()
        quality=match_boxes(self.reference,actual)
        if not quality['pass']:
            raise RuntimeError('YOLO fidelity gate failed: '+repr(quality))
        del result
        return {'model_forward_ms':times[0],'predict_wall_ms':wall,'forward_shape':[1,3,640,640],'detections':actual,'fidelity':quality}

    def close(self):
        self.observer.close()
        self.observer=None
        self.stream=None
        self.model=None


def match_boxes(reference,actual):
    remaining=set(range(len(actual)))
    matches=[]
    for ref in reference:
        choices=[]
        for j in remaining:
            box=actual[j]
            if int(box[5])!=int(ref[5]):
                continue
            intersection=max(0,min(ref[2],box[2])-max(ref[0],box[0]))*max(0,min(ref[3],box[3])-max(ref[1],box[1]))
            union=(ref[2]-ref[0])*(ref[3]-ref[1])+(box[2]-box[0])*(box[3]-box[1])-intersection
            choices.append((intersection/union if union else 0,j))
        if not choices:
            return {'pass':False,'reason':'unmatched class/count'}
        iou,j=max(choices)
        remaining.remove(j)
        matches.append({'iou':iou,'confidence_delta':abs(ref[4]-actual[j][4])})
    return {'pass':len(reference)==len(actual) and not remaining and all(x['iou']>=.98 and x['confidence_delta']<=.02 for x in matches),'matches':matches}


def main():
    p=argparse.ArgumentParser()
    p.add_argument('--model',choices=['qwen','yolo'],required=True)
    p.add_argument('--output',type=Path,required=True)
    p.add_argument('--sms',nargs='+',type=int,default=[8,16,24,32,40,48])
    p.add_argument('--rounds',type=int,default=2)
    p.add_argument('--samples-per-round',type=int,required=True)
    p.add_argument('--warmup',type=int,required=True)
    p.add_argument('--reference-samples',type=int,required=True)
    p.add_argument('--input-tokens',type=int,default=512)
    p.add_argument('--output-tokens',type=int,default=128)
    p.add_argument('--trace-probe',action='store_true')
    a=p.parse_args()
    if min(a.rounds,a.samples_per_round,a.warmup,a.reference_samples,a.input_tokens,a.output_tokens)<1 or a.output_tokens<2:
        p.error('Positive counts and >=2 output tokens required')
    if os.environ.get('CUDA_MPS_PIPE_DIRECTORY') or os.environ.get('CUDA_MPS_ACTIVE_THREAD_PERCENTAGE'):
        p.error('MPS must be disabled')
    a.output.mkdir(parents=True,exist_ok=False)
    import torch
    torch.set_num_threads(4)
    torch.cuda.set_device(0)
    torch.manual_seed(20261109)
    streams=Streams(torch)
    runner=None
    manifest={'state':'RUNNING','start_wall_ns':time.time_ns(),'model':a.model,'sms':a.sms,'rounds':a.rounds,'samples_per_round':a.samples_per_round,'warmup_per_point_round':a.warmup,'reference_samples_per_position':a.reference_samples,'torch':torch.__version__,'gpu':torch.cuda.get_device_name(0),'graph_capture':False,'mps':False,'scope':'single active real-model CUDA-event/host inference sensitivity, NOT service E2E or concurrent performance','timing_note':'CUDA events bracket native Module.forward; spans can include GPU idle/dispatch gaps, not pure kernel busy time. No added per-token synchronize.'}
    rows=[]
    try:
        runner=Qwen(torch,a) if a.model=='qwen' else Yolo(torch,a)
        manifest['workload']=runner.info
        print(json.dumps({'event':'model_loaded','model':a.model}),flush=True)
        def block(sm,round_index,samples,warmup,writer):
            stream=streams.get(sm)
            runner.configure(stream)
            sm_count=48 if sm is None else sm
            print(json.dumps({'event':'point_start','sm_count':sm_count,'backend':'default' if sm is None else 'green','round':round_index}),flush=True)
            before=sensor()
            for index in range(warmup+samples):
                record={'model':a.model,'sm_count':sm_count,'backend':'default' if sm is None else 'green','round':round_index,'index':index-warmup,'warmup':index<warmup}
                if a.trace_probe and index==warmup and sm is not None:
                    with torch.cuda.nvtx.range(f'{a.model}.green.sm{sm}'):
                        record.update(runner.call())
                else:
                    record.update(runner.call())
                rows.append(record)
                writer.write(json.dumps(record)+'\n')
                writer.flush()
            manifest.setdefault('point_sensors',[]).append({'sm_count':sm_count,'backend':'default' if sm is None else 'green','round':round_index,'before':before,'after':sensor()})
            manifest['green_resources']=streams.metadata
            (a.output/'manifest.json').write_text(json.dumps(manifest,indent=2))
            print(json.dumps({'event':'point_complete','sm_count':sm_count,'round':round_index,'samples':samples}),flush=True)
        with (a.output/'default-reference.jsonl').open('x') as ref, (a.output/'requests.jsonl').open('x') as out:
            block(None,-1,a.reference_samples,a.warmup,ref)
            if a.trace_probe:
                torch.cuda.profiler.start()
            for round_index in range(a.rounds):
                for sm in sweep_order(a.sms,round_index):
                    block(sm,round_index,a.samples_per_round,a.warmup,out)
            if a.trace_probe:
                torch.cuda.profiler.stop()
            block(None,a.rounds,a.reference_samples,a.warmup,ref)
        main_rows=[r for r in rows if r['backend']=='green']
        (a.output/'summary.json').write_text(json.dumps(summarize_rows(main_rows,runner.metrics),indent=2))
        (a.output/'default-summary.json').write_text(json.dumps(summarize_rows([r for r in rows if r['backend']=='default'],runner.metrics),indent=2))
        manifest['state']='PASS'
    except Exception as error:
        manifest.update(state='FAIL',error=repr(error))
        raise
    finally:
        if runner is not None:
            runner.close()
            del runner
        gc.collect()
        torch.cuda.synchronize()
        torch.cuda.empty_cache()
        streams.close()
        manifest['end_wall_ns']=time.time_ns()
        (a.output/'manifest.json').write_text(json.dumps(manifest,indent=2))
    print(json.dumps({'state':manifest['state'],'output':str(a.output)}),flush=True)


if __name__=='__main__':
    main()
