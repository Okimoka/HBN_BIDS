"""repair the published EEG releases, then stop for human review before augmentation"""

from collections import Counter
import json
from pathlib import Path
import shutil

from .events import MOVIES, read_header, repair_labels, review_events, task_run, write_set
from .inventory import plan_inputs, inheritance, entities
from .io import sha256, write_json, write_rows, read_table, validate_dataset
from .quality import (
    DATA, ISSUES, SOURCE_RELEASES,
    apply_reviews, apply_validation, base_row, recording_quality, write_quality,
)
from .metadata import (
    event_overrides, repair_channels, repair_dictionary,
    self_contained_hed, initial_offset_annotation, feedback_annotations,
)
from .sources import source_inventory
from .ratings import apply_ratings


# HBN_RAW -> HBN_REPAIRED/EEG/Rn plus ET/BEH links; outputs must be new and separate
def repair_dataset(input, output, *, reports=None, subjects=None, releases=None, file_mode="copy",
                   source_inventory_file=None, reviews=None, validate=False, validator="bids-validator-deno"):
    source, output = Path(input).resolve(), Path(output).resolve()
    reports = Path(reports).resolve() if reports else output.with_name(output.name + "_reports")
    paths = (source, output, reports)
    if any(a == b or a in b.parents or b in a.parents for index, a in enumerate(paths) for b in paths[index+1:]):
        raise ValueError("Input, output and reports must be separate trees")

    if output.exists() and any(output.iterdir()):
        raise FileExistsError(f"Use an empty output directory: {output}")

    print("A09: inventory releases, original EEG exports and ET associations", flush=True)
    plan = plan_inputs(source, releases, subjects)
    people = {number: read_table(root / "participants.tsv") for number, root in plan.releases.items()}
    if subjects:
        selected = {"sub-" + subject.removeprefix("sub-") for subject in subjects}
        people = {number: [row for row in rows if row["participant_id"] in selected] for number, rows in people.items()}

    selected_subjects = {row["participant_id"].removeprefix("sub-") for rows in people.values() for row in rows}
    inventory_path = Path(source_inventory_file).resolve() if source_inventory_file else reports / "s3_inventory.json"
    inventory = source_inventory(selected_subjects, inventory_path)
    known = {row["recording"]: row for row in read_table(DATA / "behavior_review.tsv")}
    definitions = json.loads((DATA / "event_columns.json").read_text())

    ratings = read_table(Path(reviews)) if reviews else []
    if len({row["recording_id"] for row in ratings}) != len(ratings):
        raise ValueError("A09: duplicate recording_id in review input")

    output.mkdir(parents=True, exist_ok=True)
    reports.mkdir(parents=True, exist_ok=True)
    for name in ("ET", "BEH"):
        if (source / name).exists():
            (output / name).symlink_to(source / name, target_is_directory=True)

    release_results = {}
    summary = {"status": "in_progress", "stage": "repair", "input": str(source), "output": str(output),
               "source_inventory": str(inventory_path), "file_mode": file_mode, "releases": release_results}
    write_json(reports / "summary.json", summary)

    all_ids = set()
    for number, root in plan.releases.items():
        destination = output / "EEG" / f"R{number}"
        release_reports = reports / f"R{number}"
        release_reports.mkdir(parents=True, exist_ok=True)
        people_ids = {row["participant_id"] for row in people[number]}
        recordings = [recording for recording in plan.recordings if recording.release == number]

        print(f"R{number}: A02–A06/A09 shared metadata and original quality tables", flush=True)
        tasks = {entities(recording.prefix)["task"] for recording in recordings}
        qc, shared_issues = copy_release(root, destination, people_ids, file_mode, definitions, tasks)
        source_id = SOURCE_RELEASES[number]

        rows, changes = [], []
        for index, recording in enumerate(recordings, 1):
            row, edits = repair_recording(
                recording, destination, definitions, known, shared_issues, source / "BEH", source / "ET",
            )
            rows.append(row)
            changes.extend({"file": str(recording.eeg.relative_to(root)), **edit} for edit in edits)
            if index % 100 == 0 or index == len(recordings):
                print(f"R{number}: A01/A07/A08/A10–A15 inspected {index}/{len(recordings)} recordings", flush=True)

        quality = recording_quality(number, source_id, people[number], rows, inventory, qc, plan.et_entries,
                                    eeg_root=destination)
        ids = {row["recording_id"] for row in quality}
        apply_reviews(quality, [row for row in ratings if row["recording_id"] in ids])
        all_ids.update(ids)
        apply_ratings(quality)
        write_quality(destination, quality)
        write_rows(release_reports / "changes.tsv", changes, ("file", "issue", "field", "before", "after"))

        validation = "not_run"
        if validate:
            validation, diagnostics = validate_dataset(destination, release_reports, validator)
            apply_validation(quality, diagnostics)
            apply_ratings(quality)
            write_quality(destination, quality)

        counts = {issue: dict(Counter(row[f"issue_{issue.lower()}_{name}"] for row in quality))
                  for issue, name in ISSUES.items()}
        release_results[f"R{number}"] = {
            "participants": len(people[number]), "bids_recordings": len(rows), "quality_rows": len(quality),
            "source_only_rows": sum(not row["in_bids"] for row in quality), "issues": counts,
            "changes": len(changes), "validation": validation,
        }
        write_json(reports / "summary.json", summary)

    if unknown := {row["recording_id"] for row in ratings} - all_ids:
        raise ValueError(f"A09: review rows do not belong to the selection: {sorted(unknown)}")

    summary["status"] = "validation_failed" if any(isinstance(row["validation"], dict) and row["validation"]["returncode"]
                                                  for row in release_results.values()) else "complete"
    write_json(reports / "summary.json", summary)
    return summary


# retain the original tree and participant files; copy/link unchanged signal containers
def copy_release(source, destination, subjects, mode, definitions, tasks):
    qc, issues = {}, set()
    for path in sorted(source.rglob("*")):
        if path.suffix.lower() not in (".set", ".fdt") and path.is_dir():
            continue

        relative = path.relative_to(source)
        if relative.parts[0].startswith("sub-") and relative.parts[0] not in subjects:
            continue

        # a selected subset must not have orphan task sidecars referring to excluded recordings
        if relative.parent == Path(".") and entities(path.stem).get("task", "") not in tasks | {""}:
            continue

        target = destination / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        if path.name.endswith("_events.json"):
            metadata, fixed = repair_dictionary(
                json.loads(path.read_text()), definitions, entities(path.stem).get("task"),
            )
            write_json(target, metadata)
            issues.update(fixed)
        elif path.name.endswith("_quality_table.tsv"):
            with path.open() as stream:
                delimiter = "," if "," in stream.readline() else "\t"
            original = read_table(path, delimiter)
            task = path.name.removesuffix("_quality_table.tsv")
            for row in original:
                qc[("sub-" + row["Row"].removeprefix("sub-"), task)] = row

            # original QC remains a historical table, including rows outside the selected participant cohort
            write_rows(target, original, original[0].keys() if original else ())
            if delimiter == ",":
                issues.add("A09")
        elif mode == "symlink" and path.suffix.lower() in (".set", ".fdt"):
            target.symlink_to(path)
        else:
            shutil.copy2(path, target)

    description_path = destination / "dataset_description.json"
    description = json.loads(description_path.read_text())
    if "SourceDatesets" in description:
        old = description.pop("SourceDatesets")
        if "SourceDatasets" in description and description["SourceDatasets"] != old:
            raise ValueError("A05: conflicting SourceDatasets definitions")
        description["SourceDatasets"] = old
        issues.add("A05")

    description.setdefault("GeneratedBy", []).append({"Name": "hbn_repair", "Version": "1"})
    write_json(description_path, description)

    changes = destination / "CHANGES"
    previous = changes.read_text() if changes.exists() else ""
    changes.write_text("Unreleased: hbn_repair A01–A15 EEG metadata/label repairs and recording quality inventory.\n"
                       "Signal samples, event codes and timing retained; see code/recording_quality.tsv.\n\n" + previous)

    return qc, issues


# A01/A07/A08/A10–A15: one recording -> output overrides and structured findings, without segmentation or preprocessing
def repair_recording(recording, output, definitions, known, shared_issues, behavior_root, et_root):
    path = recording.eeg
    target = output / path.relative_to(recording.release_root)
    events_path = path.with_name(recording.prefix + "_events.tsv")
    original = read_table(events_path)
    header = read_header(path)
    rows, labels = repair_labels(original, header)
    task, run = task_run(entities(recording.prefix), rows)

    result = base_row("sub-" + recording.subject, task, run)
    result.update(
        in_upstream_bids=1, in_bids=1, bids_path=str(target.relative_to(output)),
        et_associated=1 if recording.status == "matched" else
                      0 if recording.status == "missing_et" and et_root.exists() else "n/a",
    )
    result.update(review_events(rows, header, task))

    states = {issue: "absent" for issue in ISSUES}
    states.update(A10="unresolved" if result["mixed_task_starts"] else "absent",
                  A11="n/a" if task == "symbolSearch" else "not_applicable",
                  A12="not_applicable" if task in MOVIES else "n/a",
                  A13="n/a" if task in MOVIES else "not_applicable",
                  A14="present" if result.pop("event_ends_after_recording") else "absent",
                  A05="fixed" if "A05" in shared_issues else "absent",
                  A09="fixed" if "A09" in shared_issues else "absent")

    edits = [{"issue": "A01", "field": f"events.tsv:L{change['line']}:value", **change} for change in labels]
    if labels:
        states["A01"] = "fixed"
        write_rows(target.with_name(recording.prefix + "_events.tsv"), rows)
        if any(str(event["type"]) != row["value"] for event, row in zip(header["events"], rows)):
            hashes = write_set(path, target, [row["value"] for row in rows])
            edits.append({"issue": "A01", "field": ".set.event.type", **hashes})

    # A11–A13: retained comparisons apply only to matching event bytes and the inspected behavioral source
    evidence = known.get(f"R{recording.release}/" + str(events_path.relative_to(recording.release_root)))
    if evidence and evidence["events_sha256"] == sha256(events_path):
        states["A10"] = "unresolved" if evidence["A10"] == "present" else states["A10"]
        if evidence["behavior_sha256"] != "n/a":
            relative = Path(evidence["behavior_source"])
            candidates = [behavior_root / relative.parts[0] / Path(*relative.parts[2:]), et_root / relative]
            source = next((candidate for candidate in candidates if candidate.is_file()), None)
            if source and sha256(source) == evidence["behavior_sha256"]:
                for issue in ("A11", "A12", "A13"):
                    states[issue] = evidence[issue]

    if result["movie_anchor_count"]:
        states["A13"] = "present"

    # A01/A02/A03/A04/A06: correct definitions and add only necessary local overrides
    events = inheritance(path, "events", recording.release_root)
    repaired, fixed = repair_dictionary(events, definitions, task)
    overrides, added = event_overrides(repaired, rows, labels, definitions)
    fixed |= added
    rows, final_events, feedback = feedback_annotations(rows, repaired | overrides, events)
    feedback_unresolved = sum(count for reason, count in feedback.items() if reason not in ("annotated", "unusual_timing"))
    result.update(
        hed_feedback_annotated=feedback["annotated"], hed_feedback_unresolved=feedback_unresolved,
        hed_feedback_reasons=";".join(sorted(reason for reason, count in feedback.items()
                                             if count and reason not in ("annotated", "unusual_timing"))) or "none",
        hed_contrast_unusual_timing=feedback["unusual_timing"],
    )
    if feedback["annotated"] or feedback["unusual_timing"]:
        fixed.add("A06")

    if feedback["annotated"]:
        write_rows(target.with_name(recording.prefix + "_events.tsv"), rows)
        edits.append({"issue": "A06", "field": "events.tsv:HED", "before": "n/a", "after": dict(feedback)})

    rows, final_events, initial_offset = initial_offset_annotation(rows, final_events)
    result["initial_offset_unpaired"] = int(initial_offset)
    if initial_offset:
        write_rows(target.with_name(recording.prefix + "_events.tsv"), rows)
        fixed.add("A06")
        edits.append({"issue": "A06", "field": "events.tsv:hed_annotation", "before": "n/a", "after": "initial_offset_point"})

    overrides = {key: value for key, value in final_events.items() if events.get(key) != value}
    if overrides:
        event_target = target.with_name(recording.prefix + "_events.json")
        local = json.loads(event_target.read_text()) if event_target.exists() else {}

        # inherited corrections already written at the root need no duplicate local override
        effective = inheritance(target, "events", output)
        local.update({key: value for key, value in overrides.items() if effective.get(key) != value})
        if local:
            write_json(event_target, self_contained_hed(local, final_events))

    for issue in fixed:
        states[issue] = "fixed"
    if feedback_unresolved or feedback["unusual_timing"]:
        states["A06"] = "present"

    for field, value in overrides.items():
        edits.append({"issue": ";".join(sorted(fixed | ({"A01"} if labels else set()))),
                      "field": "events.json:" + field, "before": events.get(field), "after": value})

    # A07/A08: fill only supported channel metadata, and retain the remaining acquisition gaps
    eeg = inheritance(path, "eeg", recording.release_root)
    channels_path = path.with_name(recording.prefix + "_channels.tsv")
    channels = read_table(channels_path)
    new_eeg, new_channels, fixed, unresolved = repair_channels(eeg, channels, header)
    result["unknown_channel_identity"] = int(not header["channel_names"] or len(channels) == 6)
    states["A15"] = "present" if result["unknown_channel_identity"] else "absent"

    if channels != new_channels:
        write_rows(target.with_name(recording.prefix + "_channels.tsv"), new_channels)
        edits.append({"issue": "A07", "field": "channels.type/units", "before": "n/a", "after": "EEG/uV"})

    if new_eeg != eeg:
        local_path = target.with_suffix(".json")
        local = json.loads(local_path.read_text()) if local_path.exists() else {}
        local.update({key: value for key, value in new_eeg.items() if eeg.get(key) != value})
        write_json(local_path, local)
        edits.append({"issue": "A08", "field": "EEGChannelCount", "before": eeg.get("EEGChannelCount"), "after": new_eeg["EEGChannelCount"]})

    for issue in fixed:
        states[issue] = "fixed"
    if unresolved and not result["unknown_channel_identity"]:
        states["A07"] = "present"

    result["acquisition_fields_missing"] = ";".join(key for key in (
        "EEGChannelCount", "EEGGround", "CapManufacturer", "CapManufacturersModelName", "SoftwareVersions", "DeviceSerialNumber"
    ) if key not in new_eeg) or "n/a"
    result["eeg_channel_count_added"] = int("A08" in fixed)
    if result["acquisition_fields_missing"] != "n/a":
        states["A08"] = "present"

    for issue, name in ISSUES.items():
        result[f"issue_{issue.lower()}_{name}"] = states[issue]

    return result, edits

