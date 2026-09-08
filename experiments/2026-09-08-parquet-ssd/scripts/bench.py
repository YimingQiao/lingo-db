"""One isolated benchmark process; JSONL stdout, failures remain visible.

CPU/GPU perform the same full scan and SUM on ALL sixteen int64 columns.
No footer-only count, projection pruning, or predicate pruning is possible.
"""
import argparse
from concurrent.futures import ThreadPoolExecutor
import gc
import json
import mmap
import os
from pathlib import Path
import resource
import subprocess
import time

p = argparse.ArgumentParser()
p.add_argument('--roots', nargs='+', type=Path, required=True)
p.add_argument('--disks', type=int, required=True)
p.add_argument('--codec', choices=['none', 'snappy', 'zstd'], required=True)
p.add_argument('--engine', choices=['cpu', 'gpu', 'io'], required=True)
p.add_argument('--cache', choices=['cold', 'warm'], default='cold')
p.add_argument('--threads', type=int, default=32)
p.add_argument('--batch', type=int, default=8)
p.add_argument('--gpu-pool-max-gib', type=int, default=16)
p.add_argument('--cpu-reduce-threads', type=int, default=1)
p.add_argument('--operation', choices=['sum', 'scan'], default='sum')
p.add_argument('--repeats', type=int, default=3)
p.add_argument('--devices', nargs='+', required=True)
a = p.parse_args()
files = sorted((f for root in a.roots[:a.disks]
                for f in (root / f'disks{a.disks}' / a.codec).glob('*.parquet')),
               key=lambda f: f.name)
manifest = json.loads((a.roots[0] / 'manifest.json').read_text())
assert len(files) == manifest['shards'], (len(files), manifest['shards'])
disk_bytes = sum(f.stat().st_size for f in files)

def disk_counters():
    # Linux block stat sectors are ALWAYS 512 bytes, independent of LBA size.
    return {d: int(Path(f'/sys/block/{d}/stat').read_text().split()[2]) * 512
            for d in a.devices}

def cpu_usage():
    r = resource.getrusage(resource.RUSAGE_SELF)
    return r.ru_utime + r.ru_stime

def direct_read(path):
    size = path.stat().st_size
    with mmap.mmap(-1, 8 * 1024 * 1024) as buf:
        fd = os.open(path, os.O_RDONLY | os.O_DIRECT)
        read = 0
        while read < size:
            n = os.readv(fd, [buf])
            if not n:
                break
            read += n
        os.close(fd)
    assert read == size
    return read

if a.engine == 'cpu':
    import pyarrow as pa
    import pyarrow.compute as pc
    import pyarrow.parquet as pq
    pa.set_cpu_count(a.threads)
    pa.set_io_thread_count(a.threads)
    reduce_pool = ThreadPoolExecutor(max_workers=a.cpu_reduce_threads)

    def sum_column(column):
        return pc.sum(column).as_py()

    def scan(paths):
        table = pq.read_table([str(f) for f in paths], use_threads=True,
                              pre_buffer=True)
        # read_table is eager: every column has been materialized before this.
        if a.operation == 'scan':
            return [table.num_rows]
        if a.cpu_reduce_threads == 1:
            return [sum_column(c) for c in table.columns]
        return list(reduce_pool.map(sum_column, table.columns))

elif a.engine == 'gpu':
    import cupy as cp
    import cudf
    import rmm
    gpu_pool = rmm.mr.PoolMemoryResource(rmm.mr.CudaMemoryResource(),
                                        initial_pool_size=4*1024**3,
                                        maximum_pool_size=a.gpu_pool_max_gib*1024**3)
    rmm.mr.set_current_device_resource(gpu_pool)
    # Explicit single GPU selected by CUDA_VISIBLE_DEVICES in runner.
    def scan(paths):
        table = cudf.read_parquet([str(f) for f in paths])
        if a.operation == 'scan':
            cp.cuda.runtime.deviceSynchronize()
            return [len(table)]
        values = [int(table[f'c{i:02}'].sum()) for i in range(16)]
        cp.cuda.runtime.deviceSynchronize()
        return values

if a.engine != 'io':
    scan(files[:1])  # CUDA/runtime/JIT init excluded, cold data reset below.

for repeat in range(a.repeats):
    gc.collect()
    if a.cache == 'cold':
        os.sync()
        subprocess.run(['sudo', 'sysctl', '-q', 'vm.drop_caches=3'], check=True)
    else:
        # Warm filesystem page cache, but do NOT retain decoded data.
        for f in files:
            with f.open('rb', buffering=0) as stream:
                while stream.read(8 * 1024 * 1024):
                    pass
    before = disk_counters()
    cpu0 = cpu_usage()
    start = time.perf_counter()
    if a.engine == 'io':
        with ThreadPoolExecutor(max_workers=a.threads) as pool:
            actual = sum(pool.map(direct_read, files))
        sums = None
    else:
        sums = [0] * (16 if a.operation == 'sum' else 1)
        for offset in range(0, len(files), a.batch):
            sums = [x + y for x, y in zip(sums, scan(files[offset:offset+a.batch]))]
    seconds = time.perf_counter() - start
    cpu_seconds = cpu_usage() - cpu0
    after = disk_counters()
    rows = None
    if sums is not None and a.operation == 'scan':
        rows = sums[0]
        assert rows == manifest['shards'] * manifest['rows_per_shard']
        sums = None
    elif sums is not None:
        assert sums == manifest['sums'], (sums, manifest['sums'])
    physical = {d: after[d] - before[d] for d in before}
    result = dict(engine=a.engine, codec=a.codec, disks=a.disks, cache=a.cache,
                  threads=a.threads, batch=a.batch, repeat=repeat, seconds=seconds,
                  cpu_seconds=cpu_seconds, cpu_core_equivalents=cpu_seconds/seconds,
                  file_bytes=disk_bytes, logical_bytes=manifest['logical_bytes'],
                  file_GBps=disk_bytes/seconds/1e9,
                  logical_GBps=manifest['logical_bytes']/seconds/1e9,
                  physical_read_bytes=physical,
                  physical_read_GBps=sum(physical.values())/seconds/1e9,
                  sums=sums, kvikio_compat_mode=os.environ.get('KVIKIO_COMPAT_MODE'),
                  operation=a.operation, rows=rows,
                  cpu_reduce_threads=a.cpu_reduce_threads if a.engine == 'cpu' else None,
                  gpu_pool_initial_GiB=4 if a.engine == 'gpu' else None,
                  gpu_pool_max_GiB=a.gpu_pool_max_gib if a.engine == 'gpu' else None,
                  cufile_config=os.environ.get('CUFILE_ENV_PATH_JSON'))
    print(json.dumps(result), flush=True)
