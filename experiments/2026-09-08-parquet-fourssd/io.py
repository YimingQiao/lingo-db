"""Sustained aligned O_DIRECT reference, no Parquet decoding and no page cache."""
from concurrent.futures import ThreadPoolExecutor
import json
import mmap
import os
from pathlib import Path
import random
import time

out = Path(__file__).resolve().parent/'results'
os.sched_setaffinity(0,set(json.loads((out/'affinity.json').read_text())['cpus']))
def read(path):
    size = path.stat().st_size
    with mmap.mmap(-1,8*1024**2) as buf:
        fd = os.open(path,os.O_RDONLY|os.O_DIRECT)
        total = 0
        while total < size:
            count = os.readv(fd,[buf])
            assert count > 0
            total += count
        os.close(fd)
    assert total == size
    return total

def counters():
    return {f'nvme{i}n1':int(Path(f'/sys/block/nvme{i}n1/stat').read_text().split()[2])*512 for i in range(1,5)}

cases = [(n,t,r) for n in [1,2,4] for t in [8,32] for r in range(3)]
random.Random(20260911).shuffle(cases)
with (out/'sustained-io.jsonl').open('x') as log:
    for n,threads,repeat in cases:
        files = sorted((p for i in range(n) for p in Path(f'/mnt/ssd{i}/disks{n}/none').glob('*.parquet')),key=lambda p:p.name)
        assert len(files) == 512
        before = counters()
        start = time.perf_counter()
        deadline = start+30
        def worker(index):
            total = completed = 0
            position = index
            while time.perf_counter() < deadline:
                total += read(files[position%len(files)])
                completed += 1
                position += threads
            return total,completed
        with ThreadPoolExecutor(max_workers=threads) as pool:
            counts = list(pool.map(worker,range(threads)))
        total = sum(c[0] for c in counts)
        completed = sum(c[1] for c in counts)
        seconds = time.perf_counter()-start
        after = counters()
        row = dict(disks=n,threads=threads,repeat=repeat,seconds=seconds,files_completed=completed,equivalent_passes=total/sum(p.stat().st_size for p in files),file_bytes=total,file_GBps=total/seconds/1e9,physical_read_bytes={d:after[d]-before[d] for d in before})
        log.write(json.dumps(row)+'\n')
        log.flush()
        print(json.dumps(row),flush=True)
