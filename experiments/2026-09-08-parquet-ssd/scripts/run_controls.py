"""Run after matrix: resident decode, batch sensitivity, integrity validation."""
import json
import os
from pathlib import Path
import subprocess
import sys

base = Path('/home/ubuntu/parquet-results')
scripts = Path(__file__).parent
env = dict(os.environ, CUDA_VISIBLE_DEVICES='0', KVIKIO_COMPAT_MODE='ON', KVIKIO_NTHREADS='16')

# Independent native tool uses the apt-installed cuFile, not Python's wheel.
native_cmd = ['sudo', 'env', 'CUFILE_ENV_PATH_JSON=/home/ubuntu/parquet-experiment/cufile-strict.json',
              '/usr/local/cuda/gds/tools/gdsio', '-f', '/mnt/ssd0/gds-probe.bin',
              '-d', '0', '-w', '1', '-s', '8M', '-i', '1M', '-I', '0', '-x', '0', '-T', '1']
native = subprocess.run(native_cmd, capture_output=True, text=True, timeout=60)
(base / 'gds-probes/native-gdsio.stdout').write_text(native.stdout)
(base / 'gds-probes/native-gdsio.stderr').write_text(native.stderr)
(base / 'gds-probes/native-gdsio.json').write_text(json.dumps(
    {'command': native_cmd, 'returncode': native.returncode}, indent=2))

def run(name, cmd):
    path = base / name
    path.parent.mkdir(parents=True, exist_ok=True)
    assert not path.exists(), path
    print(json.dumps({'case': name, 'status': 'start'}), flush=True)
    with path.open('x') as f, path.with_suffix('.stderr').open('x') as err:
        result = subprocess.run(cmd, env=env, stdout=f, stderr=err)
    print(json.dumps({'case': name, 'returncode': result.returncode}), flush=True)
    assert result.returncode == 0, name

# First matrix case overlapped the final diagnostic cache eviction during its
# preload. Retain the invalid original and rerun the entire three-repeat cell.
excluded = base / 'excluded'
excluded.mkdir(exist_ok=True)
for suffix in ['jsonl', 'stderr']:
    src = base / 'matrix' / f'cpu-snappy-2disk-warm.{suffix}'
    dst = excluded / f'cpu-snappy-2disk-warm-overlapped-probe.{suffix}'
    assert not dst.exists()
    src.rename(dst)
run('matrix/cpu-snappy-2disk-warm.jsonl',
    [sys.executable, str(scripts / 'bench.py'), '--roots', '/mnt/ssd0', '/mnt/ssd1',
     '--disks', '2', '--codec', 'snappy', '--engine', 'cpu', '--cache', 'warm',
     '--threads', '32', '--batch', '8', '--devices', 'nvme1n1', 'nvme2n1'])

for codec in ['none', 'snappy', 'zstd']:
    for engine in ['cpu', 'gpu']:
        run(f'resident/{engine}-{codec}.jsonl',
            [sys.executable, str(scripts / 'resident.py'), '--root', '/mnt/ssd0',
             '--codec', codec, '--engine', engine])
        run(f'batch32/{engine}-{codec}-2disk-cold.jsonl',
            [sys.executable, str(scripts / 'bench.py'), '--roots', '/mnt/ssd0', '/mnt/ssd1',
             '--disks', '2', '--codec', codec, '--engine', engine, '--cache', 'cold',
             '--threads', '32' if engine == 'cpu' else '16', '--batch', '32',
             '--devices', 'nvme1n1', 'nvme2n1'])
run('dataset-metadata.jsonl', [sys.executable, str(scripts / 'verify_dataset.py'),
                             '--roots', '/mnt/ssd0', '/mnt/ssd1', '--out',
                             str(base / 'dataset-inventory.json')])
