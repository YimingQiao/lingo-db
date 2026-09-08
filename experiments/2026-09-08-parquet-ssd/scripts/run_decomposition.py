"""CPU parallel-SUM and full eager-scan controls, after all other jobs finish."""
import itertools
import json
import os
from pathlib import Path
import random
import subprocess
import sys

base = Path('/home/ubuntu/parquet-results')
assert (base / 'dataset-inventory.json').is_file(), 'Run after dataset validation'
env = dict(os.environ, CUDA_VISIBLE_DEVICES='0', KVIKIO_COMPAT_MODE='ON', KVIKIO_NTHREADS='16')
cases = [(n, codec, 'cpu', cache, 'sum', 'cpu-parallel-sum')
         for n, codec, cache in itertools.product([1,2], ['none','snappy','zstd'], ['cold','warm'])
         if not (n == 1 and cache == 'warm')]
cases += [(2, codec, engine, cache, 'scan', 'scan-only')
          for codec, engine, cache in itertools.product(['none','snappy','zstd'], ['cpu','gpu'], ['cold','warm'])]
random.Random(20260909).shuffle(cases)
for n, codec, engine, cache, operation, folder in cases:
    directory = base / folder
    directory.mkdir(exist_ok=True)
    name = f'{engine}-{codec}-{n}disk-{cache}'
    path = directory / f'{name}.jsonl'
    assert not path.exists()
    cmd = [sys.executable, str(Path(__file__).with_name('bench.py')),
           '--roots', '/mnt/ssd0', '/mnt/ssd1', '--disks', str(n),
           '--codec', codec, '--engine', engine, '--cache', cache,
           '--threads', '32' if engine == 'cpu' else '16', '--batch', '8',
           '--cpu-reduce-threads', '16', '--operation', operation,
           '--devices', 'nvme1n1', 'nvme2n1']
    print(json.dumps({'case': f'{folder}/{name}', 'status': 'start'}), flush=True)
    with path.open('x') as f, (directory / f'{name}.stderr').open('x') as err:
        result = subprocess.run(cmd, env=env, stdout=f, stderr=err)
    with (directory / 'commands.jsonl').open('a') as log:
        log.write(json.dumps({'case': name, 'command': cmd, 'returncode': result.returncode}) + '\n')
    print(json.dumps({'case': f'{folder}/{name}', 'returncode': result.returncode}), flush=True)
    assert result.returncode == 0
