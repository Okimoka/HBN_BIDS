"""assign transparent EEG screening recommendations and export a combined recording sheet"""

from collections import Counter
import json
from pathlib import Path

from .io import read_table, sha256, write_json, write_rows


# these ten recordings were inspected for A15; other recordings by these people are not blacklisted
UNUSABLE_RECORDINGS = {
    f"R7/sub-{subject}/{task}"
    for subject, tasks in {
        "NDARBA381JGH": ("DespicableMe", "DiaryOfAWimpyKid", "FunwithFractals", "RestingState",
                        "seqLearning8target", "symbolSearch"),
        "NDARUJ292JXV": ("RestingState", "seqLearning8target", "surroundSupp_1", "symbolSearch"),
    }.items()
    for task in tasks
}
CAVEAT_ISSUES = ("issue_a06_hed_annotation", "issue_a11_answer_alignment", "issue_a12_behavior_disagreement",
                 "issue_a13_movie_markers", "issue_a14_event_extent")
DATA = Path(__file__).with_name("data")


# a validated EEG row with no screened caveat -> ("available", "no_detected_obstacle")
# source-only EEG -> ("unavailable", "no_assessed_bids_recording") for the delivered collection
def rate_recording(row):
    if row["recording_id"] in UNUSABLE_RECORDINGS:
        return "unavailable", "confirmed_unusable_signal"

    if str(row["in_bids"]) != "1":
        return "unavailable", "no_assessed_bids_recording"

    if str(row["unknown_channel_identity"]) != "0":
        return "caution", "unassessed_channel_identity"
    if row.get("repair_validation_state", row["validation_state"]) not in ("pass", "warning"):
        return "caution", "validation_incomplete_or_failed"
    if row["issue_a10_task_overlap"] == "unresolved":
        return "caution", "unresolved_task_identity"

    reasons = [column for column in CAVEAT_ISSUES if row[column] == "present"]
    if row["issue_a10_task_overlap"] != "absent":
        reasons.append("issue_a10_task_overlap")
    if row["upstream_status"] != "available":
        reasons.append("upstream_status")
    if str(row["upstream_key_events_exist"]) == "0":
        reasons.append("upstream_key_events_exist")
    if row["source_mapping"] == "ambiguous":
        reasons.append("source_mapping")
    if str(row["movie_anchor_count"]) == "1":
        reasons.append("movie_anchor_count")

    return ("caution", ";".join(reasons)) if reasons else ("available", "no_detected_obstacle")


# fill automatic assessments in place; explicitly supplied ratings keep precedence
def apply_ratings(rows):
    for row in rows:
        if row["recommendation"] != "n/a" and row.get("recommendation_method") not in ("automatic_v1", "automatic_v2"):
            row.setdefault("recommendation_method", "existing_review")
            row.setdefault("recommendation_reasons", "existing_review")
            continue

        recommendation, reasons = rate_recording(row)
        action = "none"
        if recommendation == "unavailable" or reasons in (
                "unassessed_channel_identity", "validation_incomplete_or_failed", "unresolved_task_identity"):
            action = "review"
        if reasons == "confirmed_unusable_signal":
            action = "exclude"

        row.update(recommendation=recommendation, recommendation_method="automatic_v2",
                   recommendation_reasons=reasons, required_action=action)


# HBN_AUGMENTED/EEG -> report/recording_quality.tsv.gz and its dictionary; inputs stay unchanged
def export_ratings(dataset, output):
    paths = sorted(Path(dataset).glob("R*/code/recording_quality.tsv"), key=lambda path: int(path.parts[-3][1:]))
    rows, definitions, sources = [], {}, []
    for path in paths:
        rows.extend(read_table(path))
        definitions.update(json.loads(path.with_suffix(".json").read_text()))
        sources.append({"Path": str(path.relative_to(dataset)), "SHA256": sha256(path)})

    if not rows:
        raise ValueError("No recording-quality rows found under R*/code/recording_quality.tsv")
    if len({row["recording_id"] for row in rows}) != len(rows):
        raise ValueError("Duplicate recording identifiers in the combined quality sheet")

    apply_ratings(rows)
    schema = json.loads((DATA / "quality_columns.json").read_text())
    for key in ("recommendation", "recommendation_method", "recommendation_reasons", "required_action",
                "ReviewProtocol", "RecommendationRules"):
        definitions[key] = schema[key]

    counts = dict(sorted(Counter(row["recommendation"] for row in rows).items()))
    definitions["RatingSummary"] = {"Rows": len(rows), "Participants": len({r["participant_id"] for r in rows}),
                                   "Recommendations": {label: counts.get(label, 0)
                                                       for label in ("available", "caution", "unavailable")},
                                   "Methods": dict(Counter(r["recommendation_method"] for r in rows))}
    definitions["SourceTables"] = sources
    first = ("recording_id", "recommendation", "recommendation_method", "recommendation_reasons")
    rows = [{**{key: row[key] for key in first}, **row} for row in rows]
    output = Path(output)
    write_rows(output / "recording_quality.tsv.gz", rows)
    write_json(output / "recording_quality.json", definitions)
    return definitions["RatingSummary"]
