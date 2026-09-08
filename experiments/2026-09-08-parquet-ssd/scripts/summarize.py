"""Validate raw records and emit deterministic Markdown medians/ranges."""
import argparse
import json
from pathlib import Path
import statistics as s

p = argparse.ArgumentParser()
p.add_argument('directory', type=Path)
p.add_argument('--out', type=Path)
a = p.parse_args()
lines = []
def emit(line):
    lines.append(line)
    print(line)
emit('| Case | N | Median s | Min–max s | File GB/s | Logical GB/s | Physical/file | CPU vCPU-eq |')
emit('|---|---:|---:|---:|---:|---:|---:|---:|')
reference = None
for f in sorted(a.directory.glob('*.jsonl')):
    if f.name == 'commands.jsonl':
        continue
    records = [json.loads(line) for line in f.read_text().splitlines() if line.strip()]
    assert len(records) == 3, f
    for r in records:
        if r.get('operation') == 'scan':
            assert r['rows'] == r['logical_bytes'] // (16*8), f
        if r['sums'] is not None:
            if reference is None:
                reference = r['sums']
            assert r['sums'] == reference, f
        fraction = sum(r['physical_read_bytes'].values())/r['file_bytes']
        if r['cache'] == 'cold':
            assert 0.98 <= fraction <= 1.05, (f, fraction)
        else:
            assert fraction < 0.01, (f, fraction)
    times = [r['seconds'] for r in records]
    median = s.median(times)
    file_bytes = records[0]['file_bytes']
    emit(f'| {f.stem} | {len(records)} | {median:.3f} | {min(times):.3f}–{max(times):.3f} | '
          f'{file_bytes/median/1e9:.3f} | {records[0]["logical_bytes"]/median/1e9:.3f} | '
          f'{s.median(sum(r["physical_read_bytes"].values())/file_bytes for r in records):.4f} | '
          f'{s.median(r["cpu_core_equivalents"] for r in records):.2f} |')
if a.out:
    a.out.write_text('\n'.join(lines) + '\n')
