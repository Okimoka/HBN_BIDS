"""Create a local BIDS dataset by linking independently prepared HBN releases"""

from collections import Counter
import hashlib
import json
import os
from pathlib import Path
import subprocess

import pandas as pd

from .metadata import collect_metadata, scoped_sidecars, collect_quality


ROOT_FILES = ("dataset_description.json", "participants.tsv", "participants.json", "README",
              "code/recording_quality.tsv", "code/recording_quality.json")


# HBN_AUGMENTED/EEG/{R1,R2,...} -> a combined BIDS root with relative links and merged root metadata
# reruns replace only this tool's links/generated files; prepared source files are never written
def bundle_dataset(dataset, output, *, releases=None, reports=None, validate=False,
                   validator="bids-validator-deno", dry_run=False):
    dataset, output = Path(dataset).resolve(), Path(output).absolute()
    if output.is_symlink():
        raise ValueError("Bundle output must not be a symlink")
    output = output.resolve()
    reports = Path(reports).resolve() if reports else output.with_name(output.name + "_reports")
    for left, right in ((dataset, output), (dataset, reports), (output, reports)):
        if left.is_relative_to(right) or right.is_relative_to(left):
            raise ValueError("Prepared inputs, bundle and reports must be separate trees")
    numbers = sorted(set(releases)) if releases else sorted(
        number for number in range(1, 12) if (dataset / f"R{number}").is_dir())
    if not numbers:
        raise ValueError("No prepared releases selected")
    roots = {f"R{number}": dataset / f"R{number}" for number in numbers}
    description, participants, metadata, links, issues = collect_metadata(roots, output)
    quality, quality_metadata = collect_quality(roots)
    links = {str(Path(name) / child.name): child for name, directory in links.items() for child in directory.iterdir()}
    shared = scoped_sidecars(roots)
    if conflicts := links.keys() & shared.keys():
        raise ValueError(f"Shared sidecars collide with existing subject-level metadata: {sorted(conflicts)}")
    links.update(shared)
    for release, root in roots.items():
        if (root / "sourcedata").is_dir():
            links[f"sourcedata/{release}"] = root / "sourcedata"
        if (root / "code").is_dir():
            links[f"code/{release}"] = root / "code"
    old_links = check_existing(output, reports)
    summary = {"status": "planned" if dry_run else "building", "releases": list(roots),
               "subjects": len(participants), "output": str(output), "reports": str(reports),
               "validation": "not_run"}
    if dry_run:
        return summary
    configuration = {"tool": "hbn_bundle", "output": str(output),
                     "inputs": [{"release": release, "path": str(root),
                                 "metadata_sha256": {name: hashlib.sha256((root / name).read_bytes()).hexdigest()
                                                     for name in ROOT_FILES[:3]}}
                                for release, root in roots.items()],
                     "links": {name: str(source) for name, source in links.items()}}
    output.mkdir(parents=True, exist_ok=True)
    reports.mkdir(parents=True, exist_ok=True)
    write_json(reports / "summary.json", summary)
    for name in ("validation.json", "validation.log"):
        (reports / name).unlink(missing_ok=True)
    # remove links themselves; neither unlink nor rmdir follows a symlink into source data
    for name in old_links:
        (output / name).unlink(missing_ok=True)
    for name in ROOT_FILES:
        (output / name).unlink(missing_ok=True)
    directories = {parent for name in [*ROOT_FILES, *old_links] for parent in Path(name).parents if parent != Path(".")}
    for directory in sorted(directories, key=lambda path: len(path.parts), reverse=True):
        if (output / directory).exists():
            (output / directory).rmdir()
    write_json(reports / "build.json", configuration)
    for name, source in links.items():
        destination = output / name
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.symlink_to(os.path.relpath(source, destination.parent), target_is_directory=source.is_dir())
    write_json(output / "dataset_description.json", description)
    write_json(output / "participants.json", metadata)
    participants.to_csv(output / "participants.tsv", sep="\t", index=False)
    if quality is not None:
        (output / "code").mkdir(exist_ok=True)
        quality.to_csv(output / "code/recording_quality.tsv", sep="\t", index=False)
        write_json(output / "code/recording_quality.json", quality_metadata)
    (output / "README").write_text(
        "HBN EEG and eye tracking: combined prepared releases\n\n"
        "This is a local analysis view built by hbn_bundle. Recording directories and\n"
        "source archives link to independently prepared releases listed in DatasetLinks.\n"
        "Keep those releases available. Changes through these links change the sources;\n"
        "write preprocessing results to a separate derivatives directory.\n"
        "Shared EEG/events JSON is linked in each subject directory, preserving\n"
        "each release's inheritance without applying one release's definitions to another.\n"
        "The recording-quality tables are combined in code/recording_quality.tsv.\n"
        "Bundling performs no matching, synchronization, conversion or preprocessing.\n"
        "The combined view has no assigned publication DOI or inferred blanket license.\n")
    pd.DataFrame(issues, columns=("kind", "field")).to_csv(reports / "issues.tsv", sep="\t", index=False)
    pd.DataFrame([{"output": name, "source": str(source)} for name, source in links.items()],
                 columns=("output", "source")).to_csv(reports / "links.tsv", sep="\t", index=False)
    summary["status"] = "complete"
    if validate:
        summary["validation"] = validate_dataset(output, reports, validator, description["BIDSVersion"])
        if summary["validation"]["returncode"]:
            summary["status"] = "validation_failed"
    write_json(reports / "summary.json", summary)
    return summary


# check the old bundle contains only owned files and links, never source directories to overwrite
def check_existing(output, reports):
    if not output.exists() or not any(output.iterdir()):
        return {}
    previous = json.loads((reports / "build.json").read_text())
    if previous["tool"] != "hbn_bundle" or previous["output"] != str(output):
        raise ValueError("Output belongs to a different build")
    links = previous["links"]
    owned = set(ROOT_FILES) | links.keys()
    directories = {str(parent) for name in owned for parent in Path(name).parents if parent != Path(".")}
    for folder, dirs, files in os.walk(output, followlinks=False):
        for name in dirs + files:
            relative = str((Path(folder) / name).relative_to(output))
            if relative not in owned | directories:
                raise ValueError(f"Unowned file or directory in bundle: {relative}")
            if relative in directories and (output / relative).is_symlink():
                raise ValueError(f"Expected a real directory: {relative}")
    for name in ROOT_FILES:
        path = output / name
        if path.is_symlink() or (path.exists() and not path.is_file()):
            raise ValueError(f"Expected a generated regular file: {path}")
    for name, source in links.items():
        path = output / name
        if path.is_symlink():
            if path.resolve() != Path(source).resolve():
                raise ValueError(f"Bundle link has been replaced: {path}")
        elif path.exists():
            raise ValueError(f"Expected an owned symlink: {path}")
    return links


# validate the combined view, retaining the full validator report outside the dataset
def validate_dataset(output, reports, validator, version):
    command = [str(validator), str(output), "--schema",
               f"https://bids-specification.readthedocs.io/en/v{version}/schema.json",
               "--max-rows", "-1", "--format", "json", "--outfile", str(reports / "validation.json")]
    result = subprocess.run(command, capture_output=True, text=True)
    (reports / "validation.log").write_text(result.stdout + result.stderr)
    issues = json.loads((reports / "validation.json").read_text())["issues"]["issues"]
    counts = Counter(issue["severity"] for issue in issues)
    return {"command": command, "returncode": result.returncode,
            "errors": counts["error"], "warnings": counts["warning"]}


# write generated JSON; all callers check output ownership before writing
def write_json(path, value):
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False, allow_nan=False) + "\n")
