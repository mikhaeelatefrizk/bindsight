"""Reproduce Linux ZIP header bytes without changing any wheel member payload."""
import hashlib
import io
import json
import zipfile
from pathlib import Path

root = Path(__file__).resolve().parent
source = root / "boltz-source/boltz-2.0.3+bindsight.1-py3-none-any.whl"
runtime_path = root / "production-checkpoint-smoke-38fb37a/output-v1/<GPU_JOB_ID>-runtime-evidence/runtime-receipt.json"
receipt = json.loads(runtime_path.read_text())
expected = receipt["boltz_runtime_wheel"]["patched_sha256"]
original = source.read_bytes()
output = io.BytesIO()
changes = []
with zipfile.ZipFile(io.BytesIO(original)) as before, zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as after:
    for member in before.infolist():
        changes.append({"member": member.filename, "from_create_system": member.create_system, "to_create_system": 3})
        member.create_system = 3
        after.writestr(member, before.read(member.filename))
rebuilt = output.getvalue()
actual = hashlib.sha256(rebuilt).hexdigest()
assert actual == expected, (actual, expected)
with zipfile.ZipFile(io.BytesIO(original)) as before, zipfile.ZipFile(io.BytesIO(rebuilt)) as after:
    assert before.namelist() == after.namelist()
    assert all(before.read(name) == after.read(name) for name in before.namelist())
destination = root / "boltz-source-linux-reproduced"
destination.mkdir(exist_ok=False)
(destination / source.name).write_bytes(rebuilt)
record = {"passed": True, "original_reference_sha256": hashlib.sha256(original).hexdigest(),
          "reproduced_linux_sha256": actual, "actual_gpu_receipt_sha256": expected,
          "same_all_member_bytes": True, "members": len(changes),
          "transformation": "ZIP create_system platform header from Windows 0 to Unix 3 only; all decompressed members unchanged",
          "changes": changes, "scope": "Exact full-wheel byte reproduction matches the separately downloaded actual GPU runtime receipt; no installed package or scientific outputs changed."}
(destination / "verification.json").write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")
print(json.dumps({k: v for k, v in record.items() if k != "changes"}, indent=2))
