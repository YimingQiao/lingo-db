# SSD Parquet → CPU / GPU experiment (2026-09-08)

Self-contained benchmark of **existing Parquet files on local SSD**, not Parquet
writing/compression and not a LingoDB query-engine benchmark. GPU decompression
means decoding the compressed Parquet payload *after* it reaches device memory.

## Experimental controls

- One disposable AWS `g6.8xlarge`, one NVIDIA L4, 32 vCPUs, 128 GiB RAM,
  two independent 450 GB local NVMe devices. Root EBS is never a data source.
- Identical seeded integer data: 128 × 1,048,576 rows, 16 int64 columns,
  16 GiB logical payload. Four interleaved entropy levels (8/16/24/32 random bits).
- Parquet 2.6, plain encoding (dictionary disabled), no statistics,
  262,144-row groups, 1 MiB target pages. Uncompressed, Snappy and Zstd level 3.
- The 1-disk and 2-disk layouts contain byte-identical copies of every shard.
  Multi-disk batches alternate files by **shard number**, not mount path.
- Both processors fully decode all columns and SUM every column. All 16 integer
  sums are checked against data generation, not just CPU/GPU agreement.
  The initial matrix uses sequential CPU column sums. Follow-up controls use
  16-way CPU column sums, and a full eager scan without SUM; the report gives
  these fairer / more targeted controls priority over the initial comparison.
- Batches contain eight files (1 GiB decoded); both paths materialize a batch
  then reduce it. Runtime/CUDA initialization is warmed outside timing.
  GPU uses an RMM pool (4 GiB initial, 16 GiB maximum). A separate 32-file
  sensitivity control checks whether larger batches materially alter results.
- Cold measurements call sync + drop_caches on this exclusive disposable host.
  Linux per-device sector counters establish actual SSD traffic. Warm cases
  preload only compressed file bytes into OS cache, never decoded tables.
- GPU staged uses `KVIKIO_COMPAT_MODE=ON`. A GDS result is admitted only after a
  strict probe with **both** KvikIO compatibility off and cuFile fallback disabled,
  plus cuFile statistics establishing actual P2PDMA reads. Merely setting an
  environment variable or seeing `gdscheck` support is not sufficient proof.
- Pure storage control uses parallel, aligned `O_DIRECT` reads. This control
  does not parse/decompress Parquet and is not an application-performance result.
  Its fixed request pattern is an observed reference, not a proven hardware
  maximum; buffered/asynchronous application readers may exceed it.
- Three repeats per cell; randomized cell order with seed 20260908. Report
  medians and ranges, not best-of-three. Cases execute sequentially.

## Reproduction

Run on a **dedicated disposable machine**, never a shared production host:

```bash
python3 -m venv parquet-venv
parquet-venv/bin/pip install 'cudf-cu13==26.8.*' 'kvikio-cu13==26.8.*' pyarrow numpy
# For exact reproduction, use this INSTEAD of the resolver command above:
# parquet-venv/bin/pip install -r results/environment/requirements.freeze.txt
parquet-venv/bin/python scripts/generate.py --roots /mnt/ssd0 /mnt/ssd1
parquet-venv/bin/python scripts/capture_environment.py --out results/environment
CUDA_VISIBLE_DEVICES=0 KVIKIO_COMPAT_MODE=OFF \
  CUFILE_ENV_PATH_JSON="$PWD/cufile-strict.json" \
  parquet-venv/bin/python scripts/probe_gds.py
# Without a successful verified probe, run CPU + staged GPU only:
parquet-venv/bin/python scripts/run_matrix.py \
  --roots /mnt/ssd0 /mnt/ssd1 --out results/matrix
# If and ONLY if GDS was verified, add --gds --config "$PWD/cufile-strict.json".
parquet-venv/bin/python scripts/resident.py --root /mnt/ssd0 --codec zstd --engine cpu
parquet-venv/bin/python scripts/resident.py --root /mnt/ssd0 --codec zstd --engine gpu
# Repeat resident controls with --codec none and --codec snappy.
parquet-venv/bin/python scripts/verify_dataset.py --roots /mnt/ssd0 /mnt/ssd1 \
  --out results/dataset-inventory.json
# Example targeted CPU control (switch engine to gpu for the matched GPU scan):
CUDA_VISIBLE_DEVICES=0 KVIKIO_COMPAT_MODE=ON KVIKIO_NTHREADS=16 \
  parquet-venv/bin/python scripts/bench.py --roots /mnt/ssd0 /mnt/ssd1 \
  --disks 2 --codec zstd --engine cpu --operation scan --devices nvme1n1 nvme2n1
# For the CPU parallel-SUM control, use --operation sum --cpu-reduce-threads 16.
```

After the main matrix, `scripts/resident.py` measures host-byte / VRAM-byte
read+decode and reduction separately. `scripts/verify_dataset.py` verifies SHA-256
identity of all layout copies and writes the file inventory.
`python3 scripts/summarize.py results/matrix` checks checksums and physical-I/O
invariants, then prints medians.

The strict configuration's log directory must exist and be writable. The
`setup_host.py` script is intentionally restricted to the **empty DLAMI ephemeral
LV on the exact two instance-store devices**. It removes that empty LV, formats
the two scratch drives, disables the image's auto-LVM service, enables kernel
P2PDMA prerequisites, and installs a 150-minute shutdown deadline. It requires
explicit `--prepare-empty-dlami-nvme` and a reboot. EC2 shutdown behavior must be
`terminate`. AWS's kernel builds NVMe into the kernel, so also run
`sudo python3 scripts/configure_builtin_nvme.py` before reboot; the modprobe
option alone does not disable multipath. It must not be reused on a machine
containing valuable data.

On this image, GDS utilities were installed using
`sudo apt-get install gds-tools-13-2 libcufile-13-2`. The recorded
`diagnose_gds.py` / `run_controls.py` are session orchestration scripts with the
original `/home/ubuntu/parquet-experiment` and `/home/ubuntu/parquet-results`
paths. The latter also preserves and reruns one cache-contaminated initial cell;
that incident-specific step is not needed in a clean, sequential reproduction.
`run_decomposition.py` records the randomized CPU parallel-SUM and scan-only
follow-up. `finish_controls.py` preserves the failed large-batch attempt and
tests a larger pool; neither pool failure is a successful performance sample.

## Offline result validation

No GPU, Parquet files or third-party Python packages are needed to audit the
archived records:

```bash
python3 scripts/validate_results.py results
python3 scripts/summarize.py results/cpu-parallel-sum
python3 scripts/summarize.py results/scan-only
```

The final archive contains 56 successful cells × 3 repeats = 168 timing records.
Failed GDS probes, failed large-batch allocations, and the excluded cache-
contaminated cell are retained separately and never used in successful medians.

## Interpreting throughput and bottlenecks

`file_GBps` uses actual Parquet file bytes, `logical_GBps` uses decoded int64
payload, and `physical_read_GBps` uses block-device counters. All are decimal
GB/s; dataset capacity is explicitly GiB. These byte domains are not interchangeable.
CPU utilization is process user+system CPU time divided by wall time, expressed
as logical-CPU equivalents, not a count of physical cores or GPU utilization.

Cold vs warm, one vs two SSDs, the pure-I/O control, and codec changes are
independent evidence. Warm timing still includes memory movement, Parquet parsing,
decoding, allocation and reduction; it is **not pure codec decompression time**.
Likewise, a faster compressed case can result from less I/O, not faster decoding.
Do not add phase times from overlapping pipelines or extrapolate two disks to
four without measurement. This synthetic integer workload does not represent
strings, nested data, dictionary-heavy files or a full SQL engine.

## References

- [NVIDIA GDS installation/troubleshooting](https://docs.nvidia.com/gpudirect-storage/troubleshooting-guide/):
  kernel P2PDMA prerequisites, explicit ext4 journaling mode and runtime statistics.
- [cuDF I/O](https://docs.rapids.ai/api/cudf/stable/cudf/io/io/):
  KvikIO compatibility mode and cuFile's separate fallback behavior.

Read [RESULTS.md](RESULTS.md) for measured conclusions, limitations and cleanup status.
