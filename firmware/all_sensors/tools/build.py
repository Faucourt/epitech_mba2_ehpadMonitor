"""Compile a generated endpoint with Arduino CLI; keep online sketch.ino naming."""
import argparse
from pathlib import Path
import shutil
import subprocess
import tempfile

def main():
 p=argparse.ArgumentParser();p.add_argument('project',type=Path);p.add_argument('--cli',default='arduino-cli');p.add_argument('--reuse-build',type=Path);args=p.parse_args()
 project=args.project.resolve();out=project/'build';out.mkdir(exist_ok=True)
 with tempfile.TemporaryDirectory(prefix='ehpad-') as tmp:
  workspace=args.reuse_build.resolve() if args.reuse_build else Path(tmp)
  sketch=workspace/'sketch';sketch.mkdir(parents=True,exist_ok=True)
  for f in project.iterdir():
   if f.suffix in {'.ino','.h'}:
    dest=sketch/f.name
    if not dest.exists() or dest.read_bytes()!=f.read_bytes():shutil.copyfile(f,dest)
  compiled=workspace/'compiled' if args.reuse_build else out
  subprocess.run([args.cli,'compile','--fqbn','esp32:esp32:esp32:PartitionScheme=huge_app','--build-path',str(compiled),str(sketch)],check=True)
  if args.reuse_build:
   for f in compiled.glob('sketch.ino.*'):
    if f.is_file():shutil.copyfile(f,out/f.name)
if __name__=='__main__':main()
