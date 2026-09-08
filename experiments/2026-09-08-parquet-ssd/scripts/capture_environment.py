"""Save non-secret hardware/software evidence to an output directory."""
import argparse
import json
from pathlib import Path
import subprocess
import sys

p = argparse.ArgumentParser()
p.add_argument('--out', required=True, type=Path)
a = p.parse_args()
a.out.mkdir(parents=True, exist_ok=True)
commands = {
    'kernel.txt': ['uname', '-r'],
    'cpu.txt': ['lscpu'],
    'gpu.txt': ['nvidia-smi'],
    'gpu-topology.txt': ['nvidia-smi', 'topo', '-m'],
    'lsblk.txt': ['lsblk', '-o', 'NAME,SIZE,TYPE,MOUNTPOINTS,MODEL'],
    'mounts.txt': ['findmnt', '-t', 'ext4'],
    'driver.txt': ['cat', '/proc/driver/nvidia/version', '/proc/driver/nvidia/params'],
    'nvme-multipath.txt': ['cat', '/sys/module/nvme_core/parameters/multipath'],
    'pci.txt': ['lspci', '-tv'],
    'gdscheck.txt': ['/usr/local/cuda/gds/tools/gdscheck.py', '-p'],
    'requirements.freeze.txt': [sys.executable, '-m', 'pip', 'freeze'],
    'apt-gds.txt': ['dpkg-query', '-W', 'gds-tools-13-2', 'libcufile-13-2'],
}
for name, cmd in commands.items():
    result = subprocess.run(cmd, capture_output=True, text=True)
    (a.out / name).write_text(result.stdout + result.stderr)
    print(json.dumps({'artifact': name, 'returncode': result.returncode}), flush=True)
