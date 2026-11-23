"""Run from HBN_BIDS: python -m hbn_bundle --help"""

import argparse
import json

from . import bundle_dataset


parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("--dataset", required=True, help="Directory containing prepared R1, R2, ... datasets")
parser.add_argument("--output", required=True)
parser.add_argument("--reports", help="Default: sibling <output>_reports directory")
parser.add_argument("--releases", type=int, nargs="+", choices=range(1, 12))
parser.add_argument("--validate", action="store_true", help="Run the BIDS validator across all rows")
parser.add_argument("--validator", default="bids-validator-deno")
parser.add_argument("--dry-run", action="store_true", help="Check inputs and metadata without writing files")
summary = bundle_dataset(**vars(parser.parse_args()))
print(json.dumps(summary, indent=2))
if isinstance(summary.get("validation"), dict) and summary["validation"]["returncode"]:
    raise SystemExit(summary["validation"]["returncode"])
