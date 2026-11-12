"""Query effective context SM count in fresh MPS CUDA clients, serialized."""
import json
import os
import subprocess
import sys

results = []
for cap in (25, 50, 75, 100):
    code = '''import json,torch,os
x=torch.empty(1,device="cuda")
p=torch.cuda.get_device_properties(0)
print(json.dumps({"cap":int(os.environ["CUDA_MPS_ACTIVE_THREAD_PERCENTAGE"]),"sms":p.multi_processor_count,"name":p.name}))'''
    p = subprocess.run([sys.executable, '-c', code], env={**os.environ, 'CUDA_MPS_ACTIVE_THREAD_PERCENTAGE': str(cap)}, check=True, text=True, capture_output=True)
    results.append(json.loads(p.stdout.strip().splitlines()[-1]))
print(json.dumps(results, indent=2))
