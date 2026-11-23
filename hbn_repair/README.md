# hbn_repair

Repair each published HBN EEG release independently. This implements A01–A15
from the [project report](../report/report.pdf).
It repairs supported metadata/event labels and publishes structured recording
quality findings. Review this output before passing it to
[hbn_augment](../hbn_augment/README.md).

This implements the raw-dataset preparation stage. It does not filter EEG,
detect bad channels, fit ICA, crop recordings, improve SMI event detection,
or create synthetic `allTasks`/`freeView` tasks.

## Repair published EEG (A01–A15)

After the [root setup](../README.md#setup), run from HBN_BIDS:

```python
from hbn_repair import repair_dataset

summary = repair_dataset("HBN_RAW", "HBN_REPAIRED", file_mode="symlink")
```

```bash
python -m hbn_repair --input HBN_RAW --output HBN_REPAIRED --validate
```

```text
HBN_RAW/                   EEG/R1/ … R11/, ET/, BEH/
HBN_REPAIRED/EEG/R1/        dataset_description.json
                              participants.tsv / participants.json
                              task-…_events.json
                              sub-…/eeg/…
                              code/… (original support files and QC)
                              code/recording_quality.tsv
                              code/recording_quality.json
HBN_REPAIRED/ET            -> HBN_RAW/ET
HBN_REPAIRED/BEH           -> HBN_RAW/BEH
HBN_REPAIRED_reports/      summary.json, s3_inventory.json, R*/changes.tsv
```

Only `EEG/Rn` is a BIDS root. ET/BEH links are created when those inputs exist;
they are not source archives inside the BIDS datasets. Legacy EEG folders such
as `ds005505` and nested `ET/<subject>/Eyetracking` are accepted.

| Repair option | Meaning |
| --- | --- |
| `--subjects ID …`, `--releases N …` | Select participants/releases |
| `--file-mode copy` | Default; portable EEG copies |
| `--file-mode symlink` | Link unchanged .set/.fdt files; changed .set files are new files |
| `--reports DIR` | Operational reports outside input and output |
| `--source-inventory FILE` | Reuse an inspected `s3_inventory.json`; must cover selected subjects |
| `--reviews FILE` | Explicit recommendations keyed by `recording_id`; override automatic ratings |
| `--validate`, `--validator PATH` | Run the BIDS validator with all TSV rows |

Use a new/empty output directory. Inputs are read-only; failed builds retain
`status: in_progress` in the report and must not be treated as complete.
The inventory lists public S3 EEG objects and downloads only small movie-event
CSVs. It does not download source EEG arrays. A cached inventory assumes the
upstream objects stay unchanged, as do the downloaders.

The quality table includes the union of confirmed published files and original
S3 signal exports for participants in the selected releases. It preserves
upstream statuses and quality values, distinguishes source/BIDS/ET presence,
and uses one column per A issue plus specific review flags. Ambiguous source
identities remain separate candidate rows. Unknown results use `n/a`, never a
fabricated pass. `embedded_in` remains `n/a` until a complete recoverable task
relationship is verified.

The original `participants.tsv` and `participants.json` are copied unchanged,
including task-availability columns. A subject selection limits recordings and
new quality rows; it retains the original participant files unchanged.

The original QC tables also retain historical rows for people outside their
release's participant cohort. Those rows are not assigned to a new release or
silently removed; the new recording inventory uses the selected participants.

Recommendations concern the named EEG task after ordinary preprocessing.
Simple rules assign provisional recommendations: **available** = no obstacle
detected by the available checks; **caution** = a known caveat or incomplete
assessment of an existing EEG recording; **unavailable** = no delivered
standalone EEG file, or a recording confirmed unusable.
The rules are in `ratings.py` and the output JSON's `RecommendationRules`.
The ten inspected A15 recordings and source-only rows receive `unavailable`;
their reason codes distinguish unusable signals from missing delivered files.
Remaining task/source flags produce `caution`; fixed metadata, ordinary
validator warnings and ET metrics do not lower the EEG recommendation.
Without completed EEG validation, an existing recording receives `caution`.

`recommendation_method` distinguishes automatic results from explicit reviews;
`recommendation_reasons` contains controlled codes. Human `review_status` is
preserved. These rules do not constitute an EEG signal-quality review.
An optional review file overrides automatic ratings using these columns:

```text
recording_id    recommendation    required_action    review_status
```

Use actual tab separators and IDs from the generated table. Action values:
`none`, `extract_task`, `convert_source`, `exclude`, `review`. Review status:
`unreviewed`, `partial`, `reviewed`. Source-only availability does not establish
usability in the delivered release. The original `upstream_status` is never
overwritten; it remains separate from our recommendation.

To export all release tables with their metrics and ratings into one compressed
TSV and JSON dictionary (without modifying the input tables), run from the root:

```python
from hbn_repair.ratings import export_ratings

export_ratings("HBN_AUGMENTED/EEG", "report")
```

The files are `report/recording_quality.tsv.gz` and `report/recording_quality.json`.
Use `gzip -dc report/recording_quality.tsv.gz > /tmp/recording_quality.tsv` to
open an uncompressed copy in a spreadsheet application.

A10–A14 retain the measurements and report unresolved findings. A10 distinguishes:

| Value | Meaning |
| --- | --- |
| `absent` | No identified extra task/run start; a `break cnt` or boundary alone does not count |
| `present_counterpart_available_matches` | All extra tasks/runs have separate counterparts and their shared signal intervals match exactly |
| `present_counterpart_available_differs` | All extra tasks/runs have separate counterparts, but at least one shared signal interval differs |
| `present_counterpart_available_unknown` | All counterparts exist, but comparison is inconclusive for at least one and no difference was established |
| `present_counterpart_missing` | At least one other task/run has no separate BIDS counterpart |
| `unresolved` | Uninspected source, uncertain task identity or ambiguous counterpart files |

Counterparts are checked automatically within each participant and release.
Matching task-start markers align the two signals; every channel and sample in
their common interval is compared, stopping at the next task start or file end.
Repeated starts, different sampling rates or channel order, or fewer than 32
common samples leave the comparison unknown. No shifting, rescaling or
rereferencing is attempted. Exact equality describes the shared interval,
not complete task coverage or good signal quality. With multiple extra tasks,
a missing counterpart takes priority; otherwise any established difference
takes priority over unknown comparisons.

Standalone counterparts do not inherit the containing file's overlap flag.
Source-only exports do not count as BIDS counterparts. An internal break marker
alone is descriptive information and leaves A10 absent. The
packaged A11–A13 source comparisons apply only when both the event TSV and behavioral
source hashes match the inspected snapshots; otherwise those checks remain
unknown. See [reference-data provenance](data/README.md). A01 checks TSV/.set
event identity before editing labels, replaces only the stored event variable,
then reads it back. Other MATLAB variables retain their exact bytes, including
signal arrays, `urevent`, source history and opaque MATLAB class storage; its
file-header pointer is adjusted if needed. A full-file hash checks the write.
No official release
version, license or new DOI is assigned by this tool.

A06 associates contrast feedback with the recorded target-end marker and adds
it to the standard `HED` column when one response establishes the outcome.
Original event values remain intact. Missing/repeated responses and unusual
timing are counted in the quality table; the latter prevents unsupported fixed
phase durations. Sequence-learning dot annotations use their corresponding
existing definitions. The scientific decisions and examples are in the report.

A06 keeps an initial offset whose preceding onset was not recorded, but
annotates it as a point event in an added `hed_annotation` column. The original
`value`, code and timing stay intact. Local HED sidecars include the inherited
definitions and referenced columns needed to validate them independently.

A15 keeps unidentified channel layouts separate from ordinary missing type/unit
metadata (A07). The ten known six-channel recordings have been inspected as
test-like signals; their exclusion recommendation is an explicit review decision.

## Run with Slurm

Submit from the HBN_BIDS root in the environment created during
[setup](../README.md#setup), just as for the downloader:

```bash
source .venv/bin/activate
sbatch hbn_repair/repair.sh --input HBN_RAW --output HBN_REPAIRED --file-mode symlink --validate
```

The launcher forwards all arguments to `python3 -u -m hbn_repair`. Logs appear
as `repair_<job-id>.out` and `.err` in the submission directory. The validator
must also be available in that environment when using `--validate`.

Defaults are partition `cpu_il`, one task, **2 CPUs, 16G RAM and 24 hours**.
These are conservative starting allocations, not measured resource requirements:
the previous local repair reused cached inputs and has no recorded peak-memory
measurement. Recordings are processed sequentially; extra CPUs do not enable
parallel recording processing. Copying all EEG payloads can take considerably
longer than linking them. Adjust the `#SBATCH` lines or override them through
`sbatch` options as needed.

Use `--file-mode copy` for a portable output instead of links. Review the repaired
dataset before submitting augmentation; the two jobs are deliberately separate.

## Reuse outside HBN_BIDS

Copy the complete `hbn_repair` folder, including `data/`, into another project
and install `python -m pip install -r hbn_repair/requirements.txt`. Run the
commands or import `repair_dataset` from that project's root. Repair does not
require the downloaders or smi2bids. The same inventory and I/O helpers are
also used by hbn_augment.
