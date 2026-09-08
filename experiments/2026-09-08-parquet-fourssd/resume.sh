#!/bin/bash
set -euo pipefail
cd /home/ubuntu/experiments/2026-09-08-parquet-fourssd
/home/ubuntu/parquet-venv/bin/python generate.py > results/generate-parallel.jsonl 2>&1
/home/ubuntu/parquet-venv/bin/python ../2026-09-08-parquet-ssd/scripts/verify_dataset.py --roots /mnt/ssd0 /mnt/ssd1 /mnt/ssd2 /mnt/ssd3 --out results/dataset-inventory.json > results/dataset-metadata.jsonl 2>&1
/home/ubuntu/parquet-venv/bin/python run.py > results/run.log 2>&1
/home/ubuntu/parquet-venv/bin/python io.py > results/io.log 2>&1
date -u
