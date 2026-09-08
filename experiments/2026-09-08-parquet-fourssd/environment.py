import json
from pathlib import Path
import subprocess
import sys

out = Path(__file__).resolve().parent/'results/environment'
out.mkdir(parents=True,exist_ok=True)
commands = {
    'cpu.txt':['lscpu'],
    'cpu-topology.txt':['lscpu','-p=CPU,CORE,SOCKET,NODE'],
    'gpu.txt':['nvidia-smi'],
    'gpu-topology.txt':['nvidia-smi','topo','-m'],
    'kernel.txt':['uname','-r'],
    'lsblk.txt':['lsblk','-o','NAME,SIZE,TYPE,MOUNTPOINTS,MODEL'],
    'mounts.txt':['findmnt','-t','ext4'],
    'requirements.freeze.txt':[sys.executable,'-m','pip','freeze'],
}
for name,cmd in commands.items():
    result = subprocess.run(cmd,capture_output=True,text=True)
    (out/name).write_text(result.stdout+result.stderr)
    assert result.returncode == 0, name
print(json.dumps({'captured':list(commands)}))
