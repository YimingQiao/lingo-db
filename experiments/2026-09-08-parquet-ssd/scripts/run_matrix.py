"""Sequential isolated processes; randomized case order; durable raw logs."""
import argparse
import itertools
import json
import os
from pathlib import Path
import random
import subprocess
import sys
import time

p = argparse.ArgumentParser()
p.add_argument('--roots', nargs='+', required=True)
p.add_argument('--out', type=Path, required=True)
p.add_argument('--gds', action='store_true', help='ONLY after strict probe succeeds')
p.add_argument('--config', type=Path)
p.add_argument('--repeats', type=int, default=3)
a = p.parse_args()
a.out.mkdir(parents=True, exist_ok=True)
cases = list(itertools.product(range(1, len(a.roots)+1), ['none', 'snappy', 'zstd'],
                              ['cpu', 'gpu', 'io'], ['cold']))
cases += [(2, c, e, 'warm') for c in ['none', 'snappy', 'zstd'] for e in ['cpu', 'gpu']]
if a.gds:
    assert a.config and a.config.is_file()
    cases += [(n, c, 'gds', 'cold') for n in range(1, len(a.roots)+1)
              for c in ['none', 'snappy', 'zstd']]
random.Random(20260908).shuffle(cases)
for n, codec, route, cache in cases:
    key = f'{route}-{codec}-{n}disk-{cache}'
    destination = a.out / f'{key}.jsonl'
    assert not destination.exists(), f'Refusing to overwrite {destination}'
    env = dict(os.environ, CUDA_VISIBLE_DEVICES='0', KVIKIO_COMPAT_MODE='OFF' if route == 'gds' else 'ON',
               KVIKIO_NTHREADS='16')
    if route == 'gds':
        env['CUFILE_ENV_PATH_JSON'] = str(a.config.resolve())
    cmd = [sys.executable, str(Path(__file__).with_name('bench.py')),
           '--roots', *a.roots, '--disks', str(n), '--codec', codec,
           '--engine', 'gpu' if route == 'gds' else route,
           '--cache', cache, '--threads', '32' if route == 'cpu' else '16',
           '--batch', '8', '--repeats', str(a.repeats),
           '--devices', 'nvme1n1', 'nvme2n1']
    print(json.dumps(dict(case=key, status='start', utc=time.strftime('%FT%TZ', time.gmtime()))), flush=True)
    with destination.open('x') as out, (a.out / f'{key}.stderr').open('x') as err:
        result = subprocess.run(cmd, env=env, stdout=out, stderr=err)
    with (a.out / 'commands.jsonl').open('a') as log:
        log.write(json.dumps(dict(case=key, command=cmd, returncode=result.returncode,
                                  env={k: env[k] for k in ['CUDA_VISIBLE_DEVICES', 'KVIKIO_COMPAT_MODE', 'KVIKIO_NTHREADS']},
                                  config=env.get('CUFILE_ENV_PATH_JSON'))) + '\n')
    print(json.dumps(dict(case=key, returncode=result.returncode)), flush=True)
    # CPU/staged failure is not silently ignored. Optional GDS is independently gated.
    assert result.returncode == 0, key
