"""Resource/event API smoke only; NOT model performance samples."""
import json
from pathlib import Path
import torch
from _green_sweep import Green

out=[]
torch.cuda.set_device(0)
x=torch.ones((128,128),device='cuda')
for sm in (8,48):
    green=Green(sm)
    stream=torch.cuda.ExternalStream(green.stream_ptr(),device=0)
    stream.wait_stream(torch.cuda.current_stream())
    try:
        ids=green.sample_smids()
        assert 0<len(ids)<=sm
        with torch.cuda.stream(stream):
            a,b=torch.cuda.Event(enable_timing=True),torch.cuda.Event(enable_timing=True)
            a.record(stream)
            y=x@x
            b.record(stream)
            stream.synchronize()
            error=float((y-128).abs().max().item())
            assert error==0
            elapsed=a.elapsed_time(b)
            assert elapsed>0
        out.append({**green.metadata(),'observed_smids':ids,'event_ms':elapsed,'max_error':error})
        del y,a,b
        torch.cuda.synchronize()
        torch.cuda.empty_cache()
    finally:
        del stream
        green.close()
Path('/experiment/verification/native-smoke.json').write_text(json.dumps(out,indent=2))
print(json.dumps(out,indent=2))
