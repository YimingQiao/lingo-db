# G6 four-SSD Parquet scaling experiment

**Complete: all 184 records pass the offline audit.** The instance is terminated,
its root EBS volume is deleted, and the temporary cloud SSH key registration is removed.

**Bottom line:** four local SSDs scale delivered storage bandwidth to about
2.5–2.6 GB/s, but do not saturate the GPU processing path. None/Snappy cold scans
remain strongly storage-limited. CPU Zstd shows mixed processing/I/O limits;
using all CPU cores reduces, but does not remove, the observed GPU advantage.

## Question and scope

Does increasing local SSD parallelism from one to two to four feed enough
compressed Parquet data to make processing, rather than storage, the bottleneck?

This compares eager PyArrow CPU scans and single-L4 cuDF scans. It is not a
LingoDB query-engine benchmark. GPU reads use **KvikIO compatibility mode ON**,
through host memory: these are **not GDS measurements**. GPU processing includes
Parquet parsing/decoding/decompression and allocation, not codec kernels alone.

## Controlled setup

- One disposable AWS `g6.12xlarge`, `us-west-2d`, On-Demand $4.6016/hour compute.
  Including 150 GiB gp3 root and public IPv4, approximately $4.62/hour, within
  the user's $5/hour cap. Local SSD data never resides on root EBS.
- Four 940 GB decimal NVMe instance-store disks, independent ext4 mounts.
  Empty DLAMI LVM scratch storage was checked before preparation; no existing
  user data or root EBS was formatted.
- AMD EPYC 7R13, 48 logical CPUs / 24 physical cores, one visible NUMA node,
  192 GiB instance RAM. Primary comparisons fix **16 physical cores + SMT**:
  CPUs `0–15,24–39`, 32 logical CPUs. Only GPU 0 is exposed (one L4, 23034 MiB
  reported VRAM), although the instance physically contains four L4s.
- Same driver/library versions as archived in `results/environment/`: NVIDIA
  595.91.07, cuDF 26.8.1, KvikIO 26.8.0, PyArrow 23.0.1, NumPy 2.4.6.
  Exact dependency freeze is included. CUDA initialization is outside timing.
- 512 shards × 1,048,576 rows × 16 int64 columns = **64 GiB logical payload**.
  Four repeated entropy levels (8/16/24/32 random bits); seeded per shard.
  Plain Parquet encoding, dictionary and statistics disabled, 262,144-row groups,
  1 MiB target pages; no compression, Snappy, or Zstd level 3.
- Every disk layout has byte-identical copies of all shards, verified by SHA-256.
  The first 128 shards in all three codecs also exactly match the previous run's
  384 hashes. The full dataset is four times larger than that earlier run.
- Eight files per batch (1 GiB decoded), fixed 4–16 GiB RMM pool. Primary CPU
  Arrow pools use 32 threads; CPU SUM controls use a separate 16-worker reduction
  pool. All columns are materialized. SUM cases check all 16 generated sums.
- Cold runs sync and drop the exclusive host's Linux page cache; per-NVMe sector
  counters verify physical reads. Warm runs preload compressed file bytes only,
  never decoded tables. This controls the OS cache, not SSD-controller/NAND caches.
- Main cases execute sequentially in seeded random order, five repeats per cell.
  Report medians and ranges, not best samples; no significance test is claimed.

## Dataset byte domains

All three codecs contain the same 68,719,476,736 decoded bytes (64 GiB).
Throughput named `file_GBps` uses actual compressed Parquet bytes, not that decoded
payload. Decimal GB/s and binary GiB capacity are deliberately distinguished.

| Codec | Parquet bytes per complete layout | Decimal GB |
|---|---:|---:|
| None | 68,737,196,544 | 68.737 |
| Snappy | 39,735,047,227 | 39.735 |
| Zstd-3 | 23,501,256,498 | 23.501 |

## Cold eager-scan medians

Seconds for the entire 64 GiB logical dataset, without SUM.

| Codec | CPU 1 SSD | CPU 2 SSD | CPU 4 SSD | GPU 1 SSD | GPU 2 SSD | GPU 4 SSD |
|---|---:|---:|---:|---:|---:|---:|
| None | 108.213 | 53.616 | 26.322 | 108.209 | 53.638 | 26.407 |
| Snappy | 62.151 | 30.589 | 14.824 | 62.158 | 30.603 | 14.859 |
| Zstd-3 | 36.454 | 17.807 | 10.848 | 36.395 | 17.728 | 8.520 |

## Warm eager-scan medians

Same four-disk layout and batch size, but compressed bytes are in OS page cache.
These timings still include memory movement, parsing, decoding and allocation.

| Codec | CPU seconds | GPU seconds |
|---|---:|---:|
| None | 5.271 | 6.148 |
| Snappy | 8.079 | 5.255 |
| Zstd-3 | 7.526 | 5.746 |

The CPU is faster for the warm uncompressed workload. A GPU advantage is not
universal: GPU staging/movement and the workload's decoding costs both matter.

## Full scan plus SUM controls

Same full materialization followed by SUM on all sixteen columns. CPU reduction
uses 16 workers, not the serial-column reduction used in the initial earlier run.
These are separate end-to-end measurements; do not subtract scan medians to
estimate isolated SUM time or add overlapping pipeline phase times.

| Codec | CPU 2 SSD | CPU 4 SSD | GPU 2 SSD | GPU 4 SSD |
|---|---:|---:|---:|---:|
| Snappy | 30.611 | 14.905 | 30.615 | 14.870 |
| Zstd-3 | 17.735 | 12.011 | 17.738 | 9.234 |

## Sustained O_DIRECT storage reference

No Parquet decoding: 8 MiB aligned reads, 8 or 32 workers, same primary CPU
affinity, three samples per setting. Workers finish the current file after a
shared 30-second deadline; the record contains actual duration and bytes read.
All eighteen samples ran after the main matrix without overlapping other jobs.

| SSDs | Read threads | Median GB/s | Min–max GB/s |
|---|---:|---:|---:|
| 1 | 8 | 0.630 | 0.630–0.630 |
| 1 | 32 | 0.635 | 0.633–0.635 |
| 2 | 8 | 1.259 | 1.256–1.277 |
| 2 | 32 | 1.273 | 1.272–1.273 |
| 4 | 8 | 2.572 | 2.534–2.620 |
| 4 | 32 | 2.518 | 2.518–2.550 |

The delivered four-disk reference is approximately **2.5–2.6 GB/s**, not the
high-single-digit or tens-of-GB/s regime. Increasing reader threads does not
unlock materially more bandwidth. This is an observed request pattern, not a
universal hardware maximum: buffered Parquet readers reached 2.6–2.8 GB/s, and
some compressed four-disk scans still last only 8–15 seconds. Do not interpret
slightly superlinear scaling ratios as a proven architectural effect.

## Full-CPU sensitivity: avoid overstating the GPU advantage

The primary matrix deliberately fixes the same 16 physical cores / 32 logical
CPUs across all disk counts. An exploratory follow-up uses the instance's full
24 physical cores / 48 logical CPUs, with the same files, batch size and eager
Zstd scan, three repeats per cold/warm cell. It runs after all other measurements.

| Configuration | Four-disk cold seconds | Warm seconds |
|---|---:|---:|
| CPU, 16 physical / 32 logical cores | 10.848 | 7.526 |
| CPU, 24 physical / 48 logical cores | 9.980 | 6.347 |
| One L4, staged I/O, 32-logical-CPU host affinity | 8.520 | 5.746 |

Full-CPU cold range: 9.979–10.034 s; warm range: 6.316–6.384 s.
The GPU's cold-scan speedup falls from **1.27× versus CPU32 to 1.17× versus
CPU48**. More CPU resources improve cold performance by about 1.09× and warm
performance by about 1.19×. CPU resource allocation therefore matters, and the
fixed-CPU result must not be presented as a comparison against all available CPUs.
Even CPU48 remains materially slower cold than warm (9.980 versus 6.347 s).

## Conclusions

1. GPU Snappy scales 62.158 → 30.603 → 14.859 s (1/2/4 SSDs), approximately
   proportional to disk count. CPU/GPU four-disk Snappy times are nearly equal.
2. CPU none improves 53.616 → 26.322 s from two to four SSDs (2.04×).
   CPU is therefore not generally compute-bound in this experiment.
3. CPU Zstd improves 36.454 → 17.807 → 10.848 s; two-to-four scaling is only
   1.64×. Processing-side costs are becoming visible, but this alone does not
   establish pure decompressor saturation. The full-CPU control confirms that
   processing resources affect this case, while substantial I/O costs remain.
4. GPU four-disk Zstd cold scan (8.520 s) is about 1.27× faster than the fixed
   32-logical-CPU result (1.17× versus CPU48), but still 1.48× slower than its own
   warm scan (5.746 s).
   Four disks have not eliminated storage-path costs for the GPU.
5. Application file-byte rates cluster around 0.64 GB/s on one disk, 1.28–1.32
   GB/s on two, and 2.6–2.8 GB/s on four in I/O-heavy cases. The sustained direct
   read controls independently confirm approximately linear storage scaling,
   but the aggregate bandwidth remains modest.

Thus the original hypothesis is only **partially** supported: high storage
parallelism helps both processors; CPU Zstd starts showing diminished scaling
sooner, but it is incorrect to say CPU generally stops benefiting from storage.
This four-disk G6 is not yet a high-enough-bandwidth platform to expose the GPU
processing ceiling for these compressed workloads.

For a further storage-bottleneck experiment, first measure a candidate's sustained
raw throughput before generating the large matrix. A planning target above
roughly 6 GB/s, ideally 8–10 GB/s for Snappy, is more informative than SSD count
or capacity alone. This is a target inferred from measured warm-path rates, not
a measured knee or a guarantee of GPU saturation. True GDS must be independently
validated; this experiment supplies no new GDS compatibility evidence.

These are seeded integer microbenchmarks, not general SQL/TPC-DS results. They
do not cover dictionary-heavy, string, nested or production datasets. Batch size,
reader scheduling, memory copies and allocation may also limit the processing
path; the study does not isolate a pure codec-kernel hardware limit.

The earlier two-disk G6.8 experiment used another instance, smaller local SSDs
and a smaller dataset. Its higher observed per-disk rates are not a controlled
causal comparison. Neither larger SSD capacity nor a larger instance name is
proof of higher delivered bandwidth; the cause of that difference is unisolated.

## Audit, reproduction and lifecycle

See [README.md](README.md) for reproduction and [resources.json](resources.json)
for the price source and lifecycle. Primary raw records, command lines, physical
read counters, environment, dataset hashes and logs are under `results/`.
`analyze.py` verified 160 primary scan records, 18 sustained-I/O records and
6 full-CPU sensitivity records: **PASS**. It checks generation-based all-column
sums or full eager row counts, physical-read/cache invariants, per-disk traffic
in the main matrix, and identity with the original 384 shard hashes.
See [summary.json](results/summary.json) and [all main-cell ranges](results/summary.md).

Cleanup verified at 2026-09-08 17:03 UTC: instance terminated, root EBS volume
absent, temporary cloud SSH key registration removed. The existing local SSH
key was preserved. Termination was requested at 16:54:20 UTC after archiving all
results. Estimated total cost is **$10.3–$11.0**, including a small allowance for
root EBS and public IPv4, not an AWS invoice. The running rate was approximately
**$4.62/hour**, within the $5/hour budget; setup and experiments took over two hours.
