"""B01–B03: add verified behavioral settings, planned waits and movie provenance"""

from collections import defaultdict
from functools import lru_cache
import json
from pathlib import Path
import re

import numpy as np
from numpy.polynomial import Polynomial
from scipy.io import loadmat
from scipy.io.matlab import MatReadError

from hbn_repair.inventory import MOVIES, TASKS, entities, inheritance
from hbn_repair.io import read_table, sha256, write_json, write_rows


FLAGS = {"recordEEG": "SourceEEGRecordingFlag", "useEL": "SourceEyeTrackingFlag",
         "useEL_Calib": "SourceEyeCalibrationFlag"}
SETTINGS = {
    "contrastChangeDetection": {"FlickF": "FlickerFrequencyHz", "numtargets": "PlannedTargetCount"},
    "surroundSupp": {"FlickF": "FlickerFrequencyHz", "trialdur": "PlannedStimulusDurationSeconds"},
    "seqLearning6target": {"numtargets": "PlannedTargetCount", "numrepet": "PlannedRepetitionCount"},
    "seqLearning8target": {"numtargets": "PlannedTargetCount", "numrepet": "PlannedRepetitionCount"},
    "symbolSearch": {"nrpages": "PlannedPageCount"},
}
CLIPS = {"Diary_of_a_Wimpy_Kid_Trailer.mp4": "DiaryOfAWimpyKid",
         "Fun_Fractals_v2.m4v": "FunwithFractals",
         "Fun_Fractals_v2.mp4": "FunwithFractals",
         "Three_Little_Kittens_Despicable_Me.mp4": "DespicableMe", "The_Present.mp4": "ThePresent"}
SOURCE_TASK = re.compile(r"(SAIIT_2AFC_Block[123]|SurroundSupp_Block[12]|WISC_ProcSpeed|vis_learn|Video_?[1-4]|movie_order)$")
LEVELS = {
    "added": "Verified addition written", "not_applicable": "Addition does not apply to this recording",
    "missing_source": "No matching MATLAB behavioral export", "ambiguous_source": "Differing source candidates",
    "identity_conflict": "Source identity cannot be reconciled with the participant",
    "invalid_source": "MATLAB export could not be decoded", "unsupported_visit": "Session or repeated run needs review",
    "no_fields": "No selected parameters present", "invalid_parameters": "Selected parameters have an unsupported value or shape",
    "target_mismatch": "Target directions/counts or block boundaries do not establish correspondence",
    "timing_mismatch": "Matched target clocks exceed 20 ms maximum affine-fit residual",
    "missing_order": "No unique matching movie-order export", "movie_conflict": "Movie identity, order or visit fields disagree",
    "metadata_conflict": "Existing metadata or column would be changed",
}
BEHAVIOR_COLUMNS = {
    **{f"beh_b0{number}_status": {"Description": description, "Levels": LEVELS} for number, description in (
        (1, "B01: selected source task settings and acquisition flags"),
        (2, "B02: planned waits before contrast targets"), (3, "B03: movie presentation index and source clip"))},
    "beh_sources": {"Description": "Semicolon-separated matched MATLAB paths relative to the input collection"},
    "beh_planned_iti_count": {"Description": "Number of EEG target rows receiving a verified planned_iti value"},
    "beh_b02_max_residual_ms": {"Description": "Maximum source/EEG target-time residual after an affine fit for B02", "Units": "ms"},
}


# B01–B03: one recording -> added JSON fields/TSV column and machine-readable outcomes
def augment_behavior(recording, output, index):
    entity = entities(recording.prefix)
    task, run = entity["task"], entity.get("run")
    result = {"beh_b01_status": "missing_source", "beh_b02_status": "not_applicable",
              "beh_b03_status": "not_applicable", "beh_sources": "n/a", "beh_planned_iti_count": 0,
              "beh_b02_max_residual_ms": "n/a"}
    relevant = ["beh_b01_status"]
    if task == "contrastChangeDetection":
        relevant.append("beh_b02_status")
    if task in MOVIES.values():
        relevant.append("beh_b03_status")
    if task == "RestingState":
        result["beh_b01_status"] = "not_applicable"
        return result

    if "ses" in entity or (task not in ("contrastChangeDetection", "surroundSupp") and run not in (None, "1")):
        result.update(dict.fromkeys(relevant, "unsupported_visit"))
        return result

    sources = []
    for path in index["subjects"].get(recording.subject, []):
        source = read_source(path, recording.subject)
        if source["target"] == (task, run if task in ("contrastChangeDetection", "surroundSupp") else None):
            sources.append(source)
    source, status = unique_source(sources)
    if status:
        result.update(dict.fromkeys(relevant, status))
        return result

    relative = recording.eeg.relative_to(recording.release_root)
    eeg = Path(output) / relative
    sidecar = eeg.with_suffix(".json")
    metadata = json.loads(sidecar.read_text()) if sidecar.exists() else {}
    effective = inheritance(eeg, "eeg", Path(output))
    additions, sources_used = {}, []
    parameters, status = task_parameters(source["data"].get("par", {}), task)
    if status == "added" and effective.get("HBNTaskParameters", parameters) != parameters:
        status = "metadata_conflict"
    if status == "added":
        additions["HBNTaskParameters"] = parameters
        sources_used.append(source)
    result["beh_b01_status"] = status

    # B02 adds one column; the task events and ET display metadata retain their existing values
    if task == "contrastChangeDetection":
        status, count, residual = add_planned_intervals(eeg, source["data"], run, Path(output))
        result.update(beh_b02_status=status, beh_planned_iti_count=count, beh_b02_max_residual_ms=residual)
        if status == "added":
            sources_used.append(source)

    if task in MOVIES.values():
        orders = [read_source(path, recording.subject) for path in index["subjects"].get(recording.subject, [])
                  if path.stem.endswith("movie_order")]
        order, order_status = unique_source(orders)
        movie, status = movie_metadata(source, order, task, eeg) if not order_status else ({}, "missing_order")
        if status == "added" and any(key in effective and effective[key] != value for key, value in movie.items()):
            status = "metadata_conflict"
        if status == "added":
            additions.update(movie)
            sources_used.extend((source, order))
        result["beh_b03_status"] = status

    used = {item["path"]: item for item in sources_used}
    result["beh_sources"] = str(source["path"].relative_to(index["root"]))
    if used:
        provenance = [{"File": str(path.relative_to(index["root"])), "SHA256": sha256(path)} for path in sorted(used)]
        metadata.update(additions, HBNBehavioralSources=provenance)
        write_json(sidecar, metadata)
        result["beh_sources"] = ";".join(item["File"] for item in provenance)
    return result


# HBN_REPAIRED + subject IDs -> MAT paths; legacy ET/subject/Behavioral is also recognized
def index_behavior(root, subjects):
    root = Path(root)
    paths = defaultdict(list)
    for participant in subjects:
        subject = participant.removeprefix("sub-")
        seen = set()
        for directory in (root / "BEH" / subject, root / "BEH" / f"sub-{subject}",
                          root / "ET" / subject / "Behavioral", root / "ET" / f"sub-{subject}" / "Behavioral"):
            for path in sorted(directory.rglob("*.mat")):
                if SOURCE_TASK.search(path.stem) and path.resolve() not in seen:
                    paths[subject].append(path)
                    seen.add(path.resolve())
    return {"root": root, "subjects": paths}


# one MAT -> decoded data, task identity and participant check; cache nearby repeated task lookups
@lru_cache(maxsize=256)
def read_source(path, subject):
    match = SOURCE_TASK.search(path.stem)
    name = match[1].replace("Video_", "Video")
    target = TASKS.get(name.replace("SurroundSupp", "SurrSupp"))
    result = {"path": path, "name": name, "target": target, "status": "", "data": {}}
    try:
        data = loadmat(path, simplify_cells=True)
    except (ValueError, MatReadError, NotImplementedError):
        return result | {"status": "invalid_source"}

    result["data"] = data
    par = data.get("par", {})
    declared = str(par.get("runID", "")).strip()
    if declared in ("NA", "n/a"):
        declared = ""
    filename_matches = bool(re.fullmatch(re.escape(subject) + r"[_-]*", path.stem[:match.start()]))
    internal_matches = declared == subject or bool(re.fullmatch(re.escape(subject) + r"[_-]\d+[a-z]?", declared))
    local_id = bool(re.fullmatch(r"\d+(?:[_-][A-Za-z0-9]+)?", declared))
    if not ((filename_matches and (not declared or internal_matches or local_id)) or declared == subject):
        result["status"] = "identity_conflict"

    if name == "vis_learn" and par.get("numtargets") in (6, 8):
        result["target"] = (f"seqLearning{int(par['numtargets'])}target", None)
    if name.startswith("Video"):
        movie = MOVIES.get((par.get("CD_START"), par.get("CD_END")))
        result["target"] = (movie, None) if movie else None
    return result


# byte-identical duplicates are harmless; differing candidates or conflicting IDs stay unresolved
def unique_source(sources):
    if not sources:
        return None, "missing_source"
    if len(sources) > 1:
        sources = list({sha256(source["path"]): source for source in sources}.values())
    if len(sources) != 1:
        return None, "ambiguous_source"
    return sources[0], sources[0]["status"]


# B01: explicit task whitelist avoids treating leftover movie parameters as active task settings
def task_parameters(par, task):
    parameters = {}
    for field, name in (FLAGS | SETTINGS.get(task, {})).items():
        if field not in par:
            continue
        value = np.asarray(par[field], dtype=float)
        if not value.size or value.ndim > 1 or not np.isfinite(value).all():
            return {}, "invalid_parameters"
        if field in FLAGS:
            if value.size != 1 or value.item() not in (0, 1):
                return {}, "invalid_parameters"
        elif np.any(value <= 0) or (field != "FlickF" and value.size != 1):
            return {}, "invalid_parameters"
        if field in ("numtargets", "numrepet", "nrpages") and np.any(value != np.floor(value)):
            return {}, "invalid_parameters"
        parameters[name] = value.item() if value.size == 1 else value.tolist()
    return parameters, "added" if parameters else "no_fields"


# B02: one unique contrast block with identical target directions/counts -> planned waits on its target rows
def add_planned_intervals(eeg, data, run, root):
    path = eeg.with_name(eeg.name.removesuffix("_eeg.set") + "_events.tsv")
    rows = read_table(path)
    intervals = np.asarray(data.get("trialITI", []), dtype=float).reshape(-1)
    sides = np.asarray(data.get("trialLR", []), dtype=float).reshape(-1)
    codes = [row["event_code"] for row in rows]
    starts = [i for i, code in enumerate(codes) if code == str(93 + int(run))]
    if len(starts) != 1 or not len(intervals) or not np.isfinite(intervals).all() or np.any(intervals < 0):
        return "target_mismatch", 0, "n/a"
    start = starts[0]
    boundaries = {str(code) for code in (*range(81, 85), *range(90, 98), 9999)}
    stop = next((i for i in range(start + 1, len(rows)) if codes[i] in boundaries), len(rows))
    targets = [i for i in range(start, stop) if codes[i] in ("8", "9")]
    if len(targets) != len(intervals) or not np.array_equal(sides, [int(codes[i]) - 7 for i in targets]):
        return "target_mismatch", 0, "n/a"

    # identical directions/counts alone can hide mismatched visits or interrupted blocks
    times = np.asarray(data.get("TargOnT", []), dtype=float).reshape(-1)
    if len(times) != len(targets) or len(times) < 3 or not np.isfinite(times).all() or np.any(np.diff(times) <= 0):
        return "target_mismatch", 0, "n/a"
    onsets = np.asarray([float(rows[i]["onset"]) for i in targets])
    if not np.isfinite(onsets).all() or np.any(np.diff(onsets) <= 0):
        return "target_mismatch", 0, "n/a"
    fit = Polynomial.fit(times - times[0], onsets, 1)
    residual = float(np.max(np.abs(onsets - fit(times - times[0]))) * 1000)
    if residual > 20:
        return "timing_mismatch", 0, residual

    definition = {"Description": "Planned waiting interval before this contrast target, from S3 trialITI; not measured reaction time or target duration.", "Units": "s"}
    inherited = inheritance(eeg, "events", root)
    if "planned_iti" in rows[0] or inherited.get("planned_iti", definition) != definition:
        return "metadata_conflict", 0, residual
    for row in rows:
        row["planned_iti"] = "n/a"
    for position, value in zip(targets, intervals):
        rows[position]["planned_iti"] = float(value)
    metadata_path = path.with_suffix(".json")
    metadata = json.loads(metadata_path.read_text()) if metadata_path.exists() else {}
    write_json(metadata_path, metadata | {"planned_iti": definition})
    write_rows(path, rows)
    return "added", len(targets), residual


# B03: a verified cumulative clip history determines presentation order; VideoN alone does not
def movie_metadata(source, order, task, eeg):
    data, ordered = source["data"], order["data"]
    clips = [Path(str(value).strip().replace("\\", "/")).name for value in np.atleast_1d(data.get("movie_presentation_order", []))]
    full = [Path(str(value).strip().replace("\\", "/")).name for value in np.atleast_1d(ordered.get("movie_presentation_order", []))]
    ordinal = len(clips)
    source_par, order_par = data.get("par", {}), ordered.get("par", {})
    same_visit = all(key in source_par and key in order_par and source_par[key] == order_par[key]
                     for key in ("runID", "ExaminationDate"))
    if (not same_visit or not ordinal or len(full) < ordinal or clips != full[:ordinal]
            or CLIPS.get(clips[-1]) != task or np.asarray(data.get("exclude", [])).size
            or np.asarray(ordered.get("exclude", [])).size):
        return {}, "movie_conflict"

    codes = next(pair for pair, name in MOVIES.items() if name == task)
    for export in (data, ordered):
        order_ids = np.asarray(export.get("block_perm", [])).reshape(-1)
        if len(order_ids) < ordinal or order_ids[ordinal - 1] != codes[0] - 80:
            return {}, "movie_conflict"
    events = read_table(eeg.with_name(eeg.name.removesuffix("_eeg.set") + "_events.tsv"))
    movie_codes = [row["event_code"] for row in events if row["event_code"] in {str(c) for pair in MOVIES for c in pair}]
    if movie_codes != [str(code) for code in codes]:
        return {}, "movie_conflict"
    return {"HBNMoviePresentationIndex": ordinal, "HBNSourceClipFile": clips[-1]}, "added"
