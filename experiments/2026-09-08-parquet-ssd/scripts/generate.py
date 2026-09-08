"""Deterministic Parquet data; identical rows/codecs/layouts, no external data."""
import argparse
import json
from pathlib import Path
import shutil

import numpy as np
import pyarrow as pa
import pyarrow.parquet as pq

p = argparse.ArgumentParser()
p.add_argument('--roots', nargs='+', required=True, type=Path)
p.add_argument('--shards', type=int, default=128)
p.add_argument('--rows', type=int, default=1048576)
a = p.parse_args()
assert all(root.is_dir() for root in a.roots)
checks = [0] * 16
for shard in range(a.shards):
    rng = np.random.default_rng(20260908 + shard)
    # Plain int64 pages isolate codec effects from dictionary/bit-pack encoding.
    # Four entropy levels; high bits are zero, useful but nontrivial compression.
    columns = [rng.integers(0, 2 ** (8 * (1 + i % 4)), a.rows, dtype=np.int64)
               for i in range(16)]
    table = pa.table({f'c{i:02}': col for i, col in enumerate(columns)})
    checks = [x + int(col.sum()) for x, col in zip(checks, columns)]
    for codec in ['none', 'snappy', 'zstd']:
        for n in range(1, len(a.roots) + 1):
            dest = a.roots[shard % n] / f'disks{n}' / codec / f'part-{shard:04}.parquet'
            dest.parent.mkdir(parents=True, exist_ok=True)
            if n == 1:
                pq.write_table(table, dest, compression=None if codec == 'none' else codec,
                               compression_level=3 if codec == 'zstd' else None,
                               use_dictionary=False, row_group_size=262144,
                               data_page_size=1048576, write_statistics=False,
                               version='2.6')
                source = dest
            else:
                shutil.copyfile(source, dest)
    if shard % 8 == 0:
        print(json.dumps({'generated_shards': shard + 1}), flush=True)
manifest = dict(seed=20260908, shards=a.shards, rows_per_shard=a.rows,
                columns=16, dtype='int64', logical_bytes=a.shards*a.rows*16*8,
                row_group_rows=262144, page_bytes=1048576, dictionary=False,
                statistics=False, sums=checks)
for root in a.roots:
    (root / 'manifest.json').write_text(json.dumps(manifest, indent=2) + '\n')
print(json.dumps(manifest), flush=True)
