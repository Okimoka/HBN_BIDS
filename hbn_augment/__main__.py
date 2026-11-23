"""run from HBN_BIDS: python -m hbn_augment --help"""

import argparse
import json

from . import augment_dataset


parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("--input", required=True, help="Reviewed repaired collection containing EEG/Rn, ET and BEH")
parser.add_argument("--output", required=True)
parser.add_argument("--reports", help="Default: sibling <output>_reports directory")
parser.add_argument("--releases", type=int, nargs="+", choices=range(1, 12))
parser.add_argument("--file-mode", choices=("copy", "symlink"), default="copy")
parser.add_argument("--metadata-file", help="Optional SMI metadata YAML; see smi2bids/README.md")
parser.add_argument("--max-residual-ms", type=float, default=20)
parser.add_argument("--max-clock-deviation", type=float, default=0.01)
parser.add_argument("--validate", action="store_true")
parser.add_argument("--validator", default="bids-validator-deno")
parser.add_argument("--dry-run", action="store_true", help="Inventory/match only; write no files")

arguments = vars(parser.parse_args())
arguments["max_residual_s"] = arguments.pop("max_residual_ms") / 1000
summary = augment_dataset(**arguments)
print(json.dumps(summary, indent=2))
raise SystemExit(1 if summary["status"] == "validation_failed" else 0)
