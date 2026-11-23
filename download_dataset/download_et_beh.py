#!/usr/bin/env python3
"""Download original HBN eye-tracking and behavioral files from public S3"""

from pathlib import Path

import boto3
from boto3.s3.transfer import S3Transfer, TransferConfig
from botocore import UNSIGNED
from botocore.config import Config

from download_utils import RemoteFile, check_selection, download_files, parse_args, safe_parts


BUCKET = "fcp-indi"
PREFIX = "data/Projects/HBN/EEG/"
MODALITIES = {"et": "Eyetracking", "beh": "Behavioral"}

# list and download ET/BEH; --only eeg intentionally does nothing here so the
# shared launcher can pass the same arguments to both downloaders
def main(argv=None):
    # use __doc__ (opening string at the top of this file) as the --help description
    args = parse_args(__doc__, ["et", "beh"], argv)
    if set(args.only).isdisjoint(MODALITIES):
        return
    client = make_client(args.concurrency)
    files = collect_files(client, args)
    config = TransferConfig(max_concurrency=args.concurrency, preferred_transfer_client="classic")
    # one SDK request pool shared across all files, including multipart transfers
    with S3Transfer(client, config) as transfer:
        download_files(files, args, lambda remote, path: transfer.download_file(BUCKET, remote.source, str(path)))


# make_client(4) -> anonymous S3 client with room for ten reusable connections
# main() sets transfer concurrency separately
def make_client(concurrency):
    return boto3.client("s3", region_name="us-east-1", config=Config(
        signature_version=UNSIGNED,  # public bucket, no AWS credentials needed
        max_pool_connections=max(10, concurrency),
        retries={"mode": "standard", "total_max_attempts": 5},
    ))


# (similar to collect_files in download_eeg)
# select S3 entries and convert their keys into local ET/BEH paths
# example entry (schematic filename and size):
#
# {"Key": "data/Projects/HBN/EEG/NDARAB793GL3/Eyetracking/txt/a.txt", "Size": 2048}
#
# corresponds to this entry in the returned list:
#
# RemoteFile(
#     source="data/Projects/HBN/EEG/NDARAB793GL3/Eyetracking/txt/a.txt",
#     relative_path=Path("ET/NDARAB793GL3/txt/a.txt"),
#     size=2048,
# )
def collect_files(client, args):
    categories = {name: kind.upper() for kind, name in MODALITIES.items() if kind in args.only}
    print(f"Listing {' + '.join(categories.values())}: s3://{BUCKET}/{PREFIX}", flush=True)
    # full runs list the tree once but never download raw EEG. Subject filters
    # list only those subjects' ET/BEH subtrees. Preserve every format and ID
    prefixes = [PREFIX]
    if args.subjects:
        prefixes = []
        for subject in sorted(args.subjects):
            for category in categories:
                prefixes.append(f"{PREFIX}{subject}/{category}/")
    files, seen_subjects = [], set()
    for prefix in prefixes:
        # no manifests files like in download_eeg, so use list_objects_v2 instead
        pages = client.get_paginator("list_objects_v2").paginate(Bucket=BUCKET, Prefix=prefix)
        for page in pages:
            for obj in page.get("Contents", []):
                if obj["Key"].endswith("/"):
                    continue
                relative = obj["Key"][len(PREFIX):]
                parts = relative.split("/")
                if len(parts) < 3 or parts[1] not in categories:
                    continue
                safe_parts(relative)
                seen_subjects.add(parts[0])
                files.append(RemoteFile(obj["Key"], Path(categories[parts[1]], parts[0], *parts[2:]), obj["Size"]))
    check_selection(files, args, seen_subjects)
    return files

if __name__ == "__main__":
    main()
