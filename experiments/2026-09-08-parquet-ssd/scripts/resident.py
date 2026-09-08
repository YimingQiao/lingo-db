"""Isolated read/decode and reduction controls; excludes SSD and H2D input copy.

Batch inputs are preloaded before timing, not the whole 16 GiB decoded dataset.
CPU uses host bytes; GPU uses compressed rmm.DeviceBuffers and pylibcudf.
This is a diagnostic microbenchmark, NOT end-to-end SSD performance.
"""
import argparse
from concurrent.futures import ThreadPoolExecutor
import gc
import json
from pathlib import Path
import time

import pyarrow as pa
import pyarrow.compute as pc
import pyarrow.parquet as pq

p = argparse.ArgumentParser()
p.add_argument('--root', type=Path, required=True)
p.add_argument('--codec', required=True)
p.add_argument('--engine', choices=['cpu', 'gpu'], required=True)
p.add_argument('--repeats', type=int, default=3)
p.add_argument('--batch', type=int, default=8)
a = p.parse_args()
files = sorted((a.root / 'disks1' / a.codec).glob('*.parquet'))
manifest = json.loads((a.root / 'manifest.json').read_text())
assert len(files) == manifest['shards']
pa.set_cpu_count(32)
if a.engine == 'gpu':
    import cupy as cp
    import pylibcudf as plc
    import rmm
    pool = rmm.mr.PoolMemoryResource(rmm.mr.CudaMemoryResource(),
                                     initial_pool_size=4*1024**3,
                                     maximum_pool_size=16*1024**3)
    rmm.mr.set_current_device_resource(pool)
    agg = plc.aggregation.sum()
    dtype = plc.DataType(plc.TypeId.INT64)

    def prepare(paths):
        values = [rmm.DeviceBuffer.to_device(memoryview(f.read_bytes())) for f in paths]
        cp.cuda.runtime.deviceSynchronize()
        return values

    def read(values):
        options = plc.io.parquet.ParquetReaderOptions.builder(plc.io.SourceInfo(values)).build()
        table = plc.io.parquet.read_parquet(options).tbl
        cp.cuda.runtime.deviceSynchronize()
        return table

    def reduce(table):
        return [plc.reduce.reduce(c, agg, dtype).to_arrow().as_py() for c in table.columns()]
else:
    executor = ThreadPoolExecutor(max_workers=a.batch)

    def prepare(paths):
        return [f.read_bytes() for f in paths]

    def read_one(value):
        return pq.read_table(pa.BufferReader(value), use_threads=True)

    def read(values):
        return pa.concat_tables(list(executor.map(read_one, values)))

    def reduce(table):
        return [pc.sum(c).as_py() for c in table.columns]

reduce(read(prepare(files[:1])))
for repeat in range(a.repeats):
    times = {'read_decode_seconds': 0.0, 'reduce_seconds': 0.0}
    sums = [0] * 16
    for offset in range(0, len(files), a.batch):
        values = prepare(files[offset:offset+a.batch])
        start = time.perf_counter()
        table = read(values)
        read_end = time.perf_counter()
        partial = reduce(table)
        end = time.perf_counter()
        times['read_decode_seconds'] += read_end - start
        times['reduce_seconds'] += end - read_end
        sums = [x+y for x,y in zip(sums, partial)]
        del table, values
        gc.collect()
    assert sums == manifest['sums']
    print(json.dumps(dict(engine=a.engine, codec=a.codec, repeat=repeat,
                          source='VRAM' if a.engine == 'gpu' else 'host_bytes',
                          batch=a.batch, logical_bytes=manifest['logical_bytes'],
                          logical_decode_GBps=manifest['logical_bytes']/times['read_decode_seconds']/1e9,
                          sums=sums, **times)), flush=True)
