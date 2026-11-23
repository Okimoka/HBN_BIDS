#!/usr/bin/env bash
#SBATCH --job-name=hbn_download
#SBATCH --output=download_%j.out
#SBATCH --error=download_%j.err
#SBATCH --partition=cpu_il
#SBATCH --time=2-00:00:00
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=2
#SBATCH --mem=4G

set -e
# -u to make progress visible in Slurm logs while the job runs
# "$@" to pass all args
python3 -u download_dataset/download_et_beh.py "$@"
python3 -u download_dataset/download_eeg.py "$@"
