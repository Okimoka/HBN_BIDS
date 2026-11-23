"""Shared arguments, file selection checks and concurrent transfers"""

import argparse
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from dataclasses import dataclass
from itertools import islice
from pathlib import Path
import time


@dataclass(frozen=True)
class RemoteFile:
    source: str          # S3 key: "data/Projects/HBN/EEG/NDAR.../Eyetracking/txt/...", or HTTPS URL
    relative_path: Path  # below --output, e.g. Path("EEG/R11/dataset_description.json")
    size: int            # file size in bytes, e.g. 2048


# normalize shared CLI options, including subject IDs and the output path
# example: --subjects sub-NDARAB793GL3 --output ./HBN_RAW
#   args.subjects -> {"NDARAB793GL3"}
#   args.output   -> Path("<current directory>/HBN_RAW")
def parse_args(description, default_only, argv=None):
    parser = argparse.ArgumentParser(description=description)
    parser.add_argument("--output", required=True, type=Path, help="Destination HBN_RAW directory")
    # both scripts accept these options so the Slurm launcher can forward them unchanged
    parser.add_argument("--only", nargs="+", choices=("eeg", "et", "beh"), default=default_only)
    parser.add_argument("--releases", nargs="+", type=int, choices=range(1, 12), default=list(range(1, 12)),
                        help="EEG releases (default: 1 through 11); ignored by ET/BEH")
    parser.add_argument("--subjects", nargs="+", help="Subject IDs, with or without sub-")
    parser.add_argument("--concurrency", type=int, default=16, help="Concurrent transfers (default: 16)")
    parser.add_argument("--dry-run", action="store_true", help="List selection without writing files")
    args = parser.parse_args(argv)
    args.subjects = {s.removeprefix("sub-") for s in args.subjects} if args.subjects else None
    args.output = args.output.expanduser().resolve()
    args.releases = list(dict.fromkeys(args.releases))
    return args


# split a source path while rejecting absolute paths and '..' components,
# which pathlib accepts but could place downloaded files outside --output
# example: "sub-A/eeg/a.set" -> ("sub-A", "eeg", "a.set")
def safe_parts(value):
    path = Path(value)
    if path.is_absolute() or ".." in path.parts:
        raise ValueError(f"Unsafe source path: {value!r}")
    return path.parts


# fail before downloading if the selection is empty or a requested subject was
# absent; e.g. requested {"A", "B"}, found {"A"} raises an error naming B
def check_selection(files, args, seen_subjects):
    if args.subjects and (missing := args.subjects - seen_subjects):
        raise ValueError("Subjects not found in this source: " + ", ".join(sorted(missing)))
    if not files:
        raise ValueError("No files found for the requested selection")


# format byte count for progress messages: human_size(1536) -> "1.5 KiB"
def human_size(size):
    for unit in ("B", "KiB", "MiB", "GiB", "TiB"):
        if size < 1024 or unit == "TiB":
            return f"{size:.1f} {unit}"
        size /= 1024


# save remote below output using the supplied fetch function; return "skipped"
# for an existing same-sized file, otherwise "downloaded" after success
def download_one(fetch, remote, output):
    destination = output / remote.relative_path
    if destination.is_file() and destination.stat().st_size == remote.size:
        return "skipped"
    destination.parent.mkdir(parents=True, exist_ok=True)
    fetch(remote, destination)
    return "downloaded"


# keep at most args.concurrency transfers in flight and report progress
# example return: {"downloaded": 3, "skipped": 2}
def download_files(files, args, fetch):
    print(f"{len(files):,} files, {human_size(sum(f.size for f in files))} -> {args.output}", flush=True)
    if args.dry_run:
        print("Dry run: nothing downloaded or written.", flush=True)
        return
    counts = {"downloaded": 0, "skipped": 0}
    remaining = iter(files)
    started = last_report = time.monotonic()
    # only keep one batch in flight, rather than a future for every dataset file
    with ThreadPoolExecutor(max_workers=args.concurrency) as workers:
        pending = {workers.submit(download_one, fetch, remote, args.output)
                   for remote in islice(remaining, args.concurrency)}
        while pending:
            done, pending = wait(pending, timeout=10, return_when=FIRST_COMPLETED)
            for future in done:
                counts[future.result()] += 1
            pending.update(workers.submit(download_one, fetch, remote, args.output)
                           for remote in islice(remaining, len(done)))
            now = time.monotonic()
            if now - last_report >= 10 or not pending:
                print(f"Progress {sum(counts.values()):,}/{len(files):,}: "
                      f"{counts['downloaded']:,} downloaded, {counts['skipped']:,} skipped "
                      f"({now - started:.0f}s)", flush=True)
                last_report = now
    return counts
