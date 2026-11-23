"""add verified behavioral information and eye tracking to repaired releases"""

from collections import Counter
from dataclasses import asdict
import json
from pathlib import Path
import shutil
from tempfile import TemporaryDirectory

from hbn_repair.inventory import eeg_releases, inheritance, plan_inputs
from hbn_repair.io import copy_file, read_table, sha256, validate_dataset, write_json, write_rows
from hbn_repair.quality import apply_validation
from smi2bids import smi2bids

from .behavior import BEHAVIOR_COLUMNS, augment_behavior, index_behavior
from .sync import estimate_sync, first_timestamp


# HBN_REPAIRED/EEG/Rn -> HBN_AUGMENTED/EEG/Rn; participant membership and repair findings survive
def augment_dataset(input, output, *, reports=None, releases=None, file_mode="copy",
                    metadata_file=None, max_residual_s=0.020, max_clock_deviation=0.01,
                    validate=False, validator="bids-validator-deno", dry_run=False):
    source, output = Path(input).resolve(), Path(output).resolve()
    reports = Path(reports).resolve() if reports else output.with_name(output.name + "_reports")
    paths = (source, output, reports)
    if any(a == b or a in b.parents or b in a.parents for index, a in enumerate(paths) for b in paths[index+1:]):
        raise ValueError("Input, output and reports must be separate trees")

    if output.exists() and any(output.iterdir()):
        raise FileExistsError(f"Use an empty output directory: {output}")

    roots = {number: root for number, root in eeg_releases(source).items()
             if releases is None or number in releases}
    if not roots:
        raise ValueError("No repaired releases selected")

    summary = {"status": "dry_run" if dry_run else "in_progress", "stage": "augment",
               "input": str(source), "output": str(output), "file_mode": file_mode,
               "metadata_sha256": sha256(Path(metadata_file)) if metadata_file else None,
               "max_residual_s": max_residual_s, "max_clock_deviation": max_clock_deviation,
               "releases": {}}

    for number, root in roots.items():
        quality = read_table(root / "code/recording_quality.tsv")
        definitions = json.loads((root / "code/recording_quality.json").read_text())
        if any(root.glob("sub-*/**/*_recording-eye*_physio.json")):
            raise ValueError(f"Already contains converted eye tracking; use the repaired EEG input: {root}")

        people = read_table(root / "participants.tsv")
        plan = plan_inputs(source, [number], [person["participant_id"] for person in people])
        behavior = index_behavior(source, {recording.subject for recording in plan.recordings})
        if dry_run:
            summary["releases"][f"R{number}"] = {
                "recordings": len(plan.recordings), "matching": dict(Counter(r.status for r in plan.recordings)),
                "et_inventory": dict(Counter(entry.status for entry in plan.et_entries)),
                "behavioral_source_files": sum(len(paths) for paths in behavior["subjects"].values()),
            }
            continue

        destination, release_reports = output / "EEG" / f"R{number}", reports / f"R{number}"
        release_reports.mkdir(parents=True, exist_ok=True)
        for name in ("validation.json", "validation.log"):
            (release_reports / name).unlink(missing_ok=True)
        write_json(reports / "summary.json", summary)
        shutil.copytree(root, destination,
                        copy_function=lambda src, dst: copy_file(Path(src), Path(dst), file_mode))

        results, anchors = [], []
        for index, recording in enumerate(plan.recordings, 1):
            result, fitted = convert_recording(recording, destination, release_reports, metadata_file,
                                              max_residual_s, max_clock_deviation)
            # B01/B02/B03 add behavior independently of whether ET conversion succeeded
            result.update(augment_behavior(recording, destination, behavior))
            results.append(result)
            anchors.extend(fitted)
            print(f"R{number} [{index}/{len(plan.recordings)}] {recording.prefix}: ET {result['et_status']}; "
                  f"B01 {result['beh_b01_status']}; B02 {result['beh_b02_status']}; B03 {result['beh_b03_status']}",
                  flush=True)

        update_quality(quality, definitions, results)
        description_path = destination / "dataset_description.json"
        description = json.loads(description_path.read_text())
        description["BIDSVersion"] = "1.11.2"
        description.setdefault("GeneratedBy", []).extend([
            {"Name": "hbn_augment", "Version": "1"}, {"Name": "smi2bids", "Version": "compact1"},
        ])
        write_json(description_path, description)
        changes = destination / "CHANGES"
        changes.write_text("Unreleased: added synchronized SMI eye tracking and verified behavioral information.\n"
                           "B01 task settings, B02 planned contrast intervals, B03 movie order/source names.\n"
                           "Existing EEG, task-event values and participants retained; see code/recording_quality.tsv.\n\n"
                           + changes.read_text())

        write_rows(destination / "code/recording_quality.tsv", quality)
        write_json(destination / "code/recording_quality.json", definitions)
        validation = "not_run"
        if validate:
            validation, diagnostics = validate_dataset(destination, release_reports, validator)
            apply_validation(quality, diagnostics)

        write_rows(destination / "code/recording_quality.tsv", quality)
        write_json(destination / "code/recording_quality.json", definitions)
        write_rows(release_reports / "recordings.tsv", results)
        write_rows(release_reports / "anchors.tsv", anchors,
                   ("prefix", "event_code", "eeg_onset_seconds", "et_timestamp_us"))
        write_rows(release_reports / "et_inventory.tsv", [asdict(entry) for entry in plan.et_entries],
                   ("subject", "task", "status", "files"))
        summary["releases"][f"R{number}"] = {
            "recordings": len(results), "quality_rows": len(quality),
            "et_status": dict(Counter(row["et_status"] for row in results)), "validation": validation,
            "behavior": {issue: dict(Counter(row[issue] for row in results))
                         for issue in BEHAVIOR_COLUMNS if issue.endswith("_status")},
        }
        write_json(reports / "summary.json", summary)

    if not dry_run:
        summary["status"] = "validation_failed" if any(
            isinstance(row["validation"], dict) and row["validation"]["returncode"]
            for row in summary["releases"].values()) else "complete"
        write_json(reports / "summary.json", summary)

    return summary


# one matched SMI pair -> added eye files and timing metrics; a failed pair leaves all EEG metadata intact
def convert_recording(recording, output, reports, metadata_file, max_residual_s, max_clock_deviation):
    relative = recording.eeg.relative_to(recording.release_root)
    collection = recording.release_root.parent.parent
    destination = output / relative.parent
    prefix = recording.prefix
    row = {"bids_path": str(relative), "et_status": recording.status,
           "et_samples": str(recording.et_samples.relative_to(collection)) if recording.et_samples else "n/a",
           "et_events": str(recording.et_events.relative_to(collection)) if recording.et_events else "n/a",
           "et_files": "n/a", "error": "n/a"}
    anchors = []
    if not recording.et_samples or not recording.et_events:
        return row, anchors

    row["et_status"] = "sync_failed"
    try:
        sync = estimate_sync(recording.eeg.with_name(prefix + "_events.tsv"), recording.et_events,
                             first_timestamp(recording.et_samples), max_residual_s=max_residual_s,
                             max_clock_deviation=max_clock_deviation)
        row.update(et_clock_scale=sync["clock_scale"],
                   et_drift_ppm=sync["drift_ppm"], et_anchors=sync["n_anchors"],
                   et_sync_max_residual_s=sync["max_residual_seconds"],
                   et_sync_warnings=";".join(sync["warnings"]) or "none")
        anchors = [{"prefix": prefix, **anchor} for anchor in sync["anchors"]]
        row["et_status"] = "conversion_failed"

        # stage effective metadata so conflicts are checked against inherited fields too
        # only successful conversions install the added fields into the final release
        inherited = inheritance(recording.eeg, "events", recording.release_root)
        task_metadata = inheritance(recording.eeg, "eeg", recording.release_root)
        shared = dict(inherited)
        for key in ("TaskName", "TaskDescription", "Instructions", "InstitutionName", "InstitutionAddress",
                    "InstitutionalDepartmentName", "CogAtlasID", "CogPOID"):
            if key in task_metadata and key not in shared:
                shared[key] = task_metadata[key]

        with TemporaryDirectory(prefix=".et-", dir=reports) as temporary:
            staging = Path(temporary)
            event_name = prefix + "_events.json"
            write_json(staging / event_name, shared)
            written = smi2bids(recording.et_samples, recording.et_events, metadata_file, staging,
                              prefix, sync["start_time"], clock_scale=sync["clock_scale"])
            for path in written:
                if path.name.endswith("_physio.json"):
                    metadata = json.loads(path.read_text())
                    metadata["HBNSynchronization"] = {key: value for key, value in sync.items() if key != "anchors"}
                    write_json(path, metadata)
                    conversion = metadata["SMIConversion"]
                    row.update(et_inserted_samples=conversion["InsertedSamples"],
                               et_source_samples=conversion["SourceSamples"], et_output_samples=conversion["OutputSamples"],
                               et_start_time=metadata["StartTime"],
                               et_sampling_frequency=metadata["SamplingFrequency"],
                               et_grid_rms_error_ms=1000 * sync["clock_scale"] * conversion["RMSGridResidualSeconds"],
                               et_grid_max_error_ms=1000 * sync["clock_scale"] * conversion["MaximumGridResidualSeconds"],
                               et_grid_pass_5pct=int(conversion["GridPass5Percent"]),
                               et_grid_pass_10pct=int(conversion["GridPass10Percent"]))
                    row[f"et_{metadata['RecordedEye']}_zero_gaze_samples"] = conversion["ZeroGazeSamples"]

            target = destination / event_name
            local = json.loads(target.read_text()) if target.exists() else {}
            merged = json.loads((staging / event_name).read_text())
            local.update({key: value for key, value in merged.items() if inherited.get(key) != value})
            write_json(target, local)
            eyes = [path for path in written if path.name != event_name]
            for path in eyes:
                path.replace(destination / path.name)
            row["et_files"] = ";".join(str(relative.parent / path.name) for path in eyes)

        row["et_status"] = "converted"
    except ValueError as error:
        row["error"] = str(error)

    return row, anchors


# extend the existing quality sheet by EEG path, retaining source-only rows and every original judgment
def update_quality(rows, definitions, results):
    columns = {
        "et_status": {"Description": "Eye-tracking augmentation outcome; not a signal-quality grade", "Levels": {
            "converted": "Aligned SMI files written", "missing_et": "No uniquely matched complete SMI pair",
            "ambiguous_et": "Multiple differing SMI candidates", "duplicate_eeg": "Non-unique EEG identity",
            "sync_failed": "Shared-event alignment failed", "conversion_failed": "SMI conversion failed",
            "not_applicable": "No EEG file in this release to augment"}},
        "et_samples": {"Description": "Matched Samples path relative to the repaired input collection"},
        "et_events": {"Description": "Matched Events path relative to the repaired input collection"},
        "et_files": {"Description": "Semicolon-separated added files, relative to this BIDS root"},
        "et_start_time": {"Description": "First grid sample relative to EEG start", "Units": "s"},
        "et_clock_scale": {"Description": "EEG seconds per device-clock second"},
        "et_drift_ppm": {"Description": "One million times (clock scale minus one)", "Units": "ppm"},
        "et_anchors": {"Description": "Number of matched timing anchors"},
        "et_sync_max_residual_s": {"Description": "Maximum absolute alignment residual", "Units": "s"},
        "et_sync_warnings": {"Description": "Semicolon-separated alignment warning codes; none if absent"},
        "et_source_samples": {"Description": "Observed source sample rows"},
        "et_output_samples": {"Description": "Output grid rows, including gaps"},
        "et_inserted_samples": {"Description": "Missing sampling slots inserted as n/a rows"},
        "et_sampling_frequency": {"Description": "Sampling frequency after clock-scale correction", "Units": "Hz"},
        "et_grid_rms_error_ms": {"Description": "RMS difference between observed native timestamps and the exported grid, on the EEG clock; inserted rows are excluded", "Units": "ms"},
        "et_grid_max_error_ms": {"Description": "Maximum absolute difference between observed native timestamps and the exported grid, on the EEG clock", "Units": "ms"},
        "et_grid_pass_5pct": {"Description": "Every observed sample is within 5% of one exported grid period", "Levels": {"0": "Fails", "1": "Passes"}},
        "et_grid_pass_10pct": {"Description": "Every observed sample is within 10% of one exported grid period", "Levels": {"0": "Fails", "1": "Passes"}},
        "et_left_zero_gaze_samples": {"Description": "Source rows with jointly zero left gaze coordinates"},
        "et_right_zero_gaze_samples": {"Description": "Source rows with jointly zero right gaze coordinates"},
    }
    columns.update(BEHAVIOR_COLUMNS)
    definitions.update(columns)
    results = {row["bids_path"]: row for row in results}
    validation_fields = ("validation_state", "validator_errors", "validator_warnings")
    for key in validation_fields:
        definitions["repair_" + key] = {**definitions[key], "Description": "Before augmentation: " + definitions[key]["Description"]}

    for row in rows:
        for key in validation_fields:
            row["repair_" + key] = row[key]
        row.update(validation_state="n/a" if row["in_bids"] == "1" else "not_applicable",
                   validator_errors="n/a", validator_warnings="n/a")
        row.update({column: "n/a" for column in columns})
        if row["in_bids"] == "1":
            result = results[row["bids_path"]]
            row.update({column: result[column] for column in columns if column in result})

            # matching may find additional exports supplied after the repair review
            if result["et_samples"] != "n/a" and result["et_events"] != "n/a":
                row["et_associated"] = 1
            elif result["et_status"] == "missing_et":
                row["et_associated"] = 0
            else:
                row["et_associated"] = "n/a"
        else:
            row["et_status"] = "not_applicable"
            row.update({column: "not_applicable" for column in BEHAVIOR_COLUMNS if column.endswith("_status")})
        row["et_in_bids"] = int(row["et_status"] == "converted")
