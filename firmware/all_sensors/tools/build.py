"""Compile a generated endpoint with Arduino CLI; keep online sketch.ino naming."""
import argparse
from pathlib import Path
import shutil
import subprocess
import tempfile

def main():
 p=argparse.ArgumentParser();p.add_argument('project',type=Path);p.add_argument('--cli',default='arduino-cli');args=p.parse_args()
 project=args.project.resolve();out=project/'build';out.mkdir(exist_ok=True)
 with tempfile.TemporaryDirectory(prefix='ehpad-') as tmp:
  sketch=Path(tmp)/'sketch';sketch.mkdir()
  for f in project.iterdir():
   if f.suffix in {'.ino','.h'}:shutil.copyfile(f,sketch/f.name)
  subprocess.run([args.cli,'compile','--fqbn','esp32:esp32:esp32:PartitionScheme=huge_app','--build-path',str(out),str(sketch)],check=True)
if __name__=='__main__':main()
