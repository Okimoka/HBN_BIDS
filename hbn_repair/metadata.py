"""A02–A08: small metadata corrections; no inferred acquisition hardware or signal quality"""

from collections import Counter
from copy import deepcopy
import json
import re

from .events import STARTS

EGI_CHANNELS = {f"E{index}" for index in range(1, 129)} | {"Cz"}


# A02/A03/A04/A06: shared dictionaries stay shared; only changed definitions are returned
def repair_dictionary(source, definitions, task=None):
    result = deepcopy(source)
    issues = set()
    expected = {"surroundSupp": ("background", "foreground_contrast", "stimulus_cond"),
                "symbolSearch": ("user_answer", "correct_answer"), "contrastChangeDetection": ("feedback",)}
    for column in expected.get(task, ()):
        if column not in result:
            result[column] = deepcopy(definitions[column])
            issues.add("A03")

    for definition in result.values():
        if isinstance(definition, dict) and definition.get("Units") == "seconds":
            definition["Units"] = "s"
            issues.add("A04")

    foreground = result.get("foreground_contrast", {})
    for wrong, right in (("0.33", "0.3"), ("0.66", "0.6")):
        levels = foreground.get("Levels", {})
        if wrong in levels:
            del levels[wrong]
            levels[right] = f"Encoded foreground contrast {right}"
            issues.add("A02")

        hed = foreground.get("HED", {})
        if right in hed and f"Fraction/{wrong}" in hed[right]:
            hed[right] = hed[right].replace(f"Fraction/{wrong}", f"Fraction/{right}")
            issues.add("A02")

    # A06: target rows reference feedback that is only populated on response rows
    delayed = ", (Delay/2400 ms, ({feedback}), Duration/400 ms)"
    for key in ("left_target", "right_target"):
        hed = result.get("value", {}).get("HED", {})
        if delayed in hed.get(key, ""):
            hed[key] = hed[key].replace(delayed, "")
            issues.add("A06")

    if "feedback" in result and "HED" in result["feedback"]:
        del result["feedback"]["HED"]
        issues.add("A06")

    # A06: dot_no7_ON -> Def/dot-no-7, provided that position has an existing definition
    positions = set(re.findall(r"Definition/(dot-no-\d+)", json.dumps(result)))
    for definition in result.values():
        hed = definition.get("HED") if isinstance(definition, dict) else None
        if not isinstance(hed, dict):
            continue

        for label, annotation in hed.items():
            match = re.fullmatch(r"dot_no([2-8])_(ON|OFF)", label)
            if match and "Def/dot-no-1" in annotation:
                position = "dot-no-" + match[1]
                hed[label] = annotation.replace("Def/dot-no-1", "Def/" + position) if position in positions else ""
                issues.add("A06")

    return result, issues


# A06: target 9 + response 13 + target-end 5 -> visual feedback on the recorded end row, preserving original columns
def feedback_annotations(rows, metadata, source):
    descriptions = source.get("feedback", {}).get("HED", {})
    if not descriptions:
        return rows, metadata, Counter()

    rows = [dict(row) for row in rows]
    counts = Counter()
    task, target, responses = None, None, []
    for row in rows:
        code = row["event_code"]
        if code in STARTS or code in ("break cnt", "boundary", "50"):
            if target is not None:
                counts["missing_end"] += 1
            task, target, responses = STARTS.get(code), None, []
            continue

        if task != "contrast":
            if row["value"] in ("left_target", "right_target"):
                counts["unknown_task_context"] += 1
            continue

        if code in ("8", "9"):
            if target is not None:
                counts["missing_end"] += 1
            target, responses = row, []
        elif code in ("12", "13") and target is not None:
            responses.append(row)
        elif code == "5" and target is not None:
            delay = float(row["onset"]) - float(target["onset"])
            # a 50 ms consistency window tolerates frame/sample jitter, not a different stimulus schedule
            nominal = abs(delay - 2.4) <= 0.05
            counts["unusual_timing"] += not nominal
            if len(responses) != 1:
                counts["missing_response" if not responses else "multiple_responses"] += 1
            else:
                response = responses[0]
                correct = int(response["event_code"]) - int(target["event_code"]) == 4
                outcome = "smiley_face" if correct else "sad_face"
                if response.get("feedback") != outcome or outcome not in descriptions or delay <= 0:
                    counts["inconsistent_outcome_or_time"] += 1
                else:
                    annotation = descriptions[outcome]
                    if nominal:
                        annotation = f"({annotation}, Duration/400 ms)"
                    previous = row.get("HED", "n/a")
                    if annotation not in previous:
                        row["HED"] = annotation if previous == "n/a" else previous + ", " + annotation
                    counts["annotated"] += 1

            target, responses = None, []

    if target is not None:
        counts["missing_end"] += 1

    if counts["annotated"]:
        rows = [dict(row, HED=row.get("HED", "n/a")) for row in rows]

    if counts["unusual_timing"]:
        # retain target identity without asserting fixed phase lengths contradicted by this recording
        metadata = deepcopy(metadata)
        for side in ("left", "right"):
            hed = metadata.get("value", {}).get("HED", {})
            if side + "_target" in hed:
                hed[side + "_target"] = f"(Def/{side}-target)"

    return rows, metadata, counts


# A01/A03/A06: effective metadata + observed rows -> only the columns needing recording-level overrides
def event_overrides(metadata, rows, changes, definitions):
    result = deepcopy(metadata)
    issues = set()
    for column in rows[0] if rows else ():
        if column not in result and column in definitions:
            result[column] = deepcopy(definitions[column])
            issues.add("A03")

        definition = result.get(column, {})
        observed = {row[column] for row in rows} - {"", "n/a"}
        for field in ("Levels", "HED"):
            if isinstance(definition.get(field), dict):
                missing = observed - definition[field].keys()
                for value in sorted(missing):
                    definition[field][value] = ("" if field == "HED" else
                        definitions.get(column, {}).get("Levels", {}).get(value, f"Retained source marker: {value}"))

                if missing:
                    issues.add("A06" if field == "HED" else "A03")

    # A01: reused codes have context-dependent meanings; the value column carries the actual label
    changed_codes = {rows[change["line"] - 2]["event_code"] for change in changes}
    for code in changed_codes:
        labels = sorted({row["value"] for row in rows if row["event_code"] == code})
        definition = result.setdefault("event_code", {"Description": "Original acquisition marker code"})
        definition.setdefault("Levels", {})[code] = "Task-context label in value: " + "; ".join(labels)
        if isinstance(definition.get("HED"), dict):
            definition["HED"][code] = ""

    return {key: value for key, value in result.items() if metadata.get(key) != value}, issues


# A06: the validator checks local HED independently, so include its inherited definitions and referenced columns
def self_contained_hed(local, effective):
    if any(isinstance(value, dict) and "HED" in value for value in local.values()):
        local = {key: value for key, value in effective.items() if isinstance(value, dict) and "HED" in value} | local
        for key in re.findall(r"\{(\w+)\}", json.dumps(local)):
            if key in effective:
                local.setdefault(key, effective[key])

    return local


# A06: retain an initial dot offset, but do not assert a HED interval whose onset is outside the recording
def initial_offset_annotation(rows, metadata):
    if rows and rows[0].get("hed_annotation") == "initial_offset":
        metadata = deepcopy(metadata)
        metadata["value"].pop("HED", None)
        return rows, metadata, True

    annotation = metadata.get("value", {}).get("HED", {}).get(rows[0]["value"], "") if rows else ""
    if "Offset" not in annotation or not rows[0]["value"].endswith("_OFF"):
        return rows, metadata, False

    metadata = deepcopy(metadata)
    hed = metadata["value"].pop("HED")
    metadata["hed_annotation"] = {
        "Description": "HED annotation key; value retains the original event label. "
                       "The first offset is a point event because its preceding onset is not recorded",
        "HED": hed | {"initial_offset": "Label/Initial-offset"},
    }
    rows = [dict(row, hed_annotation=row["value"]) for row in rows]
    rows[0]["hed_annotation"] = "initial_offset"

    return rows, metadata, True


# A07/A08: confirm the EGI channel schema against .set before filling type, units or count
def repair_channels(eeg, channels, header):
    eeg, channels = deepcopy(eeg), [dict(channel) for channel in channels]
    names = [channel["name"] for channel in channels]
    if len(names) != header["nbchan"] or names != header["channel_names"] and header["channel_names"]:
        raise ValueError("A07: channel table does not match .set channel order/count")

    known = (len(names) == 129 and set(names) == EGI_CHANNELS and header["channel_names"] == names
             and "egi" in eeg.get("Manufacturer", "").lower() and eeg.get("EEGReference") == "Cz")
    issues = set()
    for channel in channels:
        for column, value in (("type", "EEG"), ("units", "uV")):
            if known and channel.get(column, "n/a") in ("", "n/a"):
                channel[column] = value
                issues.add("A07")

    if "EEGChannelCount" not in eeg and all(channel.get("type") == "EEG" for channel in channels):
        eeg["EEGChannelCount"] = len(channels)
        issues.add("A08")

    unresolved = not known and any(channel.get(field, "n/a") in ("", "n/a") for channel in channels for field in ("type", "units"))
    return eeg, channels, issues, unresolved
