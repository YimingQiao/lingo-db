"""Offline validation of the complete archived experiment; no GPU/deps needed."""
import argparse
import json
from pathlib import Path

p = argparse.ArgumentParser()
p.add_argument('results', type=Path)
a = p.parse_args()
inventory = json.loads((a.results / 'dataset-inventory.json').read_text())
manifest = inventory['manifest']
assert len(inventory['files']) == 384
sizes = {c: sum(f['bytes'] for f in inventory['files'] if f['codec'] == c)
         for c in ['none', 'snappy', 'zstd']}
counts = {'matrix': 24, 'resident': 6, 'batch32': 5, 'cpu-parallel-sum': 9, 'scan-only': 12}
observations = 0
for folder, count in counts.items():
    files = [f for f in (a.results / folder).glob('*.jsonl') if f.name != 'commands.jsonl']
    assert len(files) == count, (folder, len(files), count)
    for f in files:
        records = [json.loads(line) for line in f.read_text().splitlines()]
        assert len(records) == 3, f
        assert [r['repeat'] for r in records] == [0,1,2], f
        for r in records:
            observations += 1
            assert r['logical_bytes'] == manifest['logical_bytes'], f
            if r.get('sums') is not None:
                assert r['sums'] == manifest['sums'], f
            if r.get('operation') == 'scan':
                assert r['rows'] == manifest['rows_per_shard'] * manifest['shards'], f
            if folder == 'resident':
                assert r['read_decode_seconds'] > 0 and r['reduce_seconds'] > 0, f
                continue
            assert r['seconds'] > 0 and r['file_bytes'] == sizes[r['codec']], f
            fraction = sum(r['physical_read_bytes'].values())/r['file_bytes']
            assert (0.98 <= fraction <= 1.05) if r['cache'] == 'cold' else (fraction < 0.01), (f, fraction)
            if r['engine'] == 'gpu':
                assert r['kvikio_compat_mode'] == 'ON', 'Never relabel staged as GDS'
for name in ['ssd0-user', 'ssd0-root', 'ssd1-user', 'ssd1-root', 'native-gdsio']:
    assert json.loads((a.results / 'gds-probes' / f'{name}.json').read_text())['returncode'] != 0
assert json.loads((a.results / 'batch32-pool20/command.json').read_text())['returncode'] != 0
assert (a.results / 'failed/gpu-zstd-2disk-cold-batch32-pool16.stderr').is_file()
print(json.dumps({'validation': 'PASS', 'successful_cells': sum(counts.values()),
                  'timing_observations': observations,
                  'dataset_shards_per_layout': len(inventory['files']),
                  'gds_verified': False}, indent=2))
