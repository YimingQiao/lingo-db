"""Offline audit and summary; needs only Python's standard library."""
import argparse
import json
from pathlib import Path
import statistics

p = argparse.ArgumentParser()
p.add_argument('--primary-only',action='store_true',help='Audit 160 main records only; do not claim controls complete')
a = p.parse_args()

base = Path(__file__).resolve().parent
out = base/'results'
inventory = json.loads((out/'dataset-inventory.json').read_text())
manifest = inventory['manifest']
previous = json.loads((base.parent/'2026-09-08-parquet-ssd/results/dataset-inventory.json').read_text())
hashes = {(r['codec'],r['shard']):r['sha256'] for r in inventory['files']}
assert all(hashes[(r['codec'],r['shard'])] == r['sha256'] for r in previous['files'])
commands = [json.loads(x) for x in (out/'commands.jsonl').read_text().splitlines()]
assert len(commands) == 32
assert len({c['case'] for c in commands}) == 32
summary = []
for command in commands:
    assert command['returncode'] == 0
    rows = [json.loads(x) for x in (out/(command['case']+'.jsonl')).read_text().splitlines()]
    assert len(rows) == 5 and {r['repeat'] for r in rows} == set(range(5))
    for r in rows:
        assert r['logical_bytes'] == 64*1024**3
        assert r['batch'] == 8 and r['threads'] == 32
        assert r['kvikio_compat_mode'] == 'ON'
        assert r['seconds'] > 0
        expected_bytes = sum(f['bytes'] for f in inventory['files'] if f['codec'] == r['codec'])
        assert expected_bytes == r['file_bytes']
        ratio = sum(r['physical_read_bytes'].values())/r['file_bytes']
        assert (0.95 < ratio < 1.15) if r['cache'] == 'cold' else ratio < 0.02, (command['case'],ratio)
        if r['cache'] == 'cold':
            for index in range(4):
                expected = sum(f['bytes'] for f in inventory['files'] if f['codec'] == r['codec'] and f['shard']%r['disks'] == index)
                observed = r['physical_read_bytes'][f'nvme{index+1}n1']
                assert abs(observed-expected) < max(16*1024**2,0.15*expected), (command['case'],index,observed,expected)
        if r['operation'] == 'sum':
            assert r['sums'] == manifest['sums']
        else:
            assert r['rows'] == manifest['shards']*manifest['rows_per_shard']
    summary.append(dict(case=command['case'],engine=rows[0]['engine'],codec=rows[0]['codec'],disks=rows[0]['disks'],cache=rows[0]['cache'],operation=rows[0]['operation'],seconds=statistics.median(r['seconds'] for r in rows),min_seconds=min(r['seconds'] for r in rows),max_seconds=max(r['seconds'] for r in rows),file_GBps=statistics.median(r['file_GBps'] for r in rows),cpu_core_equivalents=statistics.median(r['cpu_core_equivalents'] for r in rows)))
if a.primary_only:
    print(json.dumps({'validation':'PRIMARY_PASS','scan_records':160,'controls':'not checked'}))
    raise SystemExit(0)
io = [json.loads(x) for x in (out/'sustained-io.jsonl').read_text().splitlines()]
assert len(io) == 18
for r in io:
    assert r['seconds'] >= 30
    assert 0.99 < sum(r['physical_read_bytes'].values())/r['file_bytes'] < 1.05
io_summary = []
for disks in [1,2,4]:
    for threads in [8,32]:
        rows = [r for r in io if r['disks']==disks and r['threads']==threads]
        assert len(rows)==3 and {r['repeat'] for r in rows} == {0,1,2}
        io_summary.append(dict(disks=disks,threads=threads,GBps=statistics.median(r['file_GBps'] for r in rows),min_GBps=min(r['file_GBps'] for r in rows),max_GBps=max(r['file_GBps'] for r in rows)))
cpu48 = []
extra = out/'cpu48'
extra_commands = [json.loads(x) for x in (extra/'commands.jsonl').read_text().splitlines()]
assert len(extra_commands) == 2 and all(c['returncode']==0 for c in extra_commands)
assert len(json.loads((extra/'affinity.json').read_text())['cpus']) == 48
for command in extra_commands:
    rows = [json.loads(x) for x in (extra/(command['case']+'.jsonl')).read_text().splitlines()]
    assert len(rows)==3 and {r['repeat'] for r in rows} == {0,1,2}
    for r in rows:
        assert r['threads']==48 and r['engine']=='cpu' and r['codec']=='zstd' and r['disks']==4
        assert r['operation']=='scan' and r['batch']==8 and r['logical_bytes']==64*1024**3
        assert r['rows']==manifest['shards']*manifest['rows_per_shard']
        assert r['file_bytes']==sum(f['bytes'] for f in inventory['files'] if f['codec']=='zstd')
        ratio = sum(r['physical_read_bytes'].values())/r['file_bytes']
        assert (0.95 < ratio < 1.15) if r['cache']=='cold' else ratio < .02
    cpu48.append(dict(case=command['case'],cache=rows[0]['cache'],seconds=statistics.median(r['seconds'] for r in rows),min_seconds=min(r['seconds'] for r in rows),max_seconds=max(r['seconds'] for r in rows),file_GBps=statistics.median(r['file_GBps'] for r in rows),cpu_core_equivalents=statistics.median(r['cpu_core_equivalents'] for r in rows)))
result = dict(validation='PASS',scan_records=160,io_records=18,cpu_sensitivity_records=6,cases=sorted(summary,key=lambda r:r['case']),io=io_summary,cpu48=cpu48)
(out/'summary.json').write_text(json.dumps(result,indent=2)+'\n')
lines = ['| Case | Median s | Min–max s | File GB/s | CPU equivalents |','|---|---:|---:|---:|---:|']
for r in result['cases']:
    lines.append(f"| {r['case']} | {r['seconds']:.3f} | {r['min_seconds']:.3f}–{r['max_seconds']:.3f} | {r['file_GBps']:.3f} | {r['cpu_core_equivalents']:.2f} |")
(out/'summary.md').write_text('\n'.join(lines)+'\n')
print(json.dumps(result,indent=2))
