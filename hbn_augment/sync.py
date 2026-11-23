"""Estimate EEG = offset + scale * native ET elapsed time from shared messages.

These are the thesis's synchronization codes. The Gaussian HEOG/gaze fit was a
subsequent quality diagnostic, not the alignment method. No signal is changed
"""

import csv
from pathlib import Path
import re

import numpy as np
from numpy.polynomial import Polynomial

from hbn_repair.io import sha256


SYNC_CODES = {str(code) for code in (4, 8, 9, *range(11, 19), *range(20, 29), 30,
                                   *range(81, 85), *range(101, 105))}


# shared events determine offset, clock scale and fit evidence
# for anchors at ET elapsed [0, 10] s and EEG onsets [2, 12] s, the result includes:
# {
#     "start_time": 2.0,
#     "clock_scale": 1.0,
#     ...
# }
def estimate_sync(eeg_events_path: str | Path, smi_events_path: str | Path,
                  first_timestamp_us: int, *, max_residual_s: float = 0.020,
                  max_clock_deviation: float = 0.01) -> dict:
    """Return smi2bids timing arguments and the actual evidence for the fit.

    EEG onsets are already EEG-relative seconds. ET elapsed time is measured
    from the first observed sample, not the first message. Edge trimming cannot
    delete interior mismatches or disambiguate repeated candidate sequences.

    The 20 ms maximum residual and 1% clock-scale deviation are configurable
    conversion guards, not validated HBN quality criteria. Two anchors determine
    a line but provide no independent check; this is reported explicitly
    """
    first_timestamp_us = int(first_timestamp_us)
    eeg, et = _read_anchors(eeg_events_path, smi_events_path)
    counts = len(eeg), len(et)
    counter_format = False
    try:
        eeg, et, trimmed = _match_edges(eeg, et)
    except ValueError:
        run = re.search(r"_task-contrastChangeDetection_run-([123])_", Path(eeg_events_path).name)
        if not run:
            raise
        eeg, et, trimmed = _match_contrast_counter(eeg_events_path, smi_events_path, int(run[1]))
        counts = len(eeg) + sum(trimmed[:2]), len(et) + sum(trimmed[2:])
        counter_format = True

    x = np.asarray([(row[1] - first_timestamp_us) / 1e6 for row in et])
    y = np.asarray([row[1] for row in eeg])
    # EEG timestamps are quantized to samples, so separate events may share a time
    if (not np.isfinite(x).all() or not np.isfinite(y).all()
            or np.any(np.diff(x) <= 0) or np.any(np.diff(y) < 0)):
        raise ValueError("Sync anchors must be finite, with strictly increasing ET and nondecreasing EEG timestamps")
    # same core fit as mne.preprocessing.realign_raw: identical anchors/time origins give the same coefficients
    offset, scale = Polynomial.fit(x, y, deg=1).convert(domain=(-1, 1)).coef
    residual = y - (offset + scale * x)
    maximum = float(np.abs(residual).max())
    if not np.isfinite(scale) or scale <= 0 or abs(scale - 1) > max_clock_deviation:
        raise ValueError(f"Sync clock scale {scale:.9f} exceeds allowed deviation {max_clock_deviation:g}")
    if maximum > max_residual_s:
        raise ValueError(f"Sync maximum residual {maximum:.6f} s exceeds {max_residual_s:g} s")
    warnings = []
    if counter_format:
        warnings.append("contrast_response_counters_decoded")
    if len(x) == 2:
        warnings.append("two_anchors_no_independent_fit_check")
    if maximum > 0.020:
        warnings.append("marker_residual_over_20ms")
    if any(trimmed):
        warnings.append("unambiguous_edge_events_trimmed")
    return {
        "start_time": offset, "clock_scale": scale, "method": "shared_events_affine",
        "n_anchors": len(x), "eeg_anchor_count": counts[0], "et_anchor_count": counts[1],
        "trimmed_eeg_start": trimmed[0], "trimmed_eeg_end": trimmed[1],
        "trimmed_et_start": trimmed[2], "trimmed_et_end": trimmed[3],
        "anchor_span_et_seconds": float(np.ptp(x)), "anchor_span_eeg_seconds": float(np.ptp(y)),
        "drift_ppm": (scale - 1) * 1e6, "residual_degrees_of_freedom": len(x) - 2,
        "residual_rmse_seconds": float(np.sqrt(np.mean(residual ** 2))),
        "max_residual_seconds": maximum, "max_residual_limit_seconds": max_residual_s,
        "max_clock_deviation": max_clock_deviation, "warnings": warnings,
        "first_timestamp_us": first_timestamp_us,
        "eeg_events_sha256": sha256(Path(eeg_events_path)),
        "smi_events_sha256": sha256(Path(smi_events_path)),
        "anchors": [
            {"event_code": ee[0], "eeg_row": ee[2], "smi_line": tt[2] + 1,
             "eeg_onset_seconds": ee[1], "et_timestamp_us": tt[1],
             "et_elapsed_seconds": float(xx), "residual_seconds": float(rr),
             **({"et_event_code": tt[0]} if counter_format else {})}
            for ee, tt, xx, rr in zip(eeg, et, x, residual)
        ],
    }


# two event files -> ordered (code, time, source-row) lists, using seconds for EEG and µs for ET
def _read_anchors(eeg_events_path, smi_events_path, codes=SYNC_CODES):
    # tuples: (code, EEG seconds / ET microseconds, original zero-based row)
    eeg, et = [], []
    with open(eeg_events_path, encoding="utf-8-sig") as source:
        for index, row in enumerate(csv.DictReader(source, delimiter="\t")):
            code = row["event_code"].strip()
            if code.isdigit() and (codes is None or code in codes):
                eeg.append((code, float(row["onset"]), index))
    with open(smi_events_path, encoding="utf-8-sig") as source:
        for index, row in enumerate(csv.reader(source, delimiter="\t", quoting=csv.QUOTE_NONE)):
            if row and row[0] == "UserEvent":
                match = re.fullmatch(r"# Message: (\d+)", row[4].strip())
                if match and (codes is None or match[1] in codes):
                    et.append((match[1], int(row[3]), index))
    return eeg, et


# some contrast exports encode buttons as response indices: EEG [96,5,8,12,5,9,13]
# matches ET [96,5,8,2,5,9,3]. Full positional equality disambiguates counter 8/9
# from target 8/9; counter 1 initiated the block and is represented by its start marker
def _match_contrast_counter(eeg_path, et_path, run):
    eeg, et = _read_anchors(eeg_path, et_path, codes=None)
    et_end = len(et) - 1 if et and et[-1][0] == "9999" else len(et)
    marker = str(93 + run)
    boundaries = {str(code) for code in (81, 82, 83, 84, *range(90, 98), 9999)}
    matches = []
    for i, row in enumerate(eeg):
        if row[0] != marker:
            continue
        end = next((k for k in range(i + 1, len(eeg)) if eeg[k][0] in boundaries), len(eeg))
        segment = eeg[i:end]
        for j, message in enumerate(et):
            if message[0] != marker or len(segment) != et_end - j:
                continue
            counter = 1
            for ee, tt in zip(segment, et[j:et_end]):
                if ee[0] in ("12", "13"):
                    counter += 1
                    expected = str(counter)
                else:
                    expected = ee[0]
                if tt[0] != expected:
                    break
            else:
                if counter > 1:
                    matches.append((segment, et[j:et_end], (i, len(eeg) - end, j, len(et) - et_end)))

    if len(matches) != 1:
        raise ValueError("Contrast response counters do not have a unique complete ordered match; no alignment inferred")
    return matches[0]


# example code sequences [81,101] and [82,81,101] -> [81,101] in both, with one ET start trimmed
def _match_edges(eeg, et):
    """Only trim edges when the complete shorter code sequence has one match"""
    eeg_codes, et_codes = [row[0] for row in eeg], [row[0] for row in et]
    longer, shorter = (eeg_codes, et_codes) if len(eeg) >= len(et) else (et_codes, eeg_codes)
    if len(shorter) < 2:
        raise ValueError("Synchronization needs at least two real shared anchors")
    matches = [index for index in range(len(longer) - len(shorter) + 1)
               if longer[index:index + len(shorter)] == shorter]
    if len(matches) != 1:
        raise ValueError("Sync codes do not have a unique complete ordered match; no alignment inferred")
    start, end = matches[0], matches[0] + len(shorter)
    if len(eeg) >= len(et):
        return eeg[start:end], et, (start, len(eeg) - end, 0, 0)
    return eeg, et[start:end], (0, 0, start, len(et) - end)


# samples file -> first SMP timestamp in microseconds, e.g. "1000000\tSMP\t..." -> 1000000
def first_timestamp(path):
    with path.open(encoding="utf-8-sig") as source:
        for line in source:
            cells = line.split("\t", 2)
            if len(cells) > 1 and cells[1] == "SMP":
                return int(cells[0])
    raise ValueError(f"No SMI samples in {path}")
