"""Compile every active driver configuration and the real BLE path, recording evidence."""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import time
from export_projects import BASE,ROOT,inventory,export

def main():
 p=argparse.ArgumentParser();p.add_argument('--cli',default='arduino-cli');args=p.parse_args()
 chosen={}
 for d in inventory()['devices']:chosen.setdefault(d['kind'],d)
 report=[]
 for kind,d in list(chosen.items())+[('ble-hardware',chosen['ble'])]:
  out=ROOT/'build'/'matrix'/kind;export(d,out,hardware=kind=='ble-hardware')
  started=time.monotonic()
  run=subprocess.run([sys.executable,str(BASE/'tools/build.py'),str(out),'--cli',args.cli,'--reuse-build',str(ROOT/'build/arduino-matrix-cache')],capture_output=True,text=True)
  result={'kind':kind,'device_id':d['id'],'exit_code':run.returncode,'seconds':round(time.monotonic()-started,1),'compiler_output':run.stdout[-2000:],'compiler_errors':run.stderr[-2000:]}
  if run.returncode==0:
   result['firmware_sha256']=hashlib.sha256((out/'build/sketch.ino.bin').read_bytes()).hexdigest()
  report.append(result)
  (BASE/'validation').mkdir(exist_ok=True)
  (BASE/'validation/compilation.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
  print(f"{kind}: {'PASS' if run.returncode==0 else 'FAIL'} ({result['seconds']}s)",flush=True)
  if run.returncode:print(run.stderr,flush=True);raise SystemExit(run.returncode)
if __name__=='__main__':main()
