"""Run with python -m smi2bids from the project root"""

import argparse

from . import smi2bids


parser = argparse.ArgumentParser(description=__doc__)
for name in ("samples-file", "events-file", "output-dir", "bids-prefix"):
    parser.add_argument(f"--{name}", required=True)

parser.add_argument("--metadata-file", help="Optional YAML overrides for header-derived metadata")
parser.add_argument("--start-time", type=float, required=True, help="First sample relative to EEG start, in seconds")
parser.add_argument("--clock-scale", type=float, default=1.0, help="Reference-clock seconds per device second")
parser.add_argument("--overwrite", action="store_true", help="Replace this converter's eye files")

for path in smi2bids(**vars(parser.parse_args())):
    print(path)
