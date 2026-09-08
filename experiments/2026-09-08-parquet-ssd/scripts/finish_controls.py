"""Preserve the 16-GiB pool failure, test 20 GiB, then verify all data copies."""
import json
import os
from pathlib import Path
import subprocess
import sys

base = Path('/home/ubuntu/parquet-results')
scripts = Path(__file__).parent
failed = base / 'failed'
failed.mkdir(exist_ok=True)
for suffix in ['jsonl', 'stderr']:
    source = base / 'batch32' / f'gpu-zstd-2disk-cold.{suffix}'
    dest = failed / f'gpu-zstd-2disk-cold-batch32-pool16.{suffix}'
    assert not dest.exists()
    source.rename(dest)
env = dict(os.environ, CUDA_VISIBLE_DEVICES='0', KVIKIO_COMPAT_MODE='ON', KVIKIO_NTHREADS='16')
dest = base / 'batch32-pool20'
dest.mkdir(exist_ok=True)
cmd = [sys.executable, str(scripts / 'bench.py'), '--roots', '/mnt/ssd0', '/mnt/ssd1',
       '--disks', '2', '--codec', 'zstd', '--engine', 'gpu', '--cache', 'cold',
       '--threads', '16', '--batch', '32', '--gpu-pool-max-gib', '20',
       '--devices', 'nvme1n1', 'nvme2n1']
with (dest / 'gpu-zstd-2disk-cold.jsonl').open('x') as f, (dest / 'gpu-zstd-2disk-cold.stderr').open('x') as err:
    result = subprocess.run(cmd, env=env, stdout=f, stderr=err)
(dest / 'command.json').write_text(json.dumps({'command': cmd, 'returncode': result.returncode}, indent=2))
print('pool20 returncode', result.returncode, flush=True)
# Integrity validation must also run when the optional memory experiment fails.
with (base / 'dataset-metadata.jsonl').open('x') as f, (base / 'dataset-metadata.stderr').open('x') as err:
    subprocess.run([sys.executable, str(scripts / 'verify_dataset.py'),
                    '--roots', '/mnt/ssd0', '/mnt/ssd1', '--out', str(base / 'dataset-inventory.json')],
                   stdout=f, stderr=err, check=True)
print('dataset integrity PASS', flush=True)
