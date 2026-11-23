# HBN downloads

Scripts to download the required HBN files.
- `download_eeg.py` downloads the BIDS files from NEMAR
- `download_et_beh.py` downloads the ET+BEH files from the public S3 (`s3://fcp-indi/data/Projects/HBN/`)
- `download.sh` starts both downloads (can be used in slurm)
- `download_utils.py` contains helper functions

After execution, files will be in this structure:

```text
HBN_RAW/
├── EEG/R1/ … R11/    # Published EEG releases
├── ET/<subject>/    # Original Eyetracking directory contents
└── BEH/<subject>/   # Original Behavioral directory contents
```

Dataset naming in NEMAR is slightly confusing. `v1.0.0` corresponds to `v1.0.1` on OpenNeuro. Also, `on005513` does not exist, so the release mapping is

| Release | NEMAR name |
| --- | --- |
| R1–R8 | on005505–on005512|
| R9 | on005514 |
| R10 | on005515 |
| R11 | on005516 |

The script reads the release manifests and uses curl to fetch the individual files. No archive extraction or unpacking step is needed.

## Use within HBN_BIDS

Follow the [root setup instructions](../README.md#setup) once, then run these
commands from the repository root in the activated environment.

## Run

Preview both selections or download everything:

```bash
bash download_dataset/download.sh --output HBN_RAW --dry-run
bash download_dataset/download.sh --output HBN_RAW
```

The downloaders also run independently:

```bash
python download_dataset/download_et_beh.py --output HBN_RAW --only et
python download_dataset/download_eeg.py --output HBN_RAW --releases 1 11
```

Both accept `--output`, `--subjects`, `--concurrency`, `--dry-run`, `--only eeg et beh` and `--releases 1 ... 11`. This lets the launcher forward the same arguments to both. `--releases` affects EEG only. Each script skips modalities it does not handle; their defaults select ET/BEH and EEG respectively. Dry runs list sources without creating output files.

Subject IDs may include or omit `sub-`. EEG subject filtering keeps shared metadata, including the full upstream `participants.tsv`, unchanged.

`--concurrency` defaults to 16. It controls concurrent downloads independently of Slurm CPU allocation.

## Slurm

Submit from the repository root using the Python environment with the dependencies installed. ET/BEH runs first, followed by EEG. 
The launcher runs both scripts with `python3 -u ...`, so make sure the command is available on job runtime (e.g. via activating the cluster module).

```bash
sbatch download_dataset/download.sh --output HBN_RAW
# or to only download eeg from release 11
sbatch download_dataset/download.sh --output HBN_RAW --only eeg --releases 11
```

The default slurm parameters (partition name is `cpu_il` and and runtime is 2 days by default) need to be adjusted based on the cluster that it is being run on.

## Standalone reuse

Copy the complete `download_dataset` folder into another project, install
`python -m pip install -r download_dataset/requirements.txt`, and use the same
commands from that project's root. In addition, the downloaders need curl.

## Reruns

Existing same-sized files are skipped. Missing or wrong-sized files replace their destination only after a successful transfer. Interrupted individual files restart from the beginning; completed files are reused. Errors propagate normally and stop the run; already-running transfers may finish during shutdown.

The scripts assume upstream files remain unchanged, including between reruns. Size checks do not detect same-sized corruption or edits.
