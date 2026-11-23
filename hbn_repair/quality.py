"""A09: one structured row per known recording, independent of its BIDS availability"""

from collections import defaultdict
from pathlib import Path
import json

from .io import write_json, write_rows
from .sources import source_recordings
from .events import MOVIES
from .overlap import compare_signals


SOURCE_RELEASES = {1: "ds005505", 2: "ds005506", 3: "ds005507", 4: "ds005508", 5: "ds005509",
                   6: "ds005510", 7: "ds005511", 8: "ds005512", 9: "ds005514", 10: "ds005515", 11: "ds005516"}
ISSUES = {
    "A01": "event_labels",
    "A02": "contrast_dictionary",
    "A03": "event_definitions",
    "A04": "time_units",
    "A05": "source_datasets_key",
    "A06": "hed_annotation",
    "A07": "channel_metadata",
    "A08": "acquisition_metadata",
    "A09": "upstream_quality",
    "A10": "task_overlap",
    "A11": "answer_alignment",
    "A12": "behavior_disagreement",
    "A13": "movie_markers",
    "A14": "event_extent",
    "A15": "unidentified_channels",
}

DATA = Path(__file__).with_name("data")
TASK_STARTS = {
    ("RestingState", "n/a"): "90",
    ("seqLearning6target", "n/a"): "91",
    ("seqLearning8target", "n/a"): "91",
    ("symbolSearch", "n/a"): "92",
    ("surroundSupp", "1"): "93",
    ("surroundSupp", "2"): "97",
    **{("contrastChangeDetection", str(run)): str(93 + run) for run in (1, 2, 3)},
    **{(task, "n/a"): code for task, code in MOVIES.items()},
}


# published rows + confirmed original exports -> union, with unresolved source identities kept visible
def recording_quality(number, source_id, participants, bids_rows, inventory, qc, et_entries, *, eeg_root):
    result = []
    by_subject = defaultdict(list)
    et_by_subject = defaultdict(list)
    for entry in et_entries:
        et_by_subject["sub-" + entry.subject].append(entry)

    for row in bids_rows:
        by_subject[row["participant_id"]].append(row)

    for person in participants:
        subject = person["participant_id"]
        records = by_subject[subject]
        classify_overlaps(records, eeg_root)
        raw = source_recordings(inventory[subject.removeprefix("sub-")], [row["task"] for row in records])
        unidentified = any(source["source_mapping"] == "unresolved" for source in raw)

        grouped = defaultdict(list)
        for source in raw:
            grouped[(source["task"], source["run"])].append(source)

        keys = {(row["task"], row["run"]) for row in records} | grouped.keys()
        for task, run in sorted(keys):
            sources = grouped[(task, run)]
            matches = [row for row in records if (row["task"], row["run"]) == (task, run)]

            # differing exports sharing a task name are separate evidence until their identity is established
            ambiguous = len({row["source_fingerprint"] for row in sources}) > 1 or len(matches) > 1
            rows = matches or [base_row(subject, task, run)]
            if ambiguous:
                rows = matches + [base_row(subject, task, run) | source for source in sources]

            for index, row in enumerate(rows):
                row = base_row(subject, task, run) | row
                if sources and not ambiguous:
                    row.update({key: value for key, value in sources[0].items() if key != "source_fingerprint"})
                    row["source_aliases"] = ";".join(source["source_task"] for source in sources)

                row.pop("source_fingerprint", None)
                if ambiguous:
                    row["in_s3"] = "n/a" if row["in_upstream_bids"] else 1
                    row["source_mapping"] = "ambiguous"
                elif sources:
                    row["in_s3"] = 1
                else:
                    row["in_s3"] = "n/a" if unidentified else 0

                task_key = task + ("_" + run if run != "n/a" else "")
                # A09: an unmatched source candidate cannot inherit a judgment about the published recording
                unassigned = ambiguous and not row["in_upstream_bids"]
                row.update(recording_id=f"R{number}/{subject}/{task_key}" + (f"/candidate-{index+1}" if ambiguous else ""),
                           source_release=source_id, release_number=f"R{number}",
                           upstream_status="n/a" if unassigned else person.get(task_key, "n/a"))
                original = {} if unassigned else qc.get((subject, task_key), {})
                for field in ("data_pnts", "event_cnt", "key_events_exist", "quality_checks"):
                    row["upstream_" + field] = original.get(field, "n/a")

                row["issue_availability"] = "present" if (
                    row["upstream_status"] == "available" and not row["in_upstream_bids"] or
                    row["upstream_status"] == "unavailable" and row["in_upstream_bids"]) else "absent"
                if unassigned:
                    row["issue_availability"] = "n/a"

                et = [entry for entry in et_by_subject[subject] if
                      (entry.mapped_task, entry.mapped_run or "n/a") == (task, run) or entry.task == row["source_task"]]
                if row["et_associated"] == "n/a" and et:
                    complete = [entry for entry in et if entry.samples and entry.events and entry.status not in
                                ("unresolved_identity", "ambiguous_pair", "invalid_events")]
                    row["et_associated"] = int(bool(complete))

                row["review_status"] = "partial" if row["in_bids"] else "unreviewed"
                result.append(row)

    return result


# A10: embedded movie + separate movie -> compare their shared signal; a break marker alone stays absent
def classify_overlaps(records, eeg_root):
    counterparts = defaultdict(list)
    for row in records:
        start = TASK_STARTS.get((row["task"], row["run"]))
        if start:
            counterparts[start].append(row)

    for row in records:
        column = "issue_a10_task_overlap"
        row[column] = "absent"
        own_start = TASK_STARTS.get((row["task"], row["run"]))
        starts = set(row["task_start_codes"].split(";")) - {"n/a"}
        other_starts = starts - {own_start}
        if not other_starts:
            continue

        row[column] = "unresolved"
        if own_start not in starts:
            continue

        # source-only exports do not count: records contains this participant's BIDS files in this release
        if any(not counterparts[code] for code in other_starts):
            row[column] = "present_counterpart_missing"
        elif all(len(counterparts[code]) == 1 and
                 code in counterparts[code][0]["task_start_codes"].split(";") for code in other_starts):
            comparisons = [compare_signals(eeg_root / row["bids_path"],
                                          eeg_root / counterparts[code][0]["bids_path"], code)
                           for code in sorted(other_starts)]
            outcome = ("differs" if "differs" in comparisons else
                       "matches" if all(value == "matches" for value in comparisons) else "unknown")
            row[column] = "present_counterpart_available_" + outcome


# a source-only recording starts with unknown checks, never an available recommendation inferred from absent flags
def base_row(subject, task, run):
    return {"recording_id": "n/a", "participant_id": subject, "source_release": "n/a", "release_number": "n/a",
            "task": task, "run": run, "upstream_status": "n/a", "in_s3": "n/a", "in_upstream_bids": 0, "in_bids": 0,
            "et_associated": "n/a", "et_in_bids": 0, "bids_path": "n/a", "source_task": "n/a",
            "source_mat": "n/a", "source_csv": "n/a", "source_mapping": "n/a", "embedded_in": "n/a",
            "source_aliases": "n/a", "task_start_codes": "n/a",
            **{f"issue_{key.lower()}_{name}": "n/a" for key, name in ISSUES.items()},
            "issue_a10_task_overlap": "unresolved",
            "mixed_task_starts": "n/a", "internal_boundary": "n/a", "movie_anchor_count": "n/a",
            "hed_feedback_annotated": "n/a", "hed_feedback_unresolved": "n/a",
            "hed_feedback_reasons": "n/a", "hed_contrast_unusual_timing": "n/a",
            "unknown_channel_identity": "n/a",
            "validation_state": "n/a", "validator_errors": "n/a", "validator_warnings": "n/a",
            "required_action": "review", "review_status": "unreviewed", "recommendation": "n/a"}


# explicit reviews override automatic screening; original source assessments remain separate
def apply_reviews(rows, reviews):
    lookup = {row["recording_id"]: row for row in rows}
    if len(lookup) != len(rows):
        raise ValueError("A09: duplicate recording identifiers")

    for review in reviews:
        row = lookup[review["recording_id"]]
        if review["recommendation"] not in ("available", "caution", "unavailable", "n/a"):
            raise ValueError("Recommendation must be available, caution, unavailable or n/a")
        if review["required_action"] not in ("none", "extract_task", "convert_source", "exclude", "review"):
            raise ValueError("Unknown required_action")
        if review["review_status"] not in ("unreviewed", "partial", "reviewed"):
            raise ValueError("Unknown review_status")

        for key in ("recommendation", "required_action", "review_status"):
            row[key] = review[key]

        if review["recommendation"] != "n/a":
            row.update(recommendation_method="existing_review", recommendation_reasons="existing_review")


# attach machine-readable validator outcomes to the affected recording; these are not EEG usability grades
def apply_validation(rows, issues):
    by_recording = defaultdict(list)
    for issue in issues:
        prefix = Path(issue["location"]).name.rsplit("_", 1)[0].split("_recording-", 1)[0]
        by_recording[prefix].append(issue)

    for row in rows:
        if str(row["in_bids"]) != "1":
            row["validation_state"] = "not_applicable"
            continue

        found = by_recording[Path(row["bids_path"]).name.removesuffix("_eeg.set")]
        for severity in ("error", "warning"):
            row["validator_" + severity + "s"] = ";".join(sorted({issue["code"] + (":" + issue["subCode"] if issue.get("subCode") else "")
                for issue in found if issue["severity"] == severity})) or "none"

        row["validation_state"] = ("error" if row["validator_errors"] != "none" else
                                   "warning" if row["validator_warnings"] != "none" else "pass")
        if any(issue["code"] == "HED_ERROR" for issue in found):
            row["issue_a06_hed_annotation"] = "present"


# publish the table with one column dictionary; cells contain numbers, paths or controlled labels, never prose
def write_quality(root, rows):
    definitions = json.loads((DATA / "quality_columns.json").read_text())
    states = {"absent": "Checked; issue not found", "present": "Review flag or unresolved issue remains; not a recording rejection",
              "fixed": "Issue was present and repaired", "not_applicable": "Check does not apply"}
    for issue, name in ISSUES.items():
        definitions[f"issue_{issue.lower()}_{name}"] = {"Description": f"{issue}: {name.replace('_', ' ')}", "Levels": states}

    definitions["issue_a10_task_overlap"] = {
        "Description": "A10: mixed-task markers and availability of separate same-participant task/run files in this release. "
                       "Availability requires a unique named BIDS counterpart containing its task start marker; "
                       "amplitudes are compared exactly at matching start markers across every channel and sample of the "
                       "shared interval, ending at the next task start or file end. Break markers alone do not flag overlap. "
                       "A match does not establish complete task coverage or good signal quality",
        "Levels": {
            "absent": "Checked; no identified extra task/run start in this recording",
            "present_counterpart_available_matches": "All extra task/run starts have separate counterparts; every compared shared interval matches exactly",
            "present_counterpart_available_differs": "All extra task/run starts have separate counterparts; at least one shared interval differs at marker alignment",
            "present_counterpart_available_unknown": "All extra task/run starts have separate counterparts, but at least one comparison is inconclusive and none establishes a difference",
            "present_counterpart_missing": "Other task/run starts are present and at least one has no separate BIDS counterpart",
            "unresolved": "Not inspected, uncertain task identity or ambiguous counterpart files",
        },
        "ComparisonLimitations": "Repeated start markers, different sample rates or channel order, or fewer than 32 shared samples leave amplitude comparison unknown. "
                                 "Differences are measured at marker alignment; no lag search, rereferencing or rescaling is attempted. "
                                 "When several tasks are embedded, a missing counterpart takes priority; otherwise any established difference takes priority over unknown comparisons",
    }
    for column in rows[0] if rows else ():
        if column not in definitions:
            definitions[column] = {"Description": column.replace("_", " ")}

    write_rows(root / "code/recording_quality.tsv", rows)
    write_json(root / "code/recording_quality.json", definitions)
