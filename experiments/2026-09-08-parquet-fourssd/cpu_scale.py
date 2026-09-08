"""Exploratory full-CPU sensitivity for the sublinear Zstd scaling case."""
import json
import os
from pathlib import Path
import random
import subprocess
import sys

base = Path(__file__).resolve().parent
old = base.parent/'2026-09-08-parquet-ssd/scripts'
out = base/'results/cpu48'
out.mkdir(exist_ok=True)
cpus = sorted(os.sched_getaffinity(0))
assert len(cpus) == 48, cpus
(out/'affinity.json').write_text(json.dumps({'cpus':cpus,'physical_cores':24},indent=2))
env = dict(os.environ,CUDA_VISIBLE_DEVICES='0',KVIKIO_COMPAT_MODE='ON',KVIKIO_NTHREADS='16')
cases = ['cold','warm']
random.Random(20260912).shuffle(cases)
for cache in cases:
    name = 'cpu-zstd-4disk-'+cache+'-scan'
    cmd = [sys.executable,str(old/'bench.py'),'--roots',*[f'/mnt/ssd{i}' for i in range(4)],'--devices',*[f'nvme{i}n1' for i in range(1,5)],'--disks','4','--codec','zstd','--engine','cpu','--cache',cache,'--operation','scan','--threads','48','--repeats','3']
    print(json.dumps({'case':name,'status':'start'}),flush=True)
    with (out/(name+'.jsonl')).open('x') as f,(out/(name+'.stderr')).open('x') as err:
        result = subprocess.run(cmd,env=env,stdout=f,stderr=err)
    with (out/'commands.jsonl').open('a') as log:
        log.write(json.dumps({'case':name,'command':cmd,'returncode':result.returncode})+'\n')
    assert result.returncode == 0,name
    print(json.dumps({'case':name,'status':'done'}),flush=True)
