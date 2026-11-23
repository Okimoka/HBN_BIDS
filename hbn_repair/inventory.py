"""Inventory source recordings and match explicit HBN task aliases without writes"""

from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
import csv
from dataclasses import dataclass, field
import json
import os
from pathlib import Path
import re

from .io import sha256


TASKS = {
    "resting": ("RestingState", None), "WISC_ProcSpeed": ("symbolSearch", None),
    "Video-DM": ("DespicableMe", None), "Video-WK": ("DiaryOfAWimpyKid", None),
    "Video-FF": ("FunwithFractals", None), "Video-TP": ("ThePresent", None),
    **{f"SAIIT_2AFC_Block{run}": ("contrastChangeDetection", str(run)) for run in range(1, 4)},
    **{f"SurrSupp_Block{run}": ("surroundSupp", str(run)) for run in range(1, 3)},
}

# treat an extra filename digit as a naming error only for these documented cases
# NDARAEZ493ZJ/NDARAEZ493ZJ6_resting -> subject NDARAEZ493ZJ, task resting
EXTRA_DIGIT = {"NDARAEZ493ZJ", "NDARXF358XGE", "NDARAM487XU3", "NDARXL697DA6", "NDARHC661KGK"}
MOVIES = {(81, 101): "DiaryOfAWimpyKid", (82, 102): "FunwithFractals",
          (83, 103): "DespicableMe", (84, 104): "ThePresent"}


@dataclass
class Recording:
    release: int
    release_root: Path
    subject: str                         # NDARAB793GL3
    prefix: str                          # sub-NDARAB793GL3_task-symbolSearch
    eeg: Path
    files: list[Path]
    et_samples: Path | None = None
    et_events: Path | None = None
    status: str = "missing_et"
    notes: list[str] = field(default_factory=list)
    candidates: list[Path] = field(default_factory=list)


@dataclass
class ETEntry:
    subject: str
    source_subject: str
    task: str
    files: list[Path]
    samples: Path | None = None
    events: Path | None = None
    format: str = "smi"
    status: str = "missing_eeg"
    mapped_task: str | None = None
    mapped_run: str | None = None
    notes: list[str] = field(default_factory=list)
    matched_prefixes: list[str] = field(default_factory=list)


@dataclass
class Plan:
    releases: dict[int, Path]
    recordings: list[Recording]
    et_entries: list[ETEntry]


# HBN_RAW/ and optional selections -> Plan of EEG/ET sources and candidate matches; no writes
def plan_inputs(dataset: Path, releases: list[int] | None = None,
                subjects: list[str] | None = None) -> Plan:
    dataset = Path(dataset)
    selected = {subject.removeprefix("sub-") for subject in subjects} if subjects else None
    release_roots = {number: root for number, root in eeg_releases(dataset).items()
                     if releases is None or number in releases}
    recordings = []
    for number, root in release_roots.items():
        subject_dirs = [root / f"sub-{subject}" for subject in sorted(selected)] if selected else sorted(root.glob("sub-*"))
        # list each directory once; repeated glob/stat calls are costly over SSHFS
        for directory in subject_dirs:
            for folder, directories, names in os.walk(directory):
                directories.sort()
                paths = sorted(Path(folder) / name for name in names)
                for eeg in (path for path in paths if path.name.endswith("_eeg.set")):
                    prefix = eeg.name.removesuffix("_eeg.set")
                    subject = entities(prefix)["sub"]
                    if not selected or subject in selected:
                        files = [path for path in paths if path.name.rsplit("_", 1)[0] == prefix]
                        recordings.append(Recording(number, root, subject, prefix, eeg, files))
    et_entries = []
    if (dataset / "ET").exists():
        for subject_dir in sorted((dataset / "ET").iterdir()):
            if selected and subject_dir.name.removeprefix("sub-") not in selected:
                continue
            if subject_dir.is_dir():
                et_entries.extend(read_et(subject_dir))
    by_subject, by_prefix = defaultdict(list), defaultdict(list)
    for recording in recordings:
        by_subject[recording.subject].append(recording)
        by_prefix[recording.prefix].append(recording)
    matches = defaultdict(list)
    # read independent movie message files concurrently; retain source order when matching
    movie_files = {entry.events for entry in et_entries if entry.events and "Video" in entry.task}
    with ThreadPoolExecutor(max_workers=8) as pool:
        movie_results = {path: pool.submit(movie_targets, path) for path in movie_files}
    for entry in et_entries:
        if entry.format != "smi" or entry.status in ("unresolved_identity", "duplicate_source"):
            continue
        available = by_subject[entry.subject]
        try:
            movies = movie_results[entry.events].result() if entry.events in movie_results else set()
        except (ValueError, UnicodeError) as error:
            entry.status = "invalid_events"
            entry.notes.append(str(error))
            continue
        if "Video" in entry.task:
            entry.notes.append("Complete movie marker pairs: " + (", ".join(sorted(movies)) or "none"))
        target = task_target(entry.task, {entities(item.prefix)["task"] for item in available}, movies)
        if target is None:
            if entry.status == "missing_eeg":
                entry.status = "unmapped_task"
            continue
        task, run = target
        entry.mapped_task, entry.mapped_run = task, run
        if entry.status != "missing_eeg":
            continue
        candidates = [recording for recording in available
                      if entities(recording.prefix).get("task") == task
                      and (entities(recording.prefix).get("run") == run if run else
                           entities(recording.prefix).get("run") in (None, "1"))]
        if not candidates:
            continue
        entry.matched_prefixes = [candidate.prefix for candidate in candidates]
        for candidate in candidates:
            matches[candidate.prefix].append(entry)
    for prefix, same_prefix in by_prefix.items():
        candidates = matches[prefix]
        unique = {}
        for entry in candidates:
            key = (sha256(entry.samples), sha256(entry.events)) if len(candidates) > 1 else (entry.samples, entry.events)
            if key in unique:
                entry.status = "duplicate_source"
                entry.notes.append(f"Byte-identical duplicate of {unique[key].samples.name}")
            else:
                unique[key] = entry
        for recording in same_prefix:
            recording.candidates = [path for entry in candidates for path in entry.files]
            if len(same_prefix) > 1 or len(unique) > 1:
                recording.status = "ambiguous_et" if len(unique) > 1 else "duplicate_eeg"
                recording.notes.append("Multiple source candidates; no file chosen")
                for entry in unique.values():
                    entry.status = "ambiguous_pair"
            elif unique:
                entry = next(iter(unique.values()))
                recording.et_samples, recording.et_events = entry.samples, entry.events
                recording.status = entry.status = "matched"
                recording.notes.extend(entry.notes)
    return Plan(release_roots, recordings, et_entries)


# locate published EEG roots by their participants table: HBN_RAW/ -> {1: Path('.../R1'), ...}
def eeg_releases(dataset):
    release_roots = {}
    for root in sorted((dataset / "EEG").iterdir()):
        if not root.is_dir() or not (root / "participants.tsv").exists():
            continue
        with (root / "participants.tsv").open() as source:
            number = int(next(csv.DictReader(source, delimiter="\t"))["release_number"].removeprefix("R"))
        if number in release_roots:
            raise ValueError(f"Multiple source directories for release R{number}")
        release_roots[number] = root
    return release_roots


# subject folder -> ETEntry objects; matching *_Samples.txt and *_Events.txt form one entry
def read_et(subject_dir):
    """Retain original grouping and identity, including unmatched source formats"""
    subject = subject_dir.name.removeprefix("sub-")
    root = subject_dir / "Eyetracking" if (subject_dir / "Eyetracking").exists() else subject_dir
    grouped, entries = defaultdict(dict), []
    paths = []
    for folder, directories, names in os.walk(root):
        if Path(folder) == root and "Behavioral" in directories:
            directories.remove("Behavioral")
        paths.extend(Path(folder) / name for name in names)
    for path in sorted(paths):
        if path.name.endswith(".save"):
            entries.append(ETEntry(subject, subject_dir.name, "", [path], format="backup", status="ignored_backup"))
            continue
        match = re.fullmatch(r"(.+)_(Samples|Events)\.txt", path.name)
        if not match:
            entries.append(ETEntry(subject, subject_dir.name, path.stem, [path],
                                   format=path.suffix.removeprefix("."), status="unsupported_format"))
            continue
        grouped[(path.parent, match[1])][match[2]] = path
    for (_, stem), pair in grouped.items():
        entry = ETEntry(subject, subject_dir.name, "", list(pair.values()), pair.get("Samples"), pair.get("Events"))
        # directory identity remains authoritative; removing a filename artifact
        # does not rename a participant or join unrelated subject directories
        match = re.fullmatch(re.escape(subject) + r"(?:__|_|-)(.+)", stem)
        if match is None and subject in EXTRA_DIGIT:
            match = re.fullmatch(re.escape(subject) + r"\d(?:__|_|-)(.+)", stem)
            if match:
                entry.notes.append("Removed documented extra digit from filename prefix")
        if match is None:
            entry.status = "unresolved_identity"
            entry.notes.append("Filename prefix does not match its subject directory")
        else:
            entry.task = match[1]
            if not entry.samples:
                entry.status = "missing_samples"
            elif not entry.events:
                entry.status = "missing_events"
        entries.append(entry)
    # a mismatched prefix may be a byte-identical copy of a correctly named pair
    # (e.g. RV837BZQ / 5008455). Equality resolves redundancy, not new identity
    complete = [entry for entry in entries if entry.samples and entry.events]
    for entry in complete:
        if entry.status == "unresolved_identity":
            for canonical in complete:
                if canonical.status != "unresolved_identity" and all(
                    a.stat().st_size == b.stat().st_size and sha256(a) == sha256(b)
                    for a, b in [(entry.samples, canonical.samples), (entry.events, canonical.events)]
                ):
                    entry.status = "duplicate_source"
                    entry.notes.append(f"Byte-identical to {canonical.samples.name} and its Events file")
                    break
    return entries


# events file containing an ordered 83/103 pair -> {"DespicableMe"}, whatever its filename
def movie_targets(events):
    """Video1..4 denote presentation order, not a consistent movie identity"""
    if events is None:
        return set()
    markers = []
    for line in events.read_text().splitlines():
        row = line.split("\t")
        if row[0] == "UserEvent" and len(row) >= 5:
            match = re.search(r"# Message:\s*(\d+)\s*$", row[-1])
            if match:
                markers.append((float(row[3]), int(match[1])))
    return {task for (start, stop), task in MOVIES.items()
            if any(t1 < t2 for t1, code1 in markers if code1 == start
                   for t2, code2 in markers if code2 == stop)}


# ET task -> (EEG task, run), e.g. "SurrSupp_Block2" -> ("surroundSupp", "2"); None if unresolved
def task_target(task, eeg_tasks, movies):
    task = task.removeprefix("NODOOR_")
    if task == "II_SurrSupp_Block1":
        task = "SurrSupp_Block1"
    if task == "vis_learn":
        targets = {name for name in eeg_tasks if name in ("seqLearning6target", "seqLearning8target")}
        return (next(iter(targets)), None) if len(targets) == 1 else None
    if re.fullmatch(r"Video[1-4]", task):
        return (next(iter(movies)), None) if len(movies) == 1 else None
    if task.startswith("Video-") and movies and movies != {TASKS.get(task, (None,))[0]}:
        return None
    return TASKS.get(task)


# resolve one recording's metadata, e.g. root task EEG JSON plus its local EEG JSON
def inheritance(eeg: Path, suffix: str, release_root: Path) -> dict:
    """Resolve applicable JSON from release root through subject/session to eeg/.

    An inherited JSON field is replaced as a whole by a more specific field;
    event dictionaries therefore retain exactly their source BIDS interpretation
    """
    target = entities(eeg.stem.removesuffix("_eeg"))
    result = {}
    directories = [release_root]
    relative = eeg.parent.relative_to(release_root)
    directories += [release_root.joinpath(*relative.parts[:count]) for count in range(1, len(relative.parts) + 1)]
    for directory in directories:
        applicable = []
        for path in directory.glob(f"*_{suffix}.json"):
            selectors = entities(path.stem.removesuffix(f"_{suffix}"))
            if selectors.items() <= target.items():
                applicable.append((len(selectors), path))
        for _, path in sorted(applicable):
            result.update(json.loads(path.read_text()))
    return result


# "sub-NDARAB793GL3_task-symbolSearch" -> {"sub": "NDARAB793GL3", "task": "symbolSearch"}
def entities(prefix):
    return dict(part.split("-", 1) for part in prefix.split("_") if "-" in part)
