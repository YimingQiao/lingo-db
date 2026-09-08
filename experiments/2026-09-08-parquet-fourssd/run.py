"""Sequential randomized cold/warm scans; no overlapping cache-drop processes."""
import itertools
import json
import os
from pathlib import Path
import random
import subprocess
import sys

base = Path(__file__).resolve().parent
old = base.parent/'2026-09-08-parquet-ssd/scripts'
out = base/'results'
out.mkdir(exist_ok=True)
topology = subprocess.check_output(['lscpu','-p=CPU,CORE,SOCKET'], text=True)
cores = {}
for line in topology.splitlines():
    if line.startswith('#'):
        continue
    cpu, core, socket = map(int,line.split(','))
    cores.setdefault((socket,core),[]).append(cpu)
chosen = sorted(c for k in sorted(cores)[:16] for c in cores[k])
assert len(chosen) == 32
(out/'affinity.json').write_text(json.dumps({'cpus':chosen,'physical_cores':16},indent=2))
affinity = ','.join(map(str,chosen))
env = dict(os.environ,CUDA_VISIBLE_DEVICES='0',KVIKIO_COMPAT_MODE='ON',KVIKIO_NTHREADS='16')
roots = ['/mnt/ssd'+str(i) for i in range(4)]
cases = [(n,c,e,'cold','scan') for n,c,e in itertools.product([1,2,4],['none','snappy','zstd'],['cpu','gpu'])]
cases += [(4,c,e,'warm','scan') for c,e in itertools.product(['none','snappy','zstd'],['cpu','gpu'])]
cases += [(n,c,e,'cold','sum') for n,c,e in itertools.product([2,4],['snappy','zstd'],['cpu','gpu'])]
random.Random(20260910).shuffle(cases)
for n,c,e,cache,op in cases:
    name = f'{e}-{c}-{n}disk-{cache}-{op}'
    cmd = ['taskset','-c',affinity,sys.executable,str(old/'bench.py'),'--roots',*roots,'--devices','nvme1n1','nvme2n1','nvme3n1','nvme4n1','--disks',str(n),'--codec',c,'--engine',e,'--cache',cache,'--operation',op,'--threads','32','--cpu-reduce-threads','16','--repeats','5']
    print(json.dumps({'case':name,'status':'start'}),flush=True)
    with (out/(name+'.jsonl')).open('x') as f, (out/(name+'.stderr')).open('x') as err:
        result = subprocess.run(cmd,env=env,stdout=f,stderr=err)
    with (out/'commands.jsonl').open('a') as log:
        log.write(json.dumps({'case':name,'command':cmd,'returncode':result.returncode})+'\n')
    assert result.returncode == 0, name
    print(json.dumps({'case':name,'status':'done'}),flush=True)
