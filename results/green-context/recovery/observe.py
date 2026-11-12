import json
from pathlib import Path
import subprocess
import time
root=Path.home()/"cj-green-context/20261103-v1/recovery"
expected=json.loads((root/"retention-input.json").read_text())
observations=[]
start=time.monotonic()
for target in (15,45):
    time.sleep(max(0,target-(time.monotonic()-start)))
    output=subprocess.check_output(["loginctl","show-user","avees","-p","State","-p","Sessions","-p","Linger"],text=True)
    properties=dict(line.split("=",1) for line in output.splitlines() if "=" in line)
    observations.append({"elapsed_seconds":time.monotonic()-start,"properties":properties,
                         "server_files":{p:Path(p).exists() for p in expected["server_paths"]},
                         "marker_exists":Path(expected["marker"]).exists()})
state={"state":"PASS" if all(r["properties"].get("State")=="lingering" and not r["properties"].get("Sessions") and r["marker_exists"] and all(r["server_files"].values()) for r in observations) else "FAIL",
       "observations":observations}
(root/"retention-after-logout.json").write_text(json.dumps(state,indent=2)+"\n")
