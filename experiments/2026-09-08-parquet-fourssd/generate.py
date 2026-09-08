"""Parallel deterministic generator, identical shard encoding to the first run."""
from concurrent.futures import ProcessPoolExecutor
import json
from pathlib import Path
import shutil
import numpy as np
import pyarrow as pa
import pyarrow.parquet as pq

roots = [Path('/mnt/ssd'+str(i)) for i in range(4)]
rows = 1048576
shards = 512

def generate(shard):
    rng = np.random.default_rng(20260908+shard)
    cols = [rng.integers(0,2**(8*(1+i%4)),rows,dtype=np.int64) for i in range(16)]
    table = pa.table({f'c{i:02}':c for i,c in enumerate(cols)})
    for codec in ['none','snappy','zstd']:
        source = roots[0]/'disks1'/codec/f'part-{shard:04}.parquet'
        source.parent.mkdir(parents=True,exist_ok=True)
        pq.write_table(table,source,compression=None if codec=='none' else codec,
                       compression_level=3 if codec=='zstd' else None,
                       use_dictionary=False,row_group_size=262144,data_page_size=1048576,
                       write_statistics=False,version='2.6')
        for n in [2,3,4]:
            dest = roots[shard%n]/f'disks{n}'/codec/source.name
            dest.parent.mkdir(parents=True,exist_ok=True)
            shutil.copyfile(source,dest)
    return [int(c.sum()) for c in cols]

if __name__ == '__main__':
    assert all(p.is_mount() for p in roots)
    checks = [0]*16
    with ProcessPoolExecutor(max_workers=4) as pool:
        for shard,sums in enumerate(pool.map(generate,range(shards))):
            checks = [a+b for a,b in zip(checks,sums)]
            if shard%8 == 0:
                print(json.dumps({'generated_shards':shard+1}),flush=True)
    manifest = dict(seed=20260908,shards=shards,rows_per_shard=rows,columns=16,dtype='int64',logical_bytes=shards*rows*16*8,row_group_rows=262144,page_bytes=1048576,dictionary=False,statistics=False,sums=checks)
    for root in roots:
        (root/'manifest.json').write_text(json.dumps(manifest,indent=2)+'\n')
    print(json.dumps(manifest),flush=True)
