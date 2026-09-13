#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PROV = ROOT / "PROVENANCE.json"


def tracked_files() -> list[str]:
    out = subprocess.check_output(
        ["git", "ls-files"], cwd=ROOT, text=True
    )
    return sorted(
        p for p in out.splitlines()
        if p and p != "PROVENANCE.json"
    )


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def main() -> int:
    doc = json.loads(PROV.read_text())
    entries = doc.get("files", [])
    manifest = {x["path"]: x for x in entries}

    expected = set(tracked_files())
    recorded = set(manifest)

    errors: list[str] = []

    for rel in sorted(expected - recorded):
        errors.append(f"MISSING_FROM_PROVENANCE {rel}")

    for rel in sorted(recorded - expected):
        errors.append(f"NOT_TRACKED_OR_STALE {rel}")

    for rel in sorted(expected & recorded):
        path = ROOT / rel
        if not path.is_file():
            errors.append(f"MISSING_FILE {rel}")
            continue

        actual_hash = sha256(path)
        actual_bytes = path.stat().st_size
        item = manifest[rel]

        if item.get("sha256") != actual_hash:
            errors.append(f"SHA256_MISMATCH {rel}")
        if item.get("bytes") != actual_bytes:
            errors.append(f"BYTE_COUNT_MISMATCH {rel}")

    if errors:
        print("\n".join(errors))
        print(f"\nFAIL: {len(errors)} provenance error(s)")
        return 1

    print(
        f"PASS: provenance matches {len(expected)} tracked files "
        "(PROVENANCE.json intentionally self-excluded)"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
