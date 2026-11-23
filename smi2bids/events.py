"""Read interleaved SMI event tables without rerunning event detection"""

import csv
from decimal import Decimal

import pandas as pd

from .samples import header_entry, snake


KINDS = {"fixation": "fixation", "saccade": "saccade", "blink": "blink",
         "userevent": "message", "trigger": "trigger"}

SECTIONS = {"Fixations": "fixation", "Saccades": "saccade", "Blinks": "blink",
            "User Events": "message", "Trigger Line Events": "trigger", "Triggers": "trigger"}

ALIASES = {'Trial': 'trial', 'Number': 'event_number', 'End': 'end_timestamp', 'Avg. Pupil Size X': 'average_pupil_size_x',
    'Avg Pupil Size Y': 'average_pupil_size_y', 'Peak Accel.': 'peak_acceleration', 'Peak Decel.': 'peak_deceleration', 'Average Accel.': 'average_acceleration',
    'Location X': 'location_x', 'Location Y': 'location_y', 'Dispersion X': 'dispersion_x', 'Dispersion Y': 'dispersion_y',
    'Start Loc.X': 'start_location_x', 'Start Loc.Y': 'start_location_y', 'End Loc.X': 'end_location_x', 'End Loc.Y': 'end_location_y'}



# split exported events by eye; shared messages/triggers belong to both eyes
# returns ({eye label: (table, metadata)}, messages)
# for example, a 2,000 us duration becomes 0.002 s when clock_scale=1
def read_events(path, clock_scale, available_eyes):
    header, tables, records, messages, columns = {}, {}, [], [], {}
    section = None

    with open(path, encoding="utf-8-sig") as source:
        for row in csv.reader(source, delimiter="\t", quoting=csv.QUOTE_NONE):
            if not row or not row[0].strip():
                continue

            if row[0].startswith("Table Header for "):
                section = SECTIONS[row[0].removeprefix("Table Header for ").rstrip(":")]
                continue
            if section:
                tables[section], section = row, None
                continue
            if row[0].split()[0].lower() not in KINDS:
                if tables:
                    raise ValueError(f"Unknown event row: {row[0]}")
                header_entry("\t".join(row), header)
                continue

            words = row[0].split()
            kind = KINDS[words[0].lower()]
            names = tables[kind]
            if len(row) > len(names) and names[-1] == "Description":
                row = row[:len(names) - 1] + ["\t".join(row[len(names) - 1:])]
            if len(row) != len(names):
                raise ValueError(f"Event width {len(row)} != header width {len(names)}")

            event = dict(zip(names, row))
            onset = Decimal(event["Start"])
            duration = Decimal(event.get("Duration", "0")) * Decimal(str(clock_scale)) / 1_000_000
            if not onset.is_finite() or not duration.is_finite() or duration < 0:
                raise ValueError("Nonfinite onset or invalid event duration")

            message = event.get("Description", "n/a").strip() or "n/a"
            record = {"onset": event["Start"], "duration": format(duration, "f"),
                      "trial_type": kind, "message": message}

            for name, value in event.items():
                if name in ("Event Type", "Start", "Duration", "Description"):
                    continue

                target = ALIASES.get(name, snake(name))
                if target in record or (target in columns and columns[target]["SourceColumn"] != name):
                    raise ValueError(f"Event column collision: {name}")
                record[target] = value.strip() or "n/a"
                columns[target] = {"Description": f"SMI export column: {name}.", "SourceColumn": name}
                if name == "End":
                    columns[target].update(Units="us", Origin="SMI system startup")
                elif target.startswith(("location_", "dispersion_", "start_location_",
                                        "end_location_", "average_pupil_size_")):
                    columns[target]["Units"] = "pixel"

            eye = words[-1] if words[-1] in ("L", "R") else None
            if eye and eye not in available_eyes:
                raise ValueError(f"Events contain eye {eye}, but Samples has no columns for it")
            records.append((eye, record))
            if kind == "message":
                messages.append((event["Start"], message))

    if not tables:
        raise ValueError("No SMI event table headers found")

    metadata = {"OnsetSource": "timestamp", "SMISourceHeader": header,
                "onset": {"Description": "Native SMI timestamp, as in physio timestamp.", "Units": "us"},
                "duration": {"Description": "Duration in reference-clock seconds.", "Units": "s"},
                "trial_type": {"Description": "SMI event category; detection not rerun."},
                "message": {"Description": "Original SMI message."}, **columns}

    output = {}
    order = ["onset", "duration", "trial_type", "message", *columns]
    for eye, label in [("L", "eye1"), ("R", "eye2")]:
        selected = [record for owner, record in records if owner in (None, eye)]
        if selected:
            output[label] = (pd.DataFrame(selected, columns=order, dtype=object).fillna("n/a"),
                             {**metadata, "Columns": order})

    return output, messages
