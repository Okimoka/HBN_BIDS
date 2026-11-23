"""Read SMI samples, name columns, and retain gaps on a regular time grid"""

import csv
import re

import numpy as np
import pandas as pd


# fallback column naming: "Peak Accel." -> "peak_accel"
def snake(text):
    return re.sub(r"[^a-z0-9]+", "_", text.lower()).strip("_")


# add one header field in place: "# Sample Rate: 500" adds {"Sample Rate": "500"}
def header_entry(line, header):
    key, separator, value = line.lstrip("# ").partition(":")
    if separator:
        header[key.strip()] = value.strip()


# separate header fields, SMP sample rows and MSG messages; return (header, frame, messages)
# original numeric strings are retained; blank cells become "n/a"
def read_samples(path):
    header, rows, messages = {}, [], []

    with open(path, encoding="utf-8-sig") as source:
        for line in source:
            if line.startswith("Time\tType\t"):
                columns = line.rstrip().split("\t")
                break
            header_entry(line, header)

        for row in csv.reader(source, delimiter="\t", quoting=csv.QUOTE_NONE):
            if not row:
                continue

            if row[1] == "MSG": #message
                messages.append((row[0], "\t".join(row[3:]).strip()))
            elif row[1] == "SMP": #sample
                if len(row) > len(columns) and not any(row[len(columns):]):
                    row = row[:len(columns)]
                if len(row) != len(columns):
                    raise ValueError(f"Sample width {len(row)} != header width {len(columns)}")
                rows.append(row)
            else:
                raise ValueError(f"Unknown sample row type: {row[1]}")

    if not rows:
        raise ValueError("No SMI samples found")

    frame = pd.DataFrame(rows, columns=columns).drop(columns="Type")
    # replaces all kinds of spellings for n/a with just n/a
    return header, frame.replace(r"(?i)^(?:\s*|n/a)$", "n/a", regex=True), messages


# names without a unit suffix; unlisted fields survive under a snake_case name
ALIASES = {
    'Time': 'timestamp', 'POR X': 'x_coordinate', 'POR Y': 'y_coordinate',
    'Mapped Diameter': 'pupil_size', 'Dia': 'pupil_diameter', 'Area': 'pupil_area',

    'Raw X': 'raw_pupil_x', 'Raw Y': 'raw_pupil_y', 'Raw Z': 'raw_pupil_z',
    'Dia X': 'pupil_diameter_x', 'Dia Y': 'pupil_diameter_y', 'Dia Z': 'pupil_diameter_z',
    'CR1 X': 'corneal_reflection_1_x', 'CR1 Y': 'corneal_reflection_1_y', 'CR1 Z': 'corneal_reflection_1_z',
    'CR2 X': 'corneal_reflection_2_x', 'CR2 Y': 'corneal_reflection_2_y', 'CR2 Z': 'corneal_reflection_2_z',
    'EPOS X': 'eye_position_x', 'EPOS Y': 'eye_position_y', 'EPOS Z': 'eye_position_z',
    'GVEC X': 'gaze_vector_x', 'GVEC Y': 'gaze_vector_y', 'GVEC Z': 'gaze_vector_z',
    'H POS X': 'head_position_x', 'H POS Y': 'head_position_y', 'H POS Z': 'head_position_z',
    'H ROT X': 'head_rotation_x', 'H ROT Y': 'head_rotation_y', 'H ROT Z': 'head_rotation_z'
}


# map one source column to its eye, BIDS name and metadata
# example: sample_column("L POR X [px]") returns:
#   ("L", "x_coordinate", {
#       "Description": "SMI export column: L POR X [px].",
#       "SourceColumn": "L POR X [px]",
#       "Units": "pixel"
#   })
def sample_column(source):
    eye = source[0] if source.startswith(("L ", "R ")) else None
    label = source[2:] if eye else source
    parts = re.fullmatch(r"(.*?)(?:\s*\[([^]]+)\])?", label)
    label, unit = parts[1].strip(), parts[2]
    name = ALIASES.get(label, snake(label))

    if unit is None:
        unit = {"Time": "us", "Latency": "us", "Mapped Diameter": "mm", "Area": "pixel^2"}.get(label)
        if label in ALIASES and unit is None:
            unit = ("pixel" if label.startswith(("POR ", "Raw ", "Dia", "CR")) else
                    "mm" if label.startswith(("EPOS ", "H POS ")) else
                    "deg" if label.startswith("H ROT ") else None)

    # use BIDS-style "pixel"; ASCII "deg" and "us" avoid Unicode-unit issues with MNE
    unit = {"px": "pixel", "°": "deg", "µs": "us"}.get(unit, unit)

    metadata = {"Description": f"SMI export column: {source}.", "SourceColumn": source}
    if name == "pupil_size":
        metadata["Description"] = f"Pupil diameter; SMI export column: {source}."
    if unit:
        metadata["Units"] = unit
    if name == "timestamp":
        metadata["Origin"] = "SMI system startup"

    return eye, name, metadata


# find sample positions on a regular grid, including gaps
# example input: Time=[1000000, 1002000, 1006000] us, nominal_rate=500 Hz
# returns:
#   indices = [0, 1, 3]
#   period = 0.002 s
#   report = {"InsertedSamples": 1, ...}
# split_eyes fills that missing slot with "n/a"
def regular_grid(frame, nominal_rate):
    """retain every sample; grid error is reported rather than used to discard data

    Keep existing grids within 10%, then try a small origin shift
    Otherwise round native timestamps directly and move collisions to the next
    free slot: [0, 1, 1, 4] becomes [0, 1, 2, 4], without losing either sample
    """
    timestamps = frame["Time"].to_numpy(dtype=np.int64)
    elapsed = (timestamps - timestamps[0]) / 1e6
    if not np.isfinite(nominal_rate) or nominal_rate <= 0 or np.any(np.diff(elapsed) <= 0):
        raise ValueError("Need a positive sample rate and strictly increasing timestamps")

    steps = np.rint(np.diff(elapsed) * nominal_rate).astype(np.int64)
    indices = np.r_[0, np.cumsum(steps)]
    # float positions prevent integer overflow in long recordings' squared indices
    positions = indices.astype(float)
    period = float(positions @ elapsed / (positions @ positions)) if indices[-1] else 1 / nominal_rate
    least_squares_period = period
    method = "least-squares period"
    residual = elapsed - indices * period
    maximum = float(np.max(np.abs(residual)))

    # least squares minimizes average error; another period can still meet the maximum-error bound
    if np.all(steps > 0):
        for tolerance in (0.05, 0.10):
            if maximum <= tolerance * period:
                break

            lower = np.max(elapsed[1:] / (indices[1:] + tolerance))
            upper = np.min(elapsed[1:] / (indices[1:] - tolerance))
            if lower <= upper:
                period = float((lower + upper) / 2)
                maximum = float(np.max(np.abs(elapsed - indices * period)))
                method = f"midpoint of feasible periods within {tolerance:.0%} tolerance"

            if maximum <= tolerance * period:
                break

    origin = 0.0
    collisions = shifted = backlog = 0
    consistent = bool(np.all(steps > 0) and np.array_equal(np.rint(np.diff(elapsed) / period), steps))
    method = f"Rounded nominal-rate intervals; {method} anchored at first sample"
    if maximum > .10 * period or not consistent:
        period = least_squares_period
        consistent = bool(np.all(steps > 0) and np.array_equal(np.rint(np.diff(elapsed) / period), steps))
        residual = elapsed - indices * period
        # choose the smallest origin shift that places every sample inside the 10% bound
        margin = 4 * np.finfo(float).eps * max(1, float(elapsed[-1]))
        lower, upper = float(residual.max() - .1 * period + margin), float(residual.min() + .1 * period - margin)
        if consistent and lower <= upper:
            origin = float(np.clip(0, lower, upper))
            method = "Rounded nominal-rate intervals; least-squares period with minimal origin shift within 10%"
        else:
            nearest = np.rint(elapsed / period).astype(np.int64)
            sequence = np.arange(len(nearest))
            indices = np.maximum.accumulate(nearest - sequence) + sequence
            collisions = int(np.sum(np.diff(nearest) == 0))
            shifted = int(np.sum(indices != nearest))
            backlog = int(np.max(indices - nearest))
            method = "Rounded native timestamps; collisions assigned to the next free slot"

    residual = elapsed - (origin + indices * period)
    maximum = float(np.max(np.abs(residual)))

    count = int(indices[-1] + 1)
    report = {
        "NominalSamplingFrequency": nominal_rate, "DeviceSamplingFrequency": 1 / period,
        "FirstTimestamp": int(timestamps[0]), "SourceSamples": len(frame),
        "OutputSamples": count, "InsertedSamples": count - len(frame),
        "MaximumGridResidualSeconds": maximum,
        "RMSGridResidualSeconds": float(np.sqrt(np.mean(residual ** 2))),
        "GridPass5Percent": maximum <= .05 * period, "GridPass10Percent": maximum <= .10 * period,
        "GridOriginOffsetSeconds": origin, "GridMethod": method,
        "GridCollisionPairs": collisions, "GridShiftedSamples": shifted, "GridMaximumExtraSlots": backlog,
    }
    return indices, period, report


# mask complete all-zero measurement groups in one eye, returning counts by group
# e.g. GVEC (0, 0, 0) becomes (n/a, n/a, n/a), while (0, 0, 1) stays unchanged
def mask_zero_groups(data):
    groups = {"gaze": ["x_coordinate", "y_coordinate"]}
    for prefix, axes in [("raw_pupil", "xy"), ("corneal_reflection_1", "xy"),
                         ("corneal_reflection_2", "xy"), ("eye_position", "xyz"),
                         ("gaze_vector", "xyz")]:
        columns = [f"{prefix}_{axis}" for axis in axes]
        if axes == "xy" and f"{prefix}_z" in data:
            columns.append(f"{prefix}_z")
        groups[prefix] = columns

    diameter_axes = [f"pupil_diameter_{axis}" for axis in "xyz" if f"pupil_diameter_{axis}" in data]
    if not diameter_axes or {"pupil_diameter_x", "pupil_diameter_y"}.issubset(diameter_axes):
        groups["pupil_diameter"] = [c for c in ("pupil_size", "pupil_diameter") if c in data] + diameter_axes

    counts = {}
    for group, columns in groups.items():
        if not columns or not set(columns).issubset(data.columns):
            continue

        missing = data[columns].replace("n/a", np.nan).astype(float).eq(0).all(axis=1)
        data.loc[missing, columns] = "n/a"
        counts[group] = int(missing.sum())

    return counts


# return {"eye1": (table, metadata, masked-group counts), "eye2": ...}, duplicating shared columns
# each eye/group is masked independently; indices [0, 2] insert a wholly n/a row at 1
#
# Example:
#
# frame = pd.DataFrame({
#   "Time": ["1000000", "1004000"],
#   "L POR X [px]": ["0", "10"], "L POR Y [px]": ["0", "20"],
#   "R POR X [px]": ["50", "0"], "R POR Y [px]": ["60", "0"],
# })
#
# Returns
#
# {"eye1": (
#        timestamp  x_coordinate  y_coordinate
#    1   1000000    n/a           n/a
#    2   n/a        n/a           n/a
#    3   1004000    10            20,
#
#    {"..."}, // metadata dict
#    {"gaze": 1} // 1 gaze sample was masked
# ),
# "eye2": (...)
# }
#
def split_eyes(frame, indices):
    fields = [(source, *sample_column(source)) for source in frame.columns]
    output = {}

    # HBN can export both L/R column sets even when System ID declares a single eye
    # retain both sets; SourceSampleHeader preserves the mode, and two output files
    # do not by themselves establish successful acquisition of both eyes
    for eye, label in [("L", "eye1"), ("R", "eye2")]:
        if not any(field[1] == eye for field in fields):
            continue

        selected = [(source, name, meta) for source, owner, name, meta in fields if owner in (None, eye)]
        names = [name for _, name, _ in selected]
        if len(set(names)) != len(names):
            raise ValueError(f"Columns collide after renaming for eye {eye}: {names}")

        data = frame[[source for source, _, _ in selected]].copy()
        data.columns = names
        first = ["timestamp", "x_coordinate", "y_coordinate"]
        if "pupil_size" in names:
            first.append("pupil_size")
        data = data[first + [name for name in names if name not in first]]

        zero_counts = mask_zero_groups(data)
        data.index = indices
        data = data.reindex(range(int(indices[-1]) + 1), fill_value="n/a")

        metadata = {name: meta for _, name, meta in selected}
        metadata.update(Columns=list(data.columns), RecordedEye="left" if eye == "L" else "right")
        output[label] = (data, metadata, zero_counts)

    if not output:
        raise ValueError("No L/R eye columns found")

    return output
