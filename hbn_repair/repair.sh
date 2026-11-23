#!/usr/bin/env bash
#SBATCH --job-name=hbn_repair
#SBATCH --output=repair_%j.out
#SBATCH --error=repair_%j.err
#SBATCH --partition=cpu_il
#SBATCH --time=1-00:00:00
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=2
#SBATCH --mem=16G

# submit from HBN_BIDS after activating the Python environment, as with download.sh
# -u makes progress visible immediately; "$@" forwards the module's arguments
python3 -u -m hbn_repair "$@"
