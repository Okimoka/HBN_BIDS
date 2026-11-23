#!/usr/bin/env bash
#SBATCH --job-name=hbn_augment
#SBATCH --output=augment_%j.out
#SBATCH --error=augment_%j.err
#SBATCH --partition=cpu_il
#SBATCH --time=2-00:00:00
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=2
#SBATCH --mem=48G

# submit from HBN_BIDS after activating the Python environment, as with download.sh
# full R5 validation needed a 32 GiB V8 heap; this only affects the validator
export DENO_V8_FLAGS=--max-old-space-size=32768

# -u makes progress visible immediately; "$@" forwards the module's arguments
python3 -u -m hbn_augment "$@"
