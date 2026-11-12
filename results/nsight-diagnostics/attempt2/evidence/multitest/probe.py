import os
from pathlib import Path
import time
import torch
Path("/runtime/multitest/pid").write_text(str(os.getpid()))
a=torch.zeros((64,64),device="cuda")
torch.cuda.synchronize()
for i in range(3):
    torch.cuda.profiler.start()
    torch.cuda.nvtx.range_push("phase:"+str(i))
    b=a+1
    torch.cuda.synchronize()
    torch.cuda.nvtx.range_pop()
    torch.cuda.profiler.stop()
    time.sleep(.2)
Path("/runtime/multitest/ready").write_text("ready")
time.sleep(120)
