"""A10/A01/A13/A14: inspect task context and repair supported labels without moving events"""

import hashlib
from io import BytesIO

import numpy as np
from scipy.io import loadmat, savemat
from scipy.io.matlab import varmats_from_mat

from .io import sha256


STARTS = {str(code): "movie" for code in range(81, 85)} | {
    "90": "rest", "91": "sequence", "92": "symbol", "93": "surround", "97": "surround",
    "94": "contrast", "95": "contrast", "96": "contrast",
}
LABELS = {
    "rest": {"20": "instructed_toOpenEyes", "30": "instructed_toCloseEyes"},
    "symbol": {"20": "newPage", "14": "trialResponse"},
    "surround": {"4": "fixpoint_ON", "8": "stim_ON"},
    "contrast": {"5": "contrastTrial_start", "8": "left_target", "9": "right_target",
                 "12": "left_buttonPress", "13": "right_buttonPress"},
    "sequence": {str(i): f"dot_no{i-10}_ON" for i in range(11, 19)} |
                {str(i): f"dot_no{i-20}_OFF" for i in range(21, 29)},
}
MOVIES = {"DespicableMe": "83", "DiaryOfAWimpyKid": "81", "FunwithFractals": "82", "ThePresent": "84"}


# A01: event rows + corresponding .set header -> corrected rows and cell changes
def repair_labels(rows, header):
    rows = [dict(row) for row in rows]
    embedded = header["events"]
    if len(rows) != len(embedded):
        raise ValueError("A01: TSV and .set have different event counts")

    changes = []
    for index, (row, event) in enumerate(zip(rows, embedded)):
        if (row["event_code"] != str(event["event_code"]).strip() or
                abs(float(row["sample"]) - (float(event["latency"]) - 1)) > 1e-6):
            raise ValueError(f"A01: TSV/.set event identity differs at line {index + 2}")

        if row["value"] != str(event["type"]):
            # the audited first-row export defect has a valid .set label; other disagreements need review
            if index != 0 or row["value"] not in ("n/a", "") and "/" not in row["value"]:
                raise ValueError(f"A01: unrecognized TSV/.set label disagreement at line {index + 2}")

            changes.append({"line": index + 2, "before": row["value"], "after": str(event["type"]), "reason": "first_row_export"})
            row["value"] = str(event["type"])

    state = None
    for index, row in enumerate(rows):
        code = row["event_code"]
        if code in STARTS:
            state = STARTS[code]
        elif code in ("break cnt", "boundary", "50"):
            state = None

        expected = LABELS.get(state, {}).get(code)
        if expected and row["value"] != expected:
            changes.append({"line": index + 2, "before": row["value"], "after": expected, "reason": "explicit_task_context"})
            row["value"] = expected

    return rows, changes


# read small .set variables without loading EEG samples; HBN exports are top-level MATLAB variables
def read_header(path):
    values = loadmat(path, variable_names=["nbchan", "pnts", "srate", "trials", "chanlocs", "event"], simplify_cells=True)
    events = values["event"]
    if isinstance(events, dict):
        events = [events]

    channels = values["chanlocs"]
    if isinstance(channels, dict):
        channels = [channels]

    return {key: values[key] for key in ("nbchan", "pnts", "srate", "trials")} | {
        "events": list(events), "channel_names": [channel["labels"] for channel in channels]}


# A01: replace only the event variable; preserve signal bytes, urevent and opaque MATLAB objects verbatim
def write_set(source, destination, labels):
    data = loadmat(source, variable_names=["event"])["event"]
    events = data.reshape(-1)
    for event, label in zip(events, labels, strict=True):
        event["type"] = np.array([label])

    replacement = BytesIO()
    savemat(replacement, {"event": data}, long_field_names=True)

    with source.open("rb") as stream:
        variables = varmats_from_mat(stream)
    assert sum(name == "event" for name, _ in variables) == 1
    header = bytes(variables[0][1].getbuffer()[:128])
    source_digest = hashlib.sha256(header)
    if header[-2:] != replacement.getbuffer()[126:128]:
        raise ValueError("A01: source and replacement MAT byte orders differ")

    # MATLAB class storage has an absolute file offset, which moves when the event variable changes size
    offset = int.from_bytes(header[116:124], "little")
    if offset:
        position = 128
        for name, content in variables:
            size = len(content.getbuffer()) - 128
            if name == "event" and position < offset:
                offset += len(replacement.getbuffer()) - 128 - size
                break
            position += size
        header = header[:116] + offset.to_bytes(8, "little") + header[124:]

    # SciPy's raw-variable splitter retains MATLAB class storage that loadmat/savemat cannot round-trip
    temporary = destination.with_suffix(".set.part")
    digest = hashlib.sha256(header)
    with temporary.open("wb") as stream:
        stream.write(header)
        for name, content in variables:
            source_digest.update(content.getbuffer()[128:])
            block = (replacement if name == "event" else content).getbuffer()[128:]
            stream.write(block)
            digest.update(block)

    if sha256(temporary) != digest.hexdigest() or not mat_equal(data, loadmat(temporary, variable_names=["event"])["event"]):
        raise ValueError(f"A01: .set read-back differs from intended content: {temporary}")

    # replacing the directory entry cannot write through a source symlink
    temporary.replace(destination)
    return {"before": source_digest.hexdigest(), "after": digest.hexdigest()}


# compare nested MATLAB event fields without losing array shapes or numeric precision
def mat_equal(left, right):
    left, right = np.asarray(left), np.asarray(right)
    if left.shape != right.shape or left.dtype != right.dtype:
        return False

    if left.dtype.names:
        return all(mat_equal(left[name], right[name]) for name in left.dtype.names)

    if left.dtype == object:
        return all(mat_equal(a, b) for a, b in zip(left.flat, right.flat))

    return np.array_equal(left, right, equal_nan=True) if left.dtype.kind in "fc" else np.array_equal(left, right)


# contrast without run entity + unique marker 95 -> logical task contrastChangeDetection, run 2
def task_run(entity, rows):
    task, run = entity["task"], entity.get("run", "n/a")
    if run == "n/a":
        markers = {"contrastChangeDetection": {"94": "1", "95": "2", "96": "3"},
                   "surroundSupp": {"93": "1", "97": "2"}}.get(task, {})
        found = {markers[row["event_code"]] for row in rows if row["event_code"] in markers}
        if len(found) == 1:
            run = found.pop()

    return task, run


# A10/A13/A14: flags are review evidence, not instructions to crop or reject an entire recording
def review_events(rows, header, task):
    codes = [row["event_code"] for row in rows]
    partial = any(
        row["duration"] not in ("", "n/a") and
        float(row["onset"]) + float(row["duration"]) > (header["pnts"] + .5) / header["srate"]
        for row in rows
    )
    movie = task in MOVIES and any(codes.count(code) != 1 for code in (MOVIES[task], str(int(MOVIES[task]) + 20)))

    return {
        "task_start_codes": ";".join(sorted(set(codes) & STARTS.keys(), key=int)) or "n/a",
        "mixed_task_starts": int(len(set(codes) & STARTS.keys()) > 1),
        "internal_boundary": int(any(row["event_code"] in ("break cnt", "boundary") and
                                     0 < float(row["sample"]) < header["pnts"] - 1 for row in rows)),
        "movie_anchor_count": int(movie), "event_ends_after_recording": int(partial),
    }
