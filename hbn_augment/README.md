# hbn_augment

Add behavioral information and synchronized SMI eye tracking to releases already reviewed after
[hbn_repair](../hbn_repair/README.md). Repaired EEG signals, task-event values,
participant tables and original quality judgments are preserved. Each release
remains an independent BIDS dataset.

The behavioral additions are B01 (selected task settings and source flags),
B02 (planned waiting intervals before contrast targets), and B03 (movie order
and source clip names, previously B04). They are checked independently of ET
availability; ambiguous source matches remain unfilled and are logged.
Scientific conversion choices are in “B. Additional behavioral information”,
“C. Eye-tracking integration” and “Quality checks and verification”
of the [project report](../report/report.pdf).

## Run

After the environment setup in the [root README](../README.md#setup), run from
HBN_BIDS:

```python
from hbn_augment import augment_dataset

summary = augment_dataset("HBN_REPAIRED", "HBN_AUGMENTED", validate=True)
```

```bash
python -m hbn_augment --input HBN_REPAIRED --output HBN_AUGMENTED --dry-run
python -m hbn_augment --input HBN_REPAIRED --output HBN_AUGMENTED --validate
```

The input contains `EEG/R*/`, with `code/recording_quality.tsv` and its JSON
dictionary in each release, plus the `ET` and `BEH` links created by repair. Input files
are read only. Use a new/empty output directory; rebuilding uses another empty
directory. This prevents stale eye files or results from surviving a failed
conversion. Select participants during repair; augmentation retains the
membership of its selected repaired releases.

```text
HBN_REPAIRED/EEG/R*/       reviewed EEG, metadata and quality table
HBN_REPAIRED/ET           -> original downloaded ET
HBN_REPAIRED/BEH          -> original downloaded behavioral exports
HBN_AUGMENTED/EEG/R*/         same releases with added behavior and BIDS eye files
HBN_AUGMENTED_reports/        summary.json and per-release operational reports
```

Only the individual `EEG/Rn` directories are BIDS roots. Raw S3 exports are not
copied into them. Successful conversions add eye files and the necessary local
event-metadata fields; inherited EEG/task definitions remain in place. Failed
matching, alignment or conversion keeps the repaired recording intact and
records its outcome. Behavioral additions use MATLAB exports under `BEH`;
the older `ET/<subject>/Behavioral/` layout is also supported. Missing behavioral
sources do not prevent ET conversion. Unexpected I/O errors stop the build.

| Option | Meaning |
| --- | --- |
| `--input DIR`, `--output DIR` | Repaired collection and new final collection |
| `--releases N …` | Selected releases from 1–11; default is all in the repaired input |
| `--file-mode copy` | Default; independent copies, checked against source hashes |
| `--file-mode symlink` | Link .set/.fdt files; editable metadata remains independent |
| `--metadata-file FILE` | Optional acquisition/display YAML for smi2bids |
| `--max-residual-ms 20` | Maximum accepted synchronization residual |
| `--max-clock-deviation .01` | Maximum accepted absolute clock-scale deviation from 1 |
| `--reports DIR` | Default is the output's sibling `<output>_reports` directory |
| `--dry-run` | Match inputs without creating output or reports |
| `--validate`, `--validator PATH` | Run the BIDS validator over every table row |

API options follow the CLI; the API uses `max_residual_s=0.020` in seconds.
The returned summary has one entry per release under `summary["releases"]`.
A completed build can contain EEG recordings without ET: inspect the outcome
counts. Validator failures produce `status: validation_failed` and a nonzero
CLI exit. An interrupted build retains `status: in_progress`.

## Recording quality and operational reports

`code/recording_quality.tsv` keeps every repaired row, including source-only
candidates and EEG recommendations. It adds `et_status`, `et_in_bids`, source
and output paths, alignment parameters and conversion counters. The JSON
dictionary explains each field. Error prose stays in the operational reports.

The four grid columns are `et_grid_rms_error_ms`, `et_grid_max_error_ms`,
`et_grid_pass_5pct` and `et_grid_pass_10pct`. Errors compare observed timestamps
with the exported row clock in EEG-clock milliseconds; inserted rows do not
contribute. The flags test the maximum error against 5% and 10% of one sample
period. Conversion can succeed while both flags are `0`; this preserves the
source measurements but does not certify their approximate grid timing.

`beh_b01_status`, `beh_b02_status` and `beh_b03_status` report the separate
behavioral outcomes. Source references and the number of added planned intervals
are recorded alongside them. Existing event columns and EEG recommendations remain
unchanged.

Earlier validator results are preserved as `repair_validation_state`,
`repair_validator_errors` and `repair_validator_warnings`. The regular validation
columns describe the augmented output and remain `n/a` unless validation is run.
An ET conversion outcome does not assign or change an EEG recommendation.

| File outside the BIDS roots | Contents |
| --- | --- |
| `summary.json` | Input/output paths, settings, per-release counts and validation outcomes |
| `R*/recordings.tsv` | One outcome per EEG recording, including conversion error messages |
| `R*/et_inventory.tsv` | Matched/unmatched SMI pairs and unsupported exports for release members |
| `R*/anchors.tsv` | Actual event pairs used in successful alignment fits |
| `R*/validation.json`, `validation.log` | Full validator output when requested |

## Run with Slurm

After reviewing the repair output, submit from the HBN_BIDS root in the
environment created during [setup](../README.md#setup):

```bash
source .venv/bin/activate
sbatch hbn_augment/augment.sh --input HBN_REPAIRED --output HBN_AUGMENTED --file-mode symlink --validate
```

The launcher forwards all arguments to `python3 -u -m hbn_augment`. Logs appear
as `augment_<job-id>.out` and `.err` in the submission directory. The validator
must also be available in that environment when using `--validate`.

Defaults are partition `cpu_il`, one task, **2 CPUs, 48G RAM and 48 hours**.
Full-row validation of the unusually long R5 ET export previously peaked at
about **24.2 GiB** on the local machine. A 16 GiB JavaScript heap failed, so the
launcher sets `DENO_V8_FLAGS=--max-old-space-size=32768` to allow a 32 GiB heap.
The larger Slurm allocation leaves room for the validator's other memory and
the Python process. This environment variable has no effect without validation.

The time limit is a conservative estimate, not a measured runtime. The
previous local research build used 4–8 conversion workers and linked EEG;
this command processes recordings sequentially. Extra allocated CPUs do not
turn on recording parallelism. Adjust the `#SBATCH` lines or override them
through `sbatch` options as needed.

Use `--file-mode copy` for portable EEG payloads. Keep the output directory
new/empty, including when rerunning an interrupted job.

## Reuse outside HBN_BIDS

Copy `hbn_augment`, `hbn_repair` and `smi2bids` beside each other and install
`python -m pip install -r hbn_augment/requirements.txt` in that project's
environment. The CLI and Python API work from that root. Augmentation reuses
repair's inventory, file and quality helpers; it does not rerun repairs or
require the download scripts.
