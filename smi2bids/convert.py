"""Build metadata and write one SMI recording's BIDS files"""

from collections import Counter
import hashlib
import json
import math
from pathlib import Path
import re
from tempfile import TemporaryDirectory

import yaml

from .events import read_events
from .samples import read_samples, regular_grid, split_eyes


# convert one Samples/Events pair into per-eye physio/physioevents files and shared events JSON
# for bids_prefix="sub-01_task-rest", outputs include:
#   sub-01_task-rest_recording-eye1_physio.tsv.gz
#   sub-01_task-rest_recording-eye1_physio.json
# returns the generated paths as a list
def smi2bids(samples_file: str | Path, events_file: str | Path,
             metadata_file: str | Path | None, output_dir: str | Path,
             bids_prefix: str, start_time: float, *, clock_scale: float = 1.0,
             overwrite: bool = False) -> list[Path]:
    """convert one export pair; start_time locates its first native sample on the reference clock

    Grid-origin adjustments affect output StartTime, not the preserved native mapping
    Returns generated Paths. No files change until parsing, timing, metadata and
    output serialization succeed. See README for scientific conversion policies
    """
    if not re.fullmatch(r"sub-[A-Za-z0-9]+(?:_[A-Za-z]+-[A-Za-z0-9]+)*", bids_prefix):
        raise ValueError("Expected a BIDS entity prefix, e.g. sub-NDARAB793GL3_task-symbolSearch_run-1")
    entities = dict(entity.split("-", 1) for entity in bids_prefix.split("_"))
    if "recording" in entities:
        raise ValueError("The converter supplies the recording entity")
    task = entities["task"]
    if not math.isfinite(start_time) or not math.isfinite(clock_scale) or clock_scale <= 0:
        raise ValueError("StartTime must be finite and clock_scale positive and finite")

    header, frame, sample_messages = read_samples(samples_file)
    # report holds grid diagnostics, then provenance; it becomes SMIConversion in each eye's JSON
    indices, period, report = regular_grid(frame, float(header["Sample Rate"]))
    eyes = split_eyes(frame, indices)
    available_eyes = {"L" if label == "eye1" else "R" for label in eyes}
    events, event_messages = read_events(events_file, clock_scale, available_eyes)
    if Counter(sample_messages) != Counter(event_messages):
        raise ValueError("Samples MSG and Events UserEvent messages differ; reconcile exports first")

    output_dir = Path(output_dir)
    run_name = f"{bids_prefix}_events.json"
    run_path = output_dir / run_name
    existing_run = json.loads(run_path.read_text()) if run_path.exists() else {}
    # an existing task label may be descriptive rather than the filename's task entity
    physio_metadata, run_metadata = prepare_metadata(header, frame, metadata_file, existing_run.get("TaskName", task))
    run_metadata = merge(existing_run, run_metadata, strict=True)
    generated_columns = {column for _, metadata, _ in eyes.values() for column in metadata}
    if generated_columns.intersection(physio_metadata):
        raise ValueError("Column definitions are generated from the SMI export, not supplied in YAML")

    report.update(ClockScale=clock_scale, SourceSampleHeader=header,
                  FirstTimestampReferenceSeconds=start_time,
                  TimeMapping="reference_seconds = FirstTimestampReferenceSeconds + ClockScale * (timestamp - FirstTimestamp) / 1e6",
                  Software="smi2bids compact 1",
                  Sources=[{"File": Path(path).name, "SHA256": hashlib.sha256(Path(path).read_bytes()).hexdigest()}
                           for path in (samples_file, events_file)])

    for key in ("ScreenDistance", "ScreenOrigin", "ScreenResolution", "ScreenSize"):
        if key not in run_metadata["StimulusPresentation"]:
            raise ValueError(f"Supply missing StimulusPresentation.{key} in metadata YAML")

    tables, sidecars = {}, {run_name: run_metadata}
    for label, (data, metadata, zero_counts) in eyes.items():
        stem = f"{bids_prefix}_recording-{label}"
        tables[f"{stem}_physio.tsv.gz"] = data
        sidecars[f"{stem}_physio.json"] = {
            **physio_metadata, **metadata, "PhysioType": "eyetrack",
            "StartTime": start_time + clock_scale * report["GridOriginOffsetSeconds"],
            "SamplingFrequency": 1 / (period * clock_scale),
            "SMIConversion": {**report, "ZeroGazeSamples": zero_counts["gaze"],
                              "ZeroGroupSamples": zero_counts},
        }

        if label in events:
            table, event_metadata = events[label]
            tables[f"{stem}_physioevents.tsv.gz"] = table
            sidecars[f"{stem}_physioevents.json"] = {
                **event_metadata, "TaskName": run_metadata["TaskName"],
                "Description": "SMI event-detector export; classifications retained without re-detection.",
            }

    # only these eight exact eye-file names belong to this converter. Shared EEG
    # events metadata is merged above; ordinary events.tsv is never touched
    owned = {output_dir / f"{bids_prefix}_recording-{eye}_{suffix}.{extension}"
             for eye in ("eye1", "eye2") for suffix in ("physio", "physioevents")
             for extension in ("json", "tsv.gz")}
    existing = {path for path in owned if path.exists()}
    if existing and not overwrite:
        raise FileExistsError(f"Outputs already exist; use overwrite=True: {sorted(existing)[0]}")

    output_dir.mkdir(parents=True, exist_ok=True)
    with TemporaryDirectory(prefix=".smi2bids-", dir=output_dir) as temporary:
        staging = Path(temporary)
        for name, table in tables.items():
            # omit gzip's filename header to avoid BIDS privacy warnings
            with (staging / name).open("wb") as stream:
                table.to_csv(stream, sep="\t", index=False, header=False, lineterminator="\n",
                             compression={"method": "gzip", "mtime": 0, "filename": ""})

        for name, metadata in sidecars.items():
            (staging / name).write_text(json.dumps(metadata, indent=2, ensure_ascii=False, allow_nan=False) + "\n")

        written = [output_dir / name for name in [*tables, *sidecars]]
        for destination in written:
            (staging / destination.name).replace(destination)
        for stale in existing - set(written):
            stale.unlink()

    return written


# derive metadata, apply YAML overrides, then return (eye metadata, shared run metadata)
# for example, header "Head Distance [mm]": "600" becomes ScreenDistance: 0.6 m
def prepare_metadata(header, frame, metadata_file, task):
    metadata = {"Manufacturer": "SensoMotoric Instruments", "SampleCoordinateSystem": "gaze-on-screen",
                "TaskName": task}

    screen = {"ScreenOrigin": ["top", "left"]}
    for source, target, divisor in [("Calibration Area", "ScreenResolution", 1),
                                     ("Stimulus Dimension [mm]", "ScreenSize", 1000),
                                     ("Head Distance [mm]", "ScreenDistance", 1000)]:
        if source in header:
            values = [value / divisor for value in numbers(header[source])]
            screen[target] = values[0] if target == "ScreenDistance" else values[:2]
    metadata["StimulusPresentation"] = screen

    versions = [f"{key}: {header[key]}" for key in ("Version", "IDF Version", "iView X Version") if key in header]
    if versions:
        metadata["SoftwareVersions"] = "; ".join(versions)

    system = header.get("System ID", "")
    if "//" in system:
        metadata["DeviceSerialNumber"], model = system.split("//", 1)
        metadata["ManufacturersModelName"] = model.split("///", 1)[0]

    if any(re.match(r"[LR] CR", column) for column in frame.columns):
        metadata["EyeTrackingMethod"] = "P-CR"

    calibration = [numbers(value) for key, value in header.items() if key.startswith("Calibration Point ")]
    if calibration:
        metadata.update(CalibrationPosition=calibration, CalibrationUnit="pixel")
    if "Calibration Type" in header:
        metadata["CalibrationType"] = header["Calibration Type"]

    # cursor filtering affects display only; its settings remain in SourceSampleHeader
    filters = [f"{key}={header[key]}" for key in ("Heuristic", "Heuristic Stage", "Bilateral") if key in header]
    if filters:
        metadata["RawDataFilters"] = "; ".join(filters)

    supplied = {}
    if metadata_file:
        supplied = yaml.safe_load(Path(metadata_file).read_text()) or {}
    structural = {"StartTime", "SamplingFrequency", "Columns", "RecordedEye", "PhysioType", "SMIConversion"}
    if structural.intersection(supplied):
        raise ValueError(f"Generated metadata cannot be overridden: {structural.intersection(supplied)}")

    metadata = merge(metadata, supplied)
    if metadata["SampleCoordinateSystem"] != "gaze-on-screen":
        raise ValueError("This converter supports SMI gaze-on-screen exports")

    run_keys = {"TaskName", "InstitutionAddress", "InstitutionName", "StimulusPresentation", "VisionCorrection"}
    run = {key: value for key, value in metadata.items() if key in run_keys}
    physio = {key: value for key, value in metadata.items() if key not in run_keys or key == "TaskName"}
    return physio, run


# combine metadata dictionaries, keeping existing values when the override is None
# example:
#   merge({"rate": 500}, {"rate": None, "model": "RED"})
# returns:
#   {"rate": 500, "model": "RED"}
def merge(left, right, *, strict=False):
    """Overlay non-null values; strict merging refuses conflicting EEG metadata"""
    result = dict(left)
    for key, value in right.items():
        if value is None:
            continue

        previous = result.get(key)
        if isinstance(previous, dict) and isinstance(value, dict):
            value = merge(previous, value, strict=strict)
        elif strict and previous is not None and previous != value:
            raise ValueError(f"Conflicting existing metadata for {key}: {previous!r} != {value!r}")
        result[key] = value

    return result


# extract numeric header values: "1920 x 1080" -> [1920.0, 1080.0]
def numbers(text):
    return [float(value) for value in re.findall(r"[-+]?(?:\d+(?:\.\d*)?|\.\d+)", text)]
