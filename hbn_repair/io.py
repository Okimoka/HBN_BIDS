"""Small file/report helpers; originals are only read"""

from collections import Counter
import csv
import hashlib
import json
import shutil
import subprocess

import pandas as pd


# write indented UTF-8 JSON, creating its parent folder; Path values become strings
def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False, allow_nan=False, default=str) + "\n")


# list of row dictionaries -> TSV; lists/dicts become JSON cells and None becomes "n/a"
def write_rows(path, rows, columns=()):
    rows = [{key: json.dumps(value, default=str) if isinstance(value, (list, dict)) else value
             for key, value in row.items()} for row in rows]
    table = pd.DataFrame(rows, dtype=object) if rows else pd.DataFrame(columns=columns)
    path.parent.mkdir(parents=True, exist_ok=True)
    table.to_csv(path, sep="\t", index=False, na_rep="n/a")


# hash a file in small blocks so large EEG files need not fit in memory
def sha256(path):
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


# TSV -> string-valued dictionaries; literal n/a and original categorical values stay intact
def read_table(path, delimiter="\t"):
    with path.open() as stream:
        return list(csv.DictReader(stream, delimiter=delimiter))


# copy small metadata; optionally link large signal containers and verify actual copies
# copy_file(Path("input/eeg.set"), Path("output/eeg.set"), "symlink") -> output path
def copy_file(source, destination, mode):
    if mode == "symlink" and source.suffix.lower() in (".set", ".fdt"):
        destination.symlink_to(source.resolve())
    else:
        shutil.copy2(source, destination)
        if sha256(source) != sha256(destination):
            raise OSError(f"Hash mismatch after copying {source} to {destination}")

    return destination


# run the external validator and save its output; return a count/exit-code summary and issue list
def validate_dataset(output, reports, validator):
    command = [str(validator), str(output), "--schema",
               "https://bids-specification.readthedocs.io/en/v1.11.2/schema.json",
               "--max-rows", "-1", "--format", "json", "--outfile", str(reports / "validation.json")]
    (reports / "validation.json").unlink(missing_ok=True)
    result = subprocess.run(command, capture_output=True, text=True)
    (reports / "validation.log").write_text(result.stdout + result.stderr)
    document = json.loads((reports / "validation.json").read_text())
    issues = document["issues"]["issues"]
    counts = Counter(issue["severity"] for issue in issues)
    return {"command": command, "returncode": result.returncode,
            "errors": counts["error"], "warnings": counts["warning"]}, issues
