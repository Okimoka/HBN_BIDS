# smi2bids

`smi2bids` takes the two eye-tracking files that are obtained when exporting an SMI iView X `.idf` file using the converter found in the SMI iTools toolkit (`*_Samples.txt` and `*_Events.txt`), and converts them to the BIDS-compliant representation introduced in BIDS 1.11. (`physio.tsv.gz`/`physioevents.tsv.gz`). The current project aims to comply specifically with [BIDS 1.11.2](https://bids-specification.readthedocs.io/en/stable/modality-specific-files/physiological-recordings.html#eye-tracking).

It is meant as an analog to the official [eye2bids repository](https://github.com/bids-standard/eye2bids), which only supports EyeLink files (`.edf`/`.asc`).

`smi2bids` was specifically created with the HBN dataset in mind, but can also be used standalone in another project by simply installing its requirements, i.e.
```bash
python -m pip install -r smi2bids/requirements.txt
```
after which it can be imported normally via `from smi2bids import smi2bids` (or CLI).

In the HBN_BIDS workflow, `smi2bids` is called by the `hbn_augment` utility -- follow the
setup steps in the [root README](../README.md).

## Python API

The converter returns a list of paths to the files written:

```python
from smi2bids import smi2bids

paths = smi2bids(
    samples_file="recording_Samples.txt",
    events_file="recording_Events.txt",
    metadata_file="metadata.yaml",
    output_dir="DATASET_BIDS/sub-01/eeg",
    bids_prefix="sub-01_task-rest",
    start_time=-0.137,
    clock_scale=1.0,
    overwrite=False,
)

print(paths[0])
# e.g. DATASET_BIDS/sub-01/eeg/sub-01_task-rest_recording-eye1_physio.tsv.gz
```

or equivalently via CLI:

```bash
python -m smi2bids \
  --samples-file recording_Samples.txt \
  --events-file recording_Events.txt \
  --metadata-file metadata.yaml \
  --output-dir DATASET_BIDS/sub-01/eeg \
  --bids-prefix sub-01_task-rest \
  --start-time -0.137
```

`start_time` is the time of the first observed ET sample relative
to EEG start, in seconds. A negative value means eye tracking started earlier.
The output grid's `StartTime` can differ slightly; its offset and the original
timestamp mapping are retained in `SMIConversion`.

`metadata.yaml` functions similarly as in `eye2bids` see [Metadata](#metadata).

The output files use the supplied `<bids-prefix>`:

| Output | Contents | Written when |
| --- | --- | --- |
| `<bids-prefix>_recording-eye1_physio.tsv.gz` + `.json` | Left-eye samples and column/acquisition metadata | The export has left-eye columns |
| `<bids-prefix>_recording-eye2_physio.tsv.gz` + `.json` | Right-eye samples and column/acquisition metadata | The export has right-eye columns |
| `<bids-prefix>_recording-eye1_physioevents.tsv.gz` + `.json` (likewise `eye2`) | Existing SMI events for that eye, including shared messages/triggers | The eye has samples and applicable events |
| `<bids-prefix>_events.json` | Shared display/task metadata, merged with an existing sidecar if present | Always |

The compressed TSV files have no header row; their JSON sidecars list the columns.
The caller supplies the surrounding BIDS dataset, associated EEG files, and
task `_events.tsv` to which the generated display metadata belongs.


## Metadata

The `metadata.yaml` supplies metadata information that cannot be inferred from the export headers. See [metadata_template.yaml](metadata_template.yaml) for a guide on how to construct it, as well as assumptions made for the metadata attributes. If all necessary metadata information can be inferred from the export headers, `--metadata-file` can be omitted.

Conversion choices, column mappings, timing, metadata assumptions and the
`SMIConversion` diagnostics are documented under “C. Eye-tracking integration” in the
[project report](../report/report.pdf).
