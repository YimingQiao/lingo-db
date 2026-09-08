"""Read-only progress summary; never alters page cache or dataset."""
import json
from pathlib import Path
import statistics

out = Path(__file__).resolve().parent/'results'
for name in ['generate-parallel.jsonl','run.log','io.log']:
    path = out/name
    if path.exists():
        lines = path.read_text().splitlines()
        if name == 'generate-parallel.jsonl' and lines and 'logical_bytes' in lines[-1]:
            print('Generation complete: 512 shards, 64 GiB logical')
        else:
            print(name, '\n'.join(lines[-2:]))
records = []
for path in sorted(out.glob('*disk-*.jsonl')):
    rows = [json.loads(x) for x in path.read_text().splitlines() if x.endswith('}')]
    if rows:
        records.append({'case':path.stem,'n':len(rows),'seconds':round(statistics.median(r['seconds'] for r in rows),3),'file_GBps':round(statistics.median(r['file_GBps'] for r in rows),3),'cpu_equiv':round(statistics.median(r['cpu_core_equivalents'] for r in rows),2)})
print('Completed cases:',sum(r['n']==5 for r in records),'/32')
for r in records:
    print(r['case'],r['n'],r['seconds'],'s',r['file_GBps'],'GB/s',r['cpu_equiv'],'CPU')
