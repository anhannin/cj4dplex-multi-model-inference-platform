import gzip
import json
import os
from pathlib import Path

root=Path("/home/avees/cj-latency")
pod=json.loads((root/"phases/05-concurrent/pods.json").read_text())
p=next(p for p in pod["items"] if p["metadata"]["labels"]["app"]=="yolo")
m=p["metadata"]
directory=Path("/var/log/pods")/f"cj-inference_{m['name']}_{m['uid']}"/"yolo"
files=sorted(f for f in directory.iterdir() if f.name.startswith("0.log") and f.name!="0.log")+[directory/"0.log"]
lines=[]
inventory=[]
for f in files:
    if not f.is_file():continue
    opener=gzip.open if f.suffix==".gz" else open
    with opener(f,"rt") as stream:
        for line in stream:
            parts=line.split(" ",3)
            if len(parts)==4:
                lines.append(parts[3])
    inventory.append({"name":f.name,"bytes":f.stat().st_size})
out=root/"phases/05-concurrent/yolo-server.log"
out.write_text("".join(lines))
os.chown(out,1000,1000)
meta=root/"evidence/rotated-log-inventory.json"
meta.write_text(json.dumps({"files":inventory,"lines":len(lines)},indent=2)+"\n")
os.chown(meta,1000,1000)
print(meta.read_text())
