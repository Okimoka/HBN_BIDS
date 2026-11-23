#!/usr/bin/env python3
"""Download published BIDS HBN releases from NEMAR"""

import json
from pathlib import Path
import subprocess
from tempfile import TemporaryDirectory
from urllib.request import urlopen

from download_utils import RemoteFile, check_selection, download_files, parse_args, safe_parts

# these are the same as ds005xxx from OpenNeuro
RELEASES = {
    1: "on005505", 2: "on005506", 3: "on005507", 4: "on005508",
    5: "on005509", 6: "on005510", 7: "on005511", 8: "on005512",
    9: "on005514", 10: "on005515", 11: "on005516",
}

# v1.0.0 in NEMAR corresponds to v1.0.1 in OpenNeuro (for all releases)
VERSION = "v1.0.0"

# select EEG files and transfer them; --only et/beh skips this stage entirely
def main(argv=None):
    # use __doc__ (opening string at the top of this file) as the --help description
    args = parse_args(__doc__, ["eeg"], argv)
    if "eeg" not in args.only:
        return
    download_files(collect_files(args), args, fetch_file)


# manifest.json lists all files in the dataset along with attributes
# example entry for R1 (on005505):
#
# [
# ...
#   {
#    "path": "sub-NDARAC904DMU/eeg/sub-NDARAC904DMU_task-DespicableMe_channels.tsv",
#    "size": 1454,
#    "url": "https://data.nemar.org/on005505/v1.0.0/sub-NDARAC904DMU/eeg/sub-NDARAC904DMU_task-DespicableMe_channels.tsv",
#    ...
#    },
# ...
# ]
#
# size is in bytes; path is relative to this release's BIDS root
# collect_files selects entries based on args and returns them as RemoteFile objects:
#
# [
#     RemoteFile(
#         source="https://data.nemar.org/on005505/v1.0.0/sub-NDARAC904DMU/eeg/sub-NDARAC904DMU_task-DespicableMe_channels.tsv",
#         relative_path=Path("EEG/R1/sub-NDARAC904DMU/eeg/sub-NDARAC904DMU_task-DespicableMe_channels.tsv"),
#         size=1454,
#     ),
#     ...
# ]

def collect_files(args):
    files, seen_subjects = [], set()
    for release in args.releases:
        url = f"https://data.nemar.org/{RELEASES[release]}/{VERSION}/manifest.json"
        print(f"Listing EEG R{release}: {url}", flush=True)
        with urlopen(url, timeout=60) as response:
            manifest = json.load(response)
        for item in manifest:
            parts = safe_parts(item["path"])
            if parts[0].startswith("sub-"):
                subject = parts[0][4:]
                if args.subjects and subject not in args.subjects:
                    continue
                seen_subjects.add(subject)
            # keep shared metadata, including the complete participants table
            files.append(RemoteFile(item["url"], Path("EEG", f"R{release}", *parts), item["size"]))
    check_selection(files, args, seen_subjects)
    return files


# download one manifest URL to destination; replace an existing file only after
# curl succeeds and the received size matches the manifest
def fetch_file(remote, destination):
    with TemporaryDirectory(prefix=".download-", dir=destination.parent) as temporary:
        partial = Path(temporary) / destination.name
        subprocess.run(["curl", "--fail", "--location", "--silent", "--show-error", "--retry", "3",
                        "--output", str(partial), remote.source], check=True)
        if partial.stat().st_size != remote.size:
            raise ValueError(f"Downloaded size differs from manifest: {remote.source}")
        partial.replace(destination)

if __name__ == "__main__":
    main()
