from __future__ import annotations

import argparse
import hashlib
import json
from collections import defaultdict
from pathlib import Path
from typing import Any

VOLATILE_RUN_CONFIG_KEYS = {
    "resume_checkout_path",
    "resume_session",
}


class ReconciliationError(ValueError):
    pass


def _json_sha256(value: Any) -> str:
    raw = json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        default=str,
    ).encode()
    return hashlib.sha256(raw).hexdigest()


def _file_sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _payload_sha(row: dict[str, Any]) -> str:
    return row.get("payload_sha256") or _json_sha256(
        row.get("payload")
    )


def _sort_key(row: dict[str, Any]) -> tuple[Any, ...]:
    ts = row.get("timestamp")
    if not ts:
        raise ReconciliationError(
            "every captured event must have a timestamp"
        )
    return (
        str(ts),
        int(row.get("_audit_stream_index", 0)),
        int(row.get("_audit_line", 0)),
    )


def _public_observation(
    row: dict[str, Any],
) -> dict[str, Any]:
    return {
        "source": row.get("_audit_source"),
        "line": row.get("_audit_line"),
        "timestamp": row.get("timestamp"),
        "payload_sha256": _payload_sha(row),
    }


def _normalized_run_config(
    payload: dict[str, Any],
) -> dict[str, Any]:
    return {
        k: v
        for k, v in payload.items()
        if k not in VOLATILE_RUN_CONFIG_KEYS
    }


def validate_run_configs(
    run_configs: list[dict[str, Any]],
    source_labels: list[str],
) -> dict[str, Any]:
    if not run_configs:
        raise ReconciliationError(
            "no run_config observations found"
        )

    per_source: dict[str, int] = defaultdict(int)
    for row in run_configs:
        per_source[str(row["_audit_source"])] += 1

    missing_sources = sorted(
        set(source_labels) - set(per_source)
    )
    repeated_sources = sorted(
        source
        for source, n in per_source.items()
        if n != 1
    )

    if missing_sources or repeated_sources:
        raise ReconciliationError(
            "expected exactly one run_config per source stream; "
            f"missing={missing_sources}, "
            f"non_singleton={repeated_sources}"
        )

    run_lock_hashes = []
    normalized_hashes = []

    observations = []

    for row in sorted(run_configs, key=_sort_key):
        payload = row.get("payload")
        if not isinstance(payload, dict):
            raise ReconciliationError(
                "run_config payload must be a JSON object"
            )

        run_lock = payload.get("run_lock")
        if not isinstance(run_lock, dict):
            raise ReconciliationError(
                "run_config missing run_lock object"
            )

        lock_sha = _json_sha256(run_lock)
        norm_sha = _json_sha256(
            _normalized_run_config(payload)
        )

        run_lock_hashes.append(lock_sha)
        normalized_hashes.append(norm_sha)

        observations.append(
            {
                **_public_observation(row),
                "run_lock_sha256": lock_sha,
                "normalized_run_config_sha256": norm_sha,
                "resume_provenance_present": any(
                    k in payload
                    for k in VOLATILE_RUN_CONFIG_KEYS
                ),
            }
        )

    lock_unique = sorted(set(run_lock_hashes))
    config_unique = sorted(set(normalized_hashes))

    report = {
        "observation_count": len(run_configs),
        "volatile_fields_ignored_for_semantic_equality": sorted(
            VOLATILE_RUN_CONFIG_KEYS
        ),
        "run_lock_sha256": (
            lock_unique[0]
            if len(lock_unique) == 1
            else None
        ),
        "normalized_run_config_sha256": (
            config_unique[0]
            if len(config_unique) == 1
            else None
        ),
        "run_lock_consistent": len(lock_unique) == 1,
        "semantic_run_config_consistent": (
            len(config_unique) == 1
        ),
        "observations": observations,
    }

    if len(lock_unique) != 1:
        raise ReconciliationError(
            "run_lock drift detected across resume streams: "
            + ", ".join(lock_unique)
        )

    if len(config_unique) != 1:
        raise ReconciliationError(
            "semantic run_config drift detected after removing "
            "resume-only provenance fields: "
            + ", ".join(config_unique)
        )

    return report


def _canonicalize_attempt(
    trial_id: str,
    attempt_index: int,
    observations: list[dict[str, Any]],
) -> tuple[
    list[dict[str, Any]],
    list[dict[str, Any]],
    int,
]:
    by_tag: dict[str, list[dict[str, Any]]] = defaultdict(
        list
    )

    for row in observations:
        by_tag[str(row.get("tag"))].append(row)

    logical: list[dict[str, Any]] = []
    groups: list[dict[str, Any]] = []
    exact_duplicate_groups = 0

    for tag, rows in by_tag.items():
        rows = sorted(rows, key=_sort_key)

        by_sha: dict[str, list[dict[str, Any]]] = (
            defaultdict(list)
        )
        for row in rows:
            by_sha[_payload_sha(row)].append(row)

        # A different proposal would already have created a new
        # attempt. Any other conflicting same-stage payload inside
        # one attempt is ambiguous and must not be silently merged.
        if len(by_sha) > 1:
            raise ReconciliationError(
                "conflicting payloads inside one execution "
                f"attempt: trial={trial_id}, "
                f"attempt={attempt_index}, tag={tag}, "
                f"payloads={sorted(by_sha)}"
            )

        chosen = rows[0]
        logical.append(chosen)

        duplicate = len(rows) > 1
        if duplicate:
            exact_duplicate_groups += 1

        groups.append(
            {
                "trial_id": trial_id,
                "attempt_index": attempt_index,
                "tag": tag,
                "classification": (
                    "exact_duplicate"
                    if duplicate
                    else "unique"
                ),
                "observation_count": len(rows),
                "selected": _public_observation(chosen),
                "observations": [
                    _public_observation(r)
                    for r in rows
                ],
            }
        )

    return (
        sorted(logical, key=_sort_key),
        groups,
        exact_duplicate_groups,
    )


def reconcile_trial(
    trial_id: str,
    rows: list[dict[str, Any]],
) -> tuple[
    list[dict[str, Any]],
    dict[str, Any],
    list[dict[str, Any]],
    int,
]:
    rows = sorted(rows, key=_sort_key)

    preproposal: list[dict[str, Any]] = []
    attempts: list[dict[str, Any]] = []
    current: dict[str, Any] | None = None

    for row in rows:
        tag = row.get("tag")

        if tag == "proposal":
            sha = _payload_sha(row)

            if current is None:
                current = {
                    "proposal_sha256": sha,
                    "observations": [row],
                }
            elif sha == current["proposal_sha256"]:
                # Same proposal replayed: same attempt.
                current["observations"].append(row)
            else:
                # A genuinely different proposal is the only
                # defensible old-data attempt boundary.
                attempts.append(current)
                current = {
                    "proposal_sha256": sha,
                    "observations": [row],
                }
        else:
            if current is None:
                preproposal.append(row)
            else:
                current["observations"].append(row)

    if current is not None:
        attempts.append(current)

    if preproposal:
        raise ReconciliationError(
            f"trial {trial_id} has downstream events before "
            "its first captured proposal; attempt lineage is "
            "not reconstructible without an explicit override"
        )

    if not attempts:
        raise ReconciliationError(
            f"trial {trial_id} has no captured proposal"
        )

    # Conservative rule:
    # the latest distinct proposal defines the current attempt.
    # We never borrow downstream events from an older attempt.
    canonical_index = len(attempts) - 1
    canonical = attempts[canonical_index]

    logical, groups, duplicate_groups = (
        _canonicalize_attempt(
            trial_id,
            canonical_index,
            canonical["observations"],
        )
    )

    attempt_reports = []

    for i, attempt in enumerate(attempts):
        obs = sorted(
            attempt["observations"],
            key=_sort_key,
        )

        tags = []
        for row in obs:
            tag = str(row.get("tag"))
            if tag not in tags:
                tags.append(tag)

        sources = []
        for row in obs:
            source = str(row.get("_audit_source"))
            if source not in sources:
                sources.append(source)

        attempt_reports.append(
            {
                "attempt_index": i,
                "proposal_sha256": (
                    attempt["proposal_sha256"]
                ),
                "canonical": i == canonical_index,
                "observation_count": len(obs),
                "tags_observed": tags,
                "sources": sources,
                "first_timestamp": obs[0]["timestamp"],
                "last_timestamp": obs[-1]["timestamp"],
            }
        )

    report = {
        "trial_id": trial_id,
        "attempt_count": len(attempts),
        "canonical_attempt_index": canonical_index,
        "selection_rule": (
            "latest_distinct_proposal_attempt; "
            "never mix downstream events across attempts"
        ),
        "superseded_attempt_count": len(attempts) - 1,
        "attempts": attempt_reports,
    }

    return (
        logical,
        report,
        groups,
        duplicate_groups,
    )


def reconcile_rows(
    rows: list[dict[str, Any]],
    source_labels: list[str],
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    rows = sorted(rows, key=_sort_key)

    run_configs = [
        r for r in rows
        if r.get("tag") == "run_config"
    ]

    config_report = validate_run_configs(
        run_configs,
        source_labels,
    )

    canonical_run_config = min(run_configs, key=_sort_key)

    by_trial: dict[str, list[dict[str, Any]]] = (
        defaultdict(list)
    )

    for row in rows:
        tid = str(row.get("trial_id"))
        if tid == "__run__":
            continue
        by_trial[tid].append(row)

    def trial_key(tid: str):
        return (
            not tid.isdigit(),
            int(tid) if tid.isdigit() else tid,
        )

    logical_trial_events: list[dict[str, Any]] = []
    trial_reports = []
    groups = []
    exact_duplicate_groups = 0
    superseded_attempt_count = 0

    for tid in sorted(by_trial, key=trial_key):
        (
            logical,
            trial_report,
            trial_groups,
            duplicates,
        ) = reconcile_trial(tid, by_trial[tid])

        logical_trial_events.extend(logical)
        trial_reports.append(trial_report)
        groups.extend(trial_groups)

        exact_duplicate_groups += duplicates
        superseded_attempt_count += trial_report[
            "superseded_attempt_count"
        ]

    logical_events = [
        canonical_run_config,
        *sorted(logical_trial_events, key=_sort_key),
    ]

    report = {
        "schema": "agent-alpha-audit.reconciliation.v2",
        "policy": {
            "run_config": (
                "all run_lock and normalized semantic "
                "run_config values must agree; "
                "resume_session/resume_checkout_path are "
                "provenance-only"
            ),
            "attempt_boundary": (
                "new distinct proposal payload within a "
                "trial starts a new execution attempt"
            ),
            "canonical_attempt": (
                "latest distinct proposal attempt"
            ),
            "same_attempt_duplicate": (
                "identical payloads collapse logically but "
                "all observations remain in execution history"
            ),
            "same_attempt_conflict": (
                "different payloads for the same tag hard-fail"
            ),
        },
        "raw_event_count": len(rows),
        "logical_event_count": len(logical_events),
        "logical_trial_count": len(by_trial),
        "run_config_consistency": config_report,
        "exact_duplicate_groups": exact_duplicate_groups,
        "superseded_attempt_count": (
            superseded_attempt_count
        ),
        "trial_attempts": trial_reports,
        # Kept for compatibility with v1 consumers.
        "reconciliation": groups,
    }

    return logical_events, report


def load_event_streams(
    base: str | Path,
) -> tuple[
    list[dict[str, Any]],
    list[dict[str, Any]],
]:
    base = Path(base).resolve()

    files = sorted(
        p
        for p in base.rglob("rdagent_events.jsonl")
        if "postrun" not in p.relative_to(base).parts
    )

    if not files:
        raise ReconciliationError(
            f"no rdagent_events.jsonl under {base}"
        )

    all_rows = []
    stream_reports = []

    for stream_index, path in enumerate(files):
        rel = path.relative_to(base).as_posix()

        rows = []
        with path.open(encoding="utf-8") as f:
            for line_no, line in enumerate(f, 1):
                if not line.strip():
                    continue

                row = json.loads(line)
                row["_audit_source"] = rel
                row["_audit_line"] = line_no
                row["_audit_stream_index"] = (
                    stream_index
                )

                rows.append(row)
                all_rows.append(row)

        stream_reports.append(
            {
                "source": rel,
                "sha256": _file_sha256(path),
                "event_count": len(rows),
            }
        )

    return all_rows, stream_reports


def write_outputs(
    base: str | Path,
    out_dir: str | Path,
) -> dict[str, Any]:
    rows, streams = load_event_streams(base)

    logical_events, report = reconcile_rows(
        rows,
        [x["source"] for x in streams],
    )

    report["source_streams"] = streams

    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)

    with (out / "execution_history.jsonl").open(
        "w",
        encoding="utf-8",
    ) as f:
        for row in sorted(rows, key=_sort_key):
            f.write(
                json.dumps(
                    row,
                    ensure_ascii=False,
                    sort_keys=True,
                )
                + "\n"
            )

    with (out / "logical_events.jsonl").open(
        "w",
        encoding="utf-8",
    ) as f:
        for row in logical_events:
            f.write(
                json.dumps(
                    row,
                    ensure_ascii=False,
                    sort_keys=True,
                )
                + "\n"
            )

    (out / "reconciliation.json").write_text(
        json.dumps(
            report,
            indent=2,
            ensure_ascii=False,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )

    return report


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base", required=True)
    parser.add_argument("--out-dir", required=True)
    args = parser.parse_args()

    report = write_outputs(
        args.base,
        args.out_dir,
    )

    print(
        json.dumps(
            {
                "schema": report["schema"],
                "raw_event_count": (
                    report["raw_event_count"]
                ),
                "logical_event_count": (
                    report["logical_event_count"]
                ),
                "logical_trial_count": (
                    report["logical_trial_count"]
                ),
                "exact_duplicate_groups": (
                    report["exact_duplicate_groups"]
                ),
                "superseded_attempt_count": (
                    report["superseded_attempt_count"]
                ),
                "run_lock_consistent": report[
                    "run_config_consistency"
                ]["run_lock_consistent"],
                "semantic_run_config_consistent": report[
                    "run_config_consistency"
                ][
                    "semantic_run_config_consistent"
                ],
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
