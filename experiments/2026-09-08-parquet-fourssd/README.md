# G6 local-NVMe scaling follow-up

Question: with CPU allocation and one L4 held fixed, does increasing local SSD
parallelism from 1 to 2 to 4 move compressed-Parquet scans toward a compute limit?
This is a staged GPU I/O experiment, not a claim of working GPUDirect Storage.

Reuses the eager CPU/GPU scan implementation and SHA-256 verifier in
`../2026-09-08-parquet-ssd/scripts/`. The generator preserves the first run's
seeds and encoding but generates independent shards in four worker processes.
No LingoDB engine changes.
The follow-up uses a larger 64 GiB logical dataset (512 shards) to reduce the
influence of short storage bursts. Codecs: none, Snappy, Zstd-3, same deterministic
16 int64 columns and plain Parquet encoding as the first experiment.

Controls: 1/2/4 local disks, fixed 32 logical CPUs (16 physical cores with
both SMT siblings), one visible L4, 1 GiB decoded batches, cold full eager scan,
warm compressed-page-cache scan, matched full-scan-plus-parallel-SUM checks,
and sustained O_DIRECT I/O without decompression. Keep original file bytes,
decoded bytes, and observed physical disk bytes separate in all throughput rates.

Measured findings and lifecycle status are recorded in RESULTS.md.
Only newly provisioned disposable instance-store devices may be prepared.

## Reproduction

Provision a disposable four-disk G6 DLAMI with a 150 GiB root EBS volume,
delete-on-termination enabled, and instance shutdown behavior set to terminate.
Set an automatic shutdown deadline before doing preparation. Copy both experiment
directories beneath `/home/ubuntu/experiments/`, then run:

```bash
bash /home/ubuntu/experiments/2026-09-08-parquet-fourssd/bootstrap.sh
```

`prepare.py` refuses unless all four scratch disks match the EC2 instance-store
model and expected device names, the DLAMI scratch mount is empty, and the LVM
physical volumes are exactly those four disks. It formats these disposable
scratch devices; **do not run it on a machine containing valuable data**.
It never formats root EBS. No GDS driver changes or reboot are part of this test.

The initial execution switched from serial to parallel data generation before
timing. `resume.sh` records that incident-specific continuation; the current
`bootstrap.sh` directly uses the parallel generator for clean reproduction.
All generation and verification finish before any benchmark starts. Layout 3
is generated/verified as well but not included in the timing matrix.

`run.py` fixes the CPU affinity, uses GPU 0 only, randomizes 32 cases, and executes
five repetitions per case. `io.py` then runs 18 sustained O_DIRECT samples
(three repetitions of each disk-count/thread-count pair, each at least 30 s).
I/O workers stop at file boundaries after a shared 30-second deadline; slower
configurations may read only part of the 64 GiB uncompressed layout. The record
includes actual bytes, files completed, equivalent full passes, and elapsed time.
No two measurement processes run concurrently. Warm scans cache compressed
file bytes only, while cold scans flush and drop the exclusive host's page cache.

After the main matrix and pure-I/O control, `cpu_scale.py` repeats the four-disk
Zstd cold/warm eager scans using all 48 logical CPUs (24 physical cores), three
repetitions each. This exploratory sensitivity checks whether the primary
32-logical-CPU allocation drives the observed sublinear CPU scaling. It is not
pooled with the primary five-repeat cells. The original live `resume.sh` does
not launch this later-added control: it must be run separately after it finishes;
the updated clean-reproduction `bootstrap.sh` includes it.

Copy `results/` back before terminating the instance; also remove its root EBS
and any experiment-only cloud key registration. Generated SSD data is disposable
and reproducible, and is not uploaded to GitHub.

## Offline audit

```bash
python3 experiments/2026-09-08-parquet-fourssd/analyze.py
```

This requires only the standard library and both archived experiment folders.
It checks 160 primary scan records, 18 sustained-I/O records, and 6 full-CPU
sensitivity records, expected row counts or
all-column sums, physical-read/cache invariants, and the first 128 shards' hashes
against the first experiment. It writes `results/summary.json` and `summary.md`.
Report medians and min–max ranges; five repetitions alone do not establish
statistical significance. Warm eager reads still include movement, parsing and
allocation, not just codec decompression; O_DIRECT is a reference read pattern,
not proof of a universal hardware upper bound.
