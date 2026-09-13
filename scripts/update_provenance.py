#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import json
import subprocess
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


def main() -> None:
    if PROV.exists():
        doc = json.loads(PROV.read_text())
    else:
        doc = {}

    entries = []
    for rel in tracked_files():
        path = ROOT / rel
        if not path.is_file():
            raise SystemExit(f"tracked path is not a regular file: {rel}")
        entries.append(
            {
                "bytes": path.stat().st_size,
                "path": rel,
                "sha256": sha256(path),
            }
        )

    doc["files"] = entries
    PROV.write_text(
        json.dumps(doc, indent=2, sort_keys=False) + "\n",
        encoding="utf-8",
    )
    print(f"updated {PROV.name}: {len(entries)} tracked files")


if __name__ == "__main__":
    main()
