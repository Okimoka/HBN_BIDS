"""A09: inventory original EEG exports without downloading their signal arrays"""

from concurrent.futures import ThreadPoolExecutor
import csv
import io
import json
from pathlib import Path

import boto3
from botocore import UNSIGNED
from botocore.config import Config

from .inventory import TASKS, MOVIES
from .io import write_json


BUCKET = "fcp-indi"
PREFIX = "data/Projects/HBN/EEG/"


# selected subjects -> cached object inventory, including subjects with no original EEG exports
def source_inventory(subjects, path):
    if path.exists():
        result = json.loads(path.read_text())
        if not set(subjects) <= result.keys():
            raise ValueError("A09: source inventory does not cover all selected subjects")

        return result

    client = boto3.client("s3", config=Config(signature_version=UNSIGNED, max_pool_connections=12))

    # one NDAR identifier -> original EEG objects and marker sets for ordinal movie names
    def list_subject(subject):
        pages = client.get_paginator("list_objects_v2").paginate(Bucket=BUCKET, Prefix=f"{PREFIX}{subject}/EEG/raw/")
        objects = [{key: obj[key] for key in ("Key", "Size", "ETag")} for page in pages for obj in page.get("Contents", [])]

        for obj in objects:
            # ordinal movies are identified by codes, never by Video1 -> a guessed movie title
            if Path(obj["Key"]).name.startswith("Video") and obj["Key"].endswith("_event.csv"):
                text = client.get_object(Bucket=BUCKET, Key=obj["Key"])["Body"].read().decode("utf-8-sig")
                obj["event_codes"] = sorted({row["type"].strip() for row in csv.DictReader(io.StringIO(text))})

        return subject, objects

    with ThreadPoolExecutor(max_workers=12) as pool:
        result = dict(pool.map(list_subject, sorted(subjects)))

    temporary = path.with_suffix(".json.part")
    write_json(temporary, result)
    temporary.replace(path)

    return result


# one subject's S3 listing -> task/run exports; MAT and CSV are representations of the same named export
def source_recordings(objects, eeg_tasks):
    grouped = {}
    for obj in objects:
        name = Path(obj["Key"]).name
        suffix = next((suffix for suffix in ("_data.csv", "_event.csv", ".mat") if name.endswith(suffix)), None)
        if suffix:
            grouped.setdefault(name.removesuffix(suffix), {})[suffix] = obj

    result = []
    aliases = TASKS | {"RestingState": ("RestingState", None)} | {
        f"SurroundSupp_Block{run}": ("surroundSupp", str(run)) for run in (1, 2)}
    for name, files in sorted(grouped.items()):
        # event-only fragments do not prove a signal export ever existed
        if ".mat" not in files and "_data.csv" not in files:
            continue

        target = aliases.get(name)
        if name.startswith("Video"):
            codes = set(files.get("_event.csv", {}).get("event_codes", []))
            movies = {task for pair, task in MOVIES.items() if {str(code) for code in pair} <= codes}
            if len(movies) == 1:
                target = (movies.pop(), None)
            elif name not in aliases:
                target = None

        if name == "vis_learn":
            tasks = set(eeg_tasks) & {"seqLearning6target", "seqLearning8target"}
            target = (tasks.pop(), None) if len(tasks) == 1 else None

        task, run = target or (name, None)
        signal = files.get("_data.csv", files.get(".mat"))
        result.append({"task": task, "run": run or "n/a", "source_task": name,
                       "source_mapping": "task_alias" if target else "unresolved",
                       "source_mat": "s3://" + BUCKET + "/" + files[".mat"]["Key"] if ".mat" in files else "n/a",
                       "source_csv": "s3://" + BUCKET + "/" + files["_data.csv"]["Key"] if "_data.csv" in files else "n/a",
                       "source_fingerprint": f"{signal['ETag']}:{signal['Size']}"})

    return result
