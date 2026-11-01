"""Exercise the local CLI with a completed real GPU archive and retained input spec."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys

import pandas as pd
from bindsight.archive_bounds import open_bounded_tar


def sha(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("--archive", type=Path, required=True)
parser.add_argument("--submitted-spec", type=Path, required=True)
parser.add_argument("--repo", type=Path, required=True)
parser.add_argument("--output", type=Path, required=True)
parser.add_argument("--installed", action="store_true", help="Exercise the installed wheel with isolated Python outside the checkout")
args = parser.parse_args()
archive = args.archive.resolve()
spec = args.submitted_spec.resolve()
assert sha(spec) == "e779ae496bdeafbe7e26264ab5d360c3cf80c3162570f2e715f2a7f40b59c389", "Unrecognized submitted smoke spec"
source_digest = sha(archive)
destination = args.output.resolve()
destination.mkdir(parents=True, exist_ok=False)
run = destination / "run"
design = run / "design"
design.mkdir(parents=True)
handle = archive.name.removesuffix(".tar.gz")
assert handle and archive.name.endswith(".tar.gz")
shutil.copyfile(archive, design / archive.name)
shutil.copyfile(spec, design / (handle + ".spec.json"))
with open_bounded_tar(archive, max_bytes=8 * 1024**3, max_members=100000) as bundle:
    metric_member = bundle.getmember("metrics.jsonl")
    assert metric_member.isfile() and metric_member.size < 64 * 1024**2
    stream = bundle.extractfile(metric_member)
    assert stream is not None
    with stream:
        original = [json.loads(line) for line in stream if line.strip()]
expected = {row["binder_id"]: row for row in original}
assert len(expected) == len(original) == 2
assert set(expected) == {"P04626_binder_42_seq0", "P04626_binder_42_seq1"}
python_prefix = [sys.executable] + (["-I"] if args.installed else [])
execution_dir = destination if args.installed else args.repo.resolve()
identity_code = (
    "import hashlib,json,pathlib,importlib.metadata as m; import bindsight.cli as c; "
    "print(json.dumps({'version':m.version('bindsight'),"
    "'cli_sha256':hashlib.sha256(pathlib.Path(c.__file__).read_bytes()).hexdigest()}))"
)
identity = json.loads(subprocess.check_output(python_prefix + ["-c", identity_code], cwd=execution_dir, text=True, timeout=60))
assert identity["version"] == "0.3.8"
committed_cli = subprocess.check_output(["git", "-C", str(args.repo.resolve()), "show", "HEAD:bindsight/cli.py"])
assert identity["cli_sha256"] == hashlib.sha256(committed_cli).hexdigest()
commands = []
for iteration in range(2):
    command = python_prefix + ["-m", "bindsight.cli", "validate", str(run)]
    completed = subprocess.run(command, cwd=execution_dir, capture_output=True, text=True, timeout=180)
    (destination / f"validate-{iteration + 1}.log").write_text(completed.stdout + completed.stderr, encoding="utf-8", newline="\n")
    commands.append({"operation": "bindsight validate", "exit_code": completed.returncode})
    assert completed.returncode == 0, completed.stdout + completed.stderr
    table = pd.read_parquet(run / "validate/validated.parquet").set_index("binder_id")
    assert set(table.index) == set(expected) and len(table) == 2
    for binder, row in expected.items():
        for key, value in row.items():
            if key == "binder_id":
                continue
            measured = table.loc[binder, key]
            assert (bool(pd.isna(measured)) if value is None else measured == value), (binder, key, measured, value)
    assert sha(design / archive.name) == source_digest
    stored = list((design / "_targets").glob("*.tar.gz"))
    assert len(stored) == 1 and sha(stored[0]) == source_digest
assert sha(archive) == source_digest
record = {
    "passed": True,
    "source_archive_sha256": source_digest,
    "submitted_spec_sha256": sha(spec),
    "binder_rows": len(expected),
    "all_original_metric_fields_preserved": True,
    "original_and_imported_archives_byte_identical": True,
    "repeat_validation_passed": True,
    "installed_wheel_isolated_execution": args.installed,
    "observed_implementation": identity,
    "commands": commands,
    "scope": "Actual production Kaggle archive through shared local downloaded-result importer; not live Colab execution.",
}
(destination / "verification.json").write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8", newline="\n")
print(json.dumps(record, indent=2))
