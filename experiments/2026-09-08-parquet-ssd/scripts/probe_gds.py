"""Strict non-fallback GDS read probe. Exit failure is an experimental result."""
import json
import os
from pathlib import Path
import subprocess
import argparse

p = argparse.ArgumentParser()
p.add_argument('--root', type=Path, default=Path('/mnt/ssd0'))
a = p.parse_args()

assert os.environ.get('KVIKIO_COMPAT_MODE') == 'OFF'
assert Path(os.environ['CUFILE_ENV_PATH_JSON']).is_file()
import cupy as cp
import kvikio

buf = cp.empty(8 * 1024 * 1024, dtype=cp.uint8)
path = a.root / 'gds-probe.bin'
with path.open('wb') as f:
    f.write(bytes(8 * 1024 * 1024))
os.sync()
subprocess.run(['sudo', 'sysctl', '-q', 'vm.drop_caches=3'], check=True)
with kvikio.CuFile(str(path), 'r') as f:
    print('CuFile handle opened', flush=True)
    read = f.pread(buf).get()
    cp.cuda.runtime.deviceSynchronize()
    assert read == buf.nbytes
    assert not cp.asnumpy(buf).any()
    print(json.dumps({'read_bytes': read, 'pid': os.getpid()}), flush=True)
    subprocess.run(['/usr/local/cuda/gds/tools/gds_stats', '-p', str(os.getpid()), '-l', '3'], check=True)
