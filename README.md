# HBN_BIDS

Resources for creating a BIDS EEG dataset with aligned SMI eye tracking from
the original HBN downloads. The tools live together here and share one Python
environment.

## Project report

[An update proposal to the HBN-EEG datasets](report/report.pdf) is the
single report covering this repository. READMEs are just for usage.

The [complete recording-quality sheet](report/recording_quality.tsv.gz) contains
all recordings, existing metrics and automatic EEG recommendations
(`available`, `caution`, `unavailable`). Its
[column dictionary](report/recording_quality.json) documents the rules and counts.
These screening ratings do not replace scientific review. See
[how to regenerate or open the sheet](hbn_repair/README.md#repair-published-eeg-a01a15).

It can be built using

```bash
typst compile report/report.typ report/report.pdf
```

## Setup

Use Python 3.10 or newer and install curl on the machine running downloads.
From the repository root, run

```bash
cd /path/to/HBN_BIDS
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
```

Run the commands below from the repository root in the same terminal.

## Workflow

Preview the download selection, then download the source files:

```bash
bash download_dataset/download.sh --output HBN_RAW --dry-run
bash download_dataset/download.sh --output HBN_RAW
```

For Slurm, submit `sbatch download_dataset/download.sh --output HBN_RAW` from
the repository root. Select the intended Python environment before submission,
and ensure it is available on the compute node. The supplied Slurm scripts use
starting parameters chosen for the Ehlers cluster; adjust their `#SBATCH`
partition, CPU, memory and time settings for your cluster. The [download README](download_dataset/README.md) describes
subject/release selection and separate EEG or ET/BEH downloads.

**Review the downloaded inputs and logs before preparation.** Repair the
published EEG releases, then review the result:

```bash
python -m hbn_repair --input HBN_RAW --output HBN_REPAIRED --validate
```

For cluster execution, submit `sbatch hbn_repair/repair.sh --input HBN_RAW --output HBN_REPAIRED --validate` from this root in the activated environment. 

The BIDS roots are `HBN_REPAIRED/EEG/R1/` through `EEG/R11/`.
Each retains the original `participants.tsv` and `participants.json` unchanged,
and adds a separate
`code/recording_quality.tsv` with its JSON column dictionary.

**Review the repairs and quality table before augmentation.** Then add verified
behavioral information and aligned SMI eye tracking to the repaired collection:

```bash
python -m hbn_augment --input HBN_REPAIRED --output HBN_AUGMENTED --dry-run
python -m hbn_augment --input HBN_REPAIRED --output HBN_AUGMENTED --validate
```

After reviewing the repair, submit with Slurm using
`sbatch hbn_augment/augment.sh --input HBN_REPAIRED --output HBN_AUGMENTED --validate`.
The [augmentation launcher](hbn_augment/README.md#run-with-slurm)
includes the validator heap setting described below.

Full-release ET validation can exceed the validator's default JavaScript heap
limit. On a machine with sufficient RAM, run
`export DENO_V8_FLAGS=--max-old-space-size=32768` before the validation command
to allow a heap of up to 32 GiB. This also applies when validating a bundle.

Both stages require a new/empty output directory. Use `--file-mode symlink` for
local work with linked EEG payloads; use `copy` for portable dataset outputs.

Review the augmented releases before analysis or optional bundling:

```bash
python -m hbn_bundle --dataset HBN_AUGMENTED/EEG --output HBN_MERGED --dry-run
python -m hbn_bundle --dataset HBN_AUGMENTED/EEG --output HBN_MERGED --validate
```

The bundle links the prepared subject directories and combines their dataset
metadata and quality tables.

## Tool usage and reuse

- [Downloaders](download_dataset/README.md): published EEG files from NEMAR and
  original ET/BEH files from S3
- [smi2bids](smi2bids/README.md): Python API and CLI for one SMI text-export pair
- [hbn_repair](hbn_repair/README.md): repair published EEG metadata and labels,
  and produce the recording-quality table
- [hbn_augment](hbn_augment/README.md): add verified behavioral metadata and
  synchronized ET to reviewed EEG releases, and extend their quality tables
- [hbn_bundle](hbn_bundle/README.md): combine prepared releases into an optional
  BIDS dataset through symlinks and merged metadata

The tool READMEs document purpose, setup, APIs, command-line parameters, and
operational constraints. The project report explains the methods and decisions.
Each tool can also be used separately by copying its complete folder
and installing its own `requirements.txt`. `hbn_augment` needs both
`hbn_repair` and `smi2bids` beside it; its requirements include their dependencies. `hbn_bundle` is independent of both tools and expects
the prepared release layout described in its README.

For example, another project can contain `smi2bids/` and use
`from smi2bids import smi2bids` after installing
`python -m pip install -r smi2bids/requirements.txt`. Run from that project's
root so Python can find the folder. These requirements do not register the
tools globally or make them importable from arbitrary directories.
