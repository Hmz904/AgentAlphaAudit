#!/usr/bin/env python3
"""Reconcile RD-Agent event streams across interrupted/resumed runs.

Produces:
1. execution_history.jsonl — immutable chronological evidence, including retries.
2. logical_events.jsonl    — one canonical event per (trial_id, tag) for ledger ingest.
3. reconciliation.json     — explicit provenance for duplicates / superseded variants.

Source files are never modified.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from collections import defaultdict
from pathlib import Path


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def load(base: Path):
    rows = []
    sources = []

    for path in sorted(base.rglob("rdagent_events.jsonl")):
        sources.append({
            "path": str(path),
            "sha256": sha256_file(path),
            "rows": 0,
        })
        with path.open(encoding="utf-8") as f:
            for line_no, line in enumerate(f, 1):
                if not line.strip():
                    continue
                r = json.loads(line)
                r["_audit_source"] = str(path)
                r["_audit_line"] = line_no
                rows.append(r)
                sources[-1]["rows"] += 1

    rows.sort(key=lambda r: (r.get("timestamp", ""), r["_audit_source"], r["_audit_line"]))
    return rows, sources


def strip_audit_fields(r):
    return {k: v for k, v in r.items() if not k.startswith("_audit_")}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", required=True, type=Path)
    ap.add_argument("--out-dir", required=True, type=Path)
    args = ap.parse_args()

    args.out_dir.mkdir(parents=True, exist_ok=True)
    rows, sources = load(args.base)

    execution_path = args.out_dir / "execution_history.jsonl"
    logical_path = args.out_dir / "logical_events.jsonl"
    manifest_path = args.out_dir / "reconciliation.json"

    # Full execution history: preserve everything.
    with execution_path.open("w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False, sort_keys=True) + "\n")

    # Run config: earliest config is the canonical experiment contract.
    run_configs = [r for r in rows if r.get("trial_id") == "__run__"]
    canonical_run_config = run_configs[0] if run_configs else None

    # Logical search history:
    # use the latest observed version of each (trial_id, tag).
    # Earlier differing payloads remain explicitly recorded as superseded provenance.
    groups = defaultdict(list)
    for r in rows:
        tid = r.get("trial_id")
        if tid in (None, "__run__"):
            continue
        groups[(str(tid), r.get("tag"))].append(r)

    selected = []
    reconciled = []

    for (tid, tag), rs in sorted(
        groups.items(),
        key=lambda kv: (
            int(kv[0][0]) if kv[0][0].isdigit() else 10**9,
            str(kv[0][1]),
        ),
    ):
        rs.sort(key=lambda r: r.get("timestamp", ""))
        chosen = rs[-1]

        hashes = {r.get("payload_sha256") for r in rs}
        status = (
            "unique"
            if len(rs) == 1
            else "exact_duplicate"
            if len(hashes) == 1
            else "superseded_variant"
        )

        selected.append(chosen)
        reconciled.append({
            "trial_id": tid,
            "tag": tag,
            "status": status,
            "selected": {
                "timestamp": chosen.get("timestamp"),
                "payload_sha256": chosen.get("payload_sha256"),
                "source": chosen["_audit_source"],
                "line": chosen["_audit_line"],
            },
            "observed": [
                {
                    "timestamp": r.get("timestamp"),
                    "payload_sha256": r.get("payload_sha256"),
                    "source": r["_audit_source"],
                    "line": r["_audit_line"],
                }
                for r in rs
            ],
        })

    selected.sort(
        key=lambda r: (
            int(str(r.get("trial_id"))) if str(r.get("trial_id")).isdigit() else 10**9,
            r.get("timestamp", ""),
        )
    )

    with logical_path.open("w", encoding="utf-8") as f:
        if canonical_run_config:
            f.write(json.dumps(strip_audit_fields(canonical_run_config),
                               ensure_ascii=False, sort_keys=True) + "\n")
        for r in selected:
            f.write(json.dumps(strip_audit_fields(r),
                               ensure_ascii=False, sort_keys=True) + "\n")

    manifest = {
        "schema": "agent-alpha-audit.reconciliation.v1",
        "policy": {
            "execution_history": "preserve_all_events",
            "logical_trial_key": ["trial_id", "tag"],
            "canonical_variant": "latest_timestamp",
            "run_config": "earliest_observed",
            "note": (
                "Superseded retries remain in execution_history and reconciliation; "
                "they are not counted as independent logical search trials."
            ),
        },
        "source_streams": sources,
        "raw_event_count": len(rows),
        "logical_event_count": len(selected) + (1 if canonical_run_config else 0),
        "logical_trial_count": len({
            str(r.get("trial_id"))
            for r in selected
            if r.get("trial_id") not in (None, "__run__")
        }),
        "reconciliation": reconciled,
    }

    manifest_path.write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )

    print(json.dumps({
        "raw_events": len(rows),
        "logical_events": manifest["logical_event_count"],
        "logical_trials": manifest["logical_trial_count"],
        "execution_history": str(execution_path),
        "logical_events_path": str(logical_path),
        "manifest": str(manifest_path),
    }, indent=2))


if __name__ == "__main__":
    main()
