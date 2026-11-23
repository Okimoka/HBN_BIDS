"""run from HBN_BIDS: python -m hbn_repair --help"""

import argparse
import json

from . import repair_dataset


parser = argparse.ArgumentParser(description="A01–A15: repair published EEG releases, then stop for review")
parser.add_argument("--input", required=True)
parser.add_argument("--output", required=True)
parser.add_argument("--reports", help="Default: sibling <output>_reports directory")
parser.add_argument("--subjects", nargs="+")
parser.add_argument("--releases", nargs="+", type=int, choices=range(1, 12))
parser.add_argument("--file-mode", choices=("copy", "symlink"), default="copy")
parser.add_argument("--source-inventory", dest="source_inventory_file", help="Reuse an earlier s3_inventory.json instead of listing S3")
parser.add_argument("--reviews", help="Explicit recommendations TSV keyed by recording_id; overrides automatic screening")
parser.add_argument("--validate", action="store_true")
parser.add_argument("--validator", default="bids-validator-deno")

summary = repair_dataset(**vars(parser.parse_args()))
print(json.dumps(summary, indent=2))
raise SystemExit(1 if summary["status"] == "validation_failed" else 0)
