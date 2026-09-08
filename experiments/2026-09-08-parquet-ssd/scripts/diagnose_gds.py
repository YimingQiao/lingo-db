"""Record failed/successful strict attempts without converting them to benchmarks."""
import json
import os
from pathlib import Path
import subprocess
import sys

out = Path('/home/ubuntu/parquet-results/gds-probes')
out.mkdir(parents=True, exist_ok=True)
env = dict(os.environ, CUDA_VISIBLE_DEVICES='0', KVIKIO_COMPAT_MODE='OFF',
           CUFILE_ENV_PATH_JSON='/home/ubuntu/parquet-experiment/cufile-strict.json')
for disk in [0, 1]:
    for root in [False, True]:
        name = f'ssd{disk}-' + ('root' if root else 'user')
        cmd = [sys.executable, str(Path(__file__).with_name('probe_gds.py')),
               '--root', f'/mnt/ssd{disk}']
        if root:
            cmd = ['sudo', 'env', *[f'{k}={env[k]}' for k in
                    ['CUDA_VISIBLE_DEVICES', 'KVIKIO_COMPAT_MODE', 'CUFILE_ENV_PATH_JSON']], *cmd]
        result = subprocess.run(cmd, env=env, capture_output=True, text=True)
        (out / f'{name}.stdout').write_text(result.stdout)
        (out / f'{name}.stderr').write_text(result.stderr)
        (out / f'{name}.json').write_text(json.dumps({'command': cmd, 'returncode': result.returncode}, indent=2))
        print(name, result.returncode, flush=True)
result = subprocess.run(['sudo', 'dmesg'], capture_output=True, text=True, check=True)
(out / 'kernel-nvme.txt').write_text('\n'.join(line for line in result.stdout.splitlines()
                                            if 'nvme' in line.lower() or 'p2pdma' in line.lower()) + '\n')
