"""Byte-level layout equality and Parquet metadata; run OUTSIDE benchmark timing."""
import argparse
import hashlib
import json
from pathlib import Path
import pyarrow.parquet as pq

p = argparse.ArgumentParser()
p.add_argument('--roots', nargs='+', type=Path, required=True)
p.add_argument('--out', type=Path, required=True)
a = p.parse_args()
manifest = json.loads((a.roots[0] / 'manifest.json').read_text())
records = []
for codec in ['none', 'snappy', 'zstd']:
    files = sorted((a.roots[0] / 'disks1' / codec).glob('*.parquet'))
    assert len(files) == manifest['shards']
    metadata = pq.read_metadata(files[0])
    assert metadata.num_rows == manifest['rows_per_shard']
    for f in files:
        digest = None
        shard = int(f.stem.split('-')[1])
        for n in range(1, len(a.roots)+1):
            other = a.roots[shard % n] / f'disks{n}' / codec / f.name
            h = hashlib.sha256()
            with other.open('rb') as stream:
                while data := stream.read(8*1024*1024):
                    h.update(data)
            if digest is None:
                digest = h.hexdigest()
            assert h.hexdigest() == digest, other
        records.append(dict(codec=codec, shard=shard, bytes=f.stat().st_size, sha256=digest))
    print(json.dumps({'codec': codec, 'metadata': metadata.to_dict()}), flush=True)
a.out.write_text(json.dumps(dict(manifest=manifest, files=records), indent=2) + '\n')
