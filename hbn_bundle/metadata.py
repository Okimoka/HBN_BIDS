"""Combine prepared releases' participant tables and dataset descriptions"""

from collections import defaultdict
import json
import os

import pandas as pd


# {"R1": Path(...), ...} -> merged metadata, participant rows, subject links and issues
# input columns age and sex become their union; missing cells are written as n/a
def collect_metadata(roots, output):
    descriptions, tables, definitions, links, issues = {}, [], defaultdict(list), {}, []
    for release, root in roots.items():
        descriptions[release] = json.loads((root / "dataset_description.json").read_text())
        table = pd.read_csv(root / "participants.tsv", sep="\t", dtype=str, keep_default_na=False)
        if table["participant_id"].duplicated().any():
            raise ValueError(f"Duplicate participant rows in {release}")
        subjects = {path.name: path for path in sorted(root.glob("sub-*")) if path.is_dir()}
        if not set(subjects) <= set(table["participant_id"]):
            raise ValueError(f"Participant table and subject directories disagree in {release}")

        # repaired subsets retain the original participant file; the merged table describes linked subjects
        table = table[table["participant_id"].isin(subjects)]
        if duplicates := links.keys() & subjects.keys():
            raise ValueError(f"Duplicate subjects across releases: {sorted(duplicates)}")
        links.update(subjects)
        tables.append(table)
        for name, definition in json.loads((root / "participants.json").read_text()).items():
            definitions[name].append((release, definition))
    participants = pd.concat(tables, ignore_index=True).fillna("n/a").replace("", "n/a")
    participants = participants[["participant_id", *[name for name in participants if name != "participant_id"]]]
    participants = participants.sort_values("participant_id", ignore_index=True)
    metadata = {}
    for column in participants:
        merged, conflict = {}, False
        for _, definition in definitions[column]:
            merged, different = merge_definition(merged, definition)
            conflict |= different
        if conflict:
            merged["SourceDefinitions"] = dict(definitions[column])
            issues.append({"kind": "participant_description_conflict", "field": column})
        if not merged:
            merged = {"Description": f"Original HBN participant field {column}; no source dictionary definition supplied."}
            issues.append({"kind": "missing_participant_definition", "field": column})
        metadata[column] = merged
    sources = list(descriptions.values())
    for field in ("BIDSVersion", "HEDVersion"):
        if len({json.dumps(source.get(field), sort_keys=True) for source in sources}) != 1:
            raise ValueError(f"Prepared releases have different {field} values")
    ignored = {"Name", "DatasetDOI", "DatasetType", "GeneratedBy", "SourceDatasets", "SourceDatesets",
               "License", "HBNRelease", "DatasetLinks"}
    common = set.intersection(*(set(source) for source in sources)) - ignored
    description = {key: sources[0][key] for key in sorted(common)
                   if all(source[key] == sources[0][key] for source in sources)}
    provenance = {json.dumps(source, sort_keys=True): source for description in sources
                  for source in description.get("SourceDatasets", [])}
    generators = {json.dumps(generator, sort_keys=True): generator for description in sources
                  for generator in description.get("GeneratedBy", [])}
    description.update(Name="Healthy Brain Network EEG with eye tracking — combined releases", DatasetType="raw",
                       GeneratedBy=[*generators.values(), {"Name": "hbn_bundle", "Version": "1"}],
                       SourceDatasets=list(provenance.values()),
                       DatasetLinks={release: os.path.relpath(root, output) for release, root in roots.items()})
    issues.append({"kind": "combined_license_not_inferred", "field": "License"})
    return description, participants, metadata, links, issues


# root task-rest_events.json -> sub-A/sub-A_task-rest_events.json for subjects with that task
# recording directories stay linked while each release's shared definitions remain applicable
def scoped_sidecars(roots):
    links = {}
    for root in roots.values():
        sidecars = sorted(path for path in root.glob("*.json") if path.name.endswith(("_eeg.json", "_events.json")))
        for subject in sorted(root.glob("sub-*")):
            recordings = [dict(part.split("-", 1) for part in path.stem.split("_") if "-" in part)
                          for path in subject.rglob("*_eeg.set")]
            for path in sidecars:
                selectors = dict(part.split("-", 1) for part in path.stem.split("_") if "-" in part)
                if any(selectors.items() <= recording.items() for recording in recordings):
                    name = path.name if "sub" in selectors else subject.name + "_" + path.name
                    links[f"{subject.name}/{name}"] = path

    return links


# combine the same recording schema across releases; original per-release sheets remain linked under code/Rn
def collect_quality(roots):
    tables, definitions = [], {}
    for root in roots.values():
        path = root / "code/recording_quality.tsv"
        if path.exists():
            tables.append(pd.read_csv(path, sep="\t", dtype=str, keep_default_na=False))
            metadata = json.loads(path.with_suffix(".json").read_text())
            definitions, conflict = merge_definition(definitions, metadata)
            if conflict:
                raise ValueError("Conflicting recording-quality descriptions across releases")

    quality = pd.concat(tables, ignore_index=True).fillna("n/a") if tables else None
    return quality, definitions


# combine compatible definitions; differing prose is retained in SourceDefinitions by the caller
def merge_definition(left, right, path=""):
    output, prose_conflict = dict(left), False
    for key, value in right.items():
        if key not in output:
            output[key] = value
        elif isinstance(output[key], dict) and isinstance(value, dict):
            output[key], conflict = merge_definition(output[key], value, path + key + ".")
            prose_conflict |= conflict
        elif output[key] != value:
            if isinstance(value, str) and isinstance(output[key], str) and output[key].split() == value.split():
                output[key] = " ".join(value.split())
            elif not path and key in ("Description", "LongName"):
                output[key] = "Source descriptions differ; see SourceDefinitions."
                prose_conflict = True
            else:
                raise ValueError(f"Conflicting participant metadata: {path + key}")
    return output, prose_conflict
