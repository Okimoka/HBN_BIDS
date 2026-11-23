# hbn_bundle

Combine prepared HBN releases into one BIDS dataset for local analysis. Recording
directories are linked; participant tables, recording-quality tables and dataset
metadata are combined. Matching, synchronization and
eye-tracking conversion have already happened in
[hbn_augment](../hbn_augment/README.md).

The independently prepared releases remain the primary outputs. Bundling is
optional and runs only when explicitly requested.

For the rationale behind separate releases and an optional bundle, see the
[project report](../report/report.pdf).

## Run

Follow the environment and dependency setup in the [root README](../README.md),
then run from the HBN_BIDS root:

```bash
python -m hbn_bundle --dataset HBN_AUGMENTED/EEG --output HBN_MERGED --dry-run
python -m hbn_bundle --dataset HBN_AUGMENTED/EEG --output HBN_MERGED --validate
```

`--dataset` names the collection containing prepared `R1/` … `R11/` datasets,
not the original download directory. Each release must have its own
`dataset_description.json`, `participants.tsv` and `participants.json`.

For example, the bundle contains:

```text
HBN_MERGED/
├── dataset_description.json
├── participants.tsv / participants.json
├── README
├── sub-A/
│   ├── eeg -> ../../HBN_AUGMENTED/EEG/R1/sub-A/eeg
│   └── sub-A_task-rest_events.json -> ../../HBN_AUGMENTED/EEG/R1/task-rest_events.json
├── sub-B/ …
└── code/
    ├── recording_quality.tsv / recording_quality.json
    ├── R1 -> ../../HBN_AUGMENTED/EEG/R1/code
    └── R2 -> ../../HBN_AUGMENTED/EEG/R2/code
```

Links are relative. The prepared releases must remain available at the expected
relative locations. Reading through a link reads the prepared release; writing
through it would change that release. Keep preprocessing outputs elsewhere.

| Option | Meaning |
| --- | --- |
| `--dataset DIR` | Collection of prepared `R*/` datasets |
| `--output DIR` | Combined BIDS dataset |
| `--releases N …` | Bundle selected releases from 1–11; default is all available releases |
| `--reports DIR` | Default is the output's sibling `<output>_reports` |
| `--dry-run` | Inspect inputs and metadata compatibility without writing output |
| `--validate` | Run BIDS schema validation on the bundle, checking every row |
| `--validator PATH` | Override the validator executable; requirements include version 3.0.1 |

The Python API uses the same options:

```python
from hbn_bundle import bundle_dataset

summary = bundle_dataset(
    "HBN_AUGMENTED/EEG", "HBN_MERGED", releases=[1, 2], validate=True,
)
```

## Metadata decisions

- Each subject must occur in only one selected release. Duplicate IDs stop the
  build; subjects are not renamed or silently merged.
- Participant table columns are combined, with missing values written as `n/a`.
  For selected-subject builds, only linked subjects enter the combined participant table;
  original release files remain unchanged. Compatible definitions in `participants.json` are combined. Different
  description prose remains available in `SourceDefinitions`; conflicting
  units or category meanings stop the build.
- The bundle has its own `dataset_description.json`. `DatasetLinks` identifies
  the prepared input directories, and `SourceDatasets` retains their upstream
  source references. No new dataset DOI or common license is inferred.
- Selected releases must agree on `BIDSVersion` and `HEDVersion`.
- Shared root EEG/events JSON is linked into each applicable subject directory
  with that subject's prefix. Local recording sidecars retain precedence. This
  keeps release-specific inheritance without assigning one release's metadata
  to every subject. A collision with an existing subject-level sidecar stops
  bundling for review.
- Recording-quality rows are combined into `code/recording_quality.tsv`, with a
  merged JSON dictionary. `code/R*/` links retain each original release's tables
  and support files. Source-only candidates and human judgments are preserved.
- Existing `sourcedata/` directories, if present in the inputs, remain accessible
  under `sourcedata/R*/`. The tools do not add raw S3 ET/BEH archives. Conversion
  reports remain outside the prepared releases.

## Reports and reruns

Reports live outside the bundle, by default in `HBN_MERGED_reports`:

| File | What it records |
| --- | --- |
| `build.json` | Selected release paths, hashes of their three root metadata files, and links belonging to this build |
| `links.tsv` | Each linked file/directory and its source |
| `issues.tsv` | Metadata differences recorded during reconciliation |
| `summary.json` | Selected releases, subject count, output paths and validation outcome |
| `validation.json`, `validation.log` | Validator results, when requested |

Rerunning rebuilds the bundle's own links and root metadata, so releases can be
added or removed from the selection without repeating preparation. It clears
old validation results. A nonempty output must belong to an earlier bundle
build with its matching `build.json`; unexpected files or replaced links stop
the rebuild rather than being removed. Prepared source files are never edited.

With `--validate`, the schema validator checks every table row. It cannot
establish correct recording identity, synchronization or scientific usability.
Validation failures are reported in the summary and produce a nonzero CLI exit.

## Reuse outside HBN_BIDS

Copy the complete `hbn_bundle` folder into another project's root and install
its dependencies into that project's Python environment:

```bash
python -m pip install -r hbn_bundle/requirements.txt
```

Run the same CLI or import `bundle_dataset` from that root. The tool does not
depend on the downloaders, smi2bids, hbn_repair or hbn_augment code; it expects prepared
datasets with the layout and metadata described above.

