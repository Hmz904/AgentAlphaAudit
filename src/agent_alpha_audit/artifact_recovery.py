from __future__ import annotations

import argparse
import hashlib
import json
import pickletools
import re
import shutil
from collections import defaultdict
from pathlib import Path
from typing import Any

SCHEMA = "agent-alpha-audit.artifact-recovery.v1"


class ArtifactRecoveryError(ValueError):
    pass


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _sha256_file(path: Path) -> str:
    return _sha256_bytes(path.read_bytes())


def _slug(value: str) -> str:
    value = re.sub(r"[^A-Za-z0-9_.-]+", "_", value).strip("_")
    return value or "factor"


def _pickle_strings(path: Path) -> set[str]:
    """Extract strings from pickle opcodes without unpickling objects."""
    strings: set[str] = set()
    for op, arg, _ in pickletools.genops(path.read_bytes()):
        if op.name in {
            "UNICODE",
            "BINUNICODE",
            "SHORT_BINUNICODE",
            "BINUNICODE8",
        } and isinstance(arg, str):
            strings.add(arg)
    return strings


def _load_jsonl(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def _event_map(
    rows: list[dict[str, Any]],
    tag: str,
) -> dict[int, dict[str, Any]]:
    out: dict[int, dict[str, Any]] = {}

    for row in rows:
        if row.get("tag") != tag:
            continue

        trial_id = row.get("trial_id")
        if trial_id in {None, "__run__"}:
            continue

        tid = int(trial_id)

        if tid in out:
            raise ArtifactRecoveryError(f"multiple canonical {tag} events for trial {tid}")

        out[tid] = row

    return out


def _index_checkpoints(
    roots: dict[str, Path],
) -> dict[int, list[tuple[str, Path]]]:
    out: dict[int, list[tuple[str, Path]]] = defaultdict(list)

    for label, root in roots.items():
        if not root.exists():
            continue

        for path in root.rglob("1_coding"):
            if not path.is_file():
                continue
            if path.parent.parent.name != "__session__":
                continue
            if not path.parent.name.isdigit():
                continue

            out[int(path.parent.name)].append((label, path))

    return out


def _checkpoint_ref(
    label: str,
    path: Path,
    root: Path,
) -> str:
    try:
        relative = path.relative_to(root)
    except ValueError as exc:
        raise ArtifactRecoveryError(f"checkpoint is outside declared root: {path}") from exc

    return f"{label}/{relative.as_posix()}"


def _runner_success_names(
    runner_payload: dict[str, Any] | None,
) -> set[str]:
    if not runner_payload:
        return set()

    state = runner_payload.get("factor_state") or {}
    current = state.get("current_successful") or []

    return {str(item["name"]) for item in current if isinstance(item, dict) and item.get("name")}


def _cumulative_runner_factors(
    runner_payload: dict[str, Any] | None,
) -> list[dict[str, str]]:
    if not runner_payload:
        return []

    state = runner_payload.get("factor_state") or {}
    cumulative = state.get("cumulative_successful") or []

    out = []

    for item in cumulative:
        if not isinstance(item, dict) or not item.get("name"):
            raise ArtifactRecoveryError("runner cumulative factor lacks a usable name")

        out.append(
            {
                "name": str(item["name"]),
                "formulation": str(item.get("formulation") or ""),
            }
        )

    return out


def recover_rdagent_artifacts(
    *,
    logical_events: Path,
    out_dir: Path,
    checkpoint_roots: dict[str, Path],
) -> dict[str, Any]:
    if out_dir.exists() and any(out_dir.iterdir()):
        raise ArtifactRecoveryError(f"output directory is not empty: {out_dir}")

    out_dir.mkdir(parents=True, exist_ok=True)

    rows = _load_jsonl(logical_events)

    coders = _event_map(rows, "coder_result")
    runners = _event_map(rows, "runner_result")

    trial_ids = sorted({int(row["trial_id"]) for row in rows if row.get("trial_id") not in {None, "__run__"}})

    checkpoints = _index_checkpoints(checkpoint_roots)

    checkpoint_string_cache: dict[Path, set[str]] = {}
    trial_records = []
    all_artifacts: list[dict[str, Any]] = []

    for tid in trial_ids:
        coder_event = coders.get(tid)
        runner_event = runners.get(tid)

        record: dict[str, Any] = {
            "trial_id": tid,
            "coder_result_observed": coder_event is not None,
            "runner_result_observed": runner_event is not None,
            "artifact_count": 0,
            "runner_current_successful_count": 0,
            "checkpoint_exact_match": False,
            "checkpoint": None,
            "artifacts": [],
        }

        if coder_event is None:
            if runner_event is not None:
                raise ArtifactRecoveryError(f"trial {tid}: runner exists without coder result")
            trial_records.append(record)
            continue

        payload = coder_event.get("payload") or {}
        tasks = payload.get("sub_tasks") or []
        workspaces = payload.get("sub_workspace_list") or []

        if len(tasks) != len(workspaces):
            raise ArtifactRecoveryError(
                f"trial {tid}: tasks/workspaces length mismatch: {len(tasks)} != {len(workspaces)}"
            )

        success_names = _runner_success_names((runner_event or {}).get("payload"))

        artifact_sources: list[str] = []
        artifacts = []

        for slot, (task, workspace) in enumerate(zip(tasks, workspaces, strict=True)):
            if not isinstance(task, dict):
                raise ArtifactRecoveryError(f"trial {tid} slot {slot}: task is not a dict")
            if not isinstance(workspace, dict):
                raise ArtifactRecoveryError(f"trial {tid} slot {slot}: workspace is not a dict")

            name = str(task.get("factor_name") or task.get("name") or f"factor_{slot}")

            workspace_path = workspace.get("workspace_path")
            if not isinstance(workspace_path, str):
                raise ArtifactRecoveryError(f"trial {tid} slot {slot}: missing workspace_path")

            source_file = Path(workspace_path) / "factor.py"

            if not source_file.is_file():
                raise ArtifactRecoveryError(
                    f"trial {tid} slot {slot}: factor.py missing from referenced workspace"
                )

            source_bytes = source_file.read_bytes()

            try:
                source_text = source_bytes.decode("utf-8")
            except UnicodeDecodeError as exc:
                raise ArtifactRecoveryError(f"trial {tid} slot {slot}: factor.py is not UTF-8") from exc

            source_sha = _sha256_bytes(source_bytes)
            artifact_sources.append(source_text)

            factor_dir = out_dir / "trials" / f"trial_{tid:02d}" / f"slot_{slot:02d}__{_slug(name)}"
            factor_dir.mkdir(parents=True, exist_ok=True)

            target = factor_dir / "factor.py"
            shutil.copyfile(source_file, target)

            if _sha256_file(target) != source_sha:
                raise ArtifactRecoveryError(f"trial {tid} slot {slot}: copy hash mismatch")

            target.chmod(0o444)

            artifact_id = f"trial-{tid:02d}-slot-{slot:02d}-{source_sha[:12]}"

            artifact = {
                "artifact_id": artifact_id,
                "trial_id": tid,
                "slot": slot,
                "name": name,
                "formulation": str(task.get("factor_formulation") or ""),
                "factor_implementation": task.get("factor_implementation"),
                "runner_current_successful": name in success_names,
                "workspace_id": Path(workspace_path).name,
                "relative_path": target.relative_to(out_dir).as_posix(),
                "sha256": source_sha,
                "bytes": len(source_bytes),
            }

            artifacts.append(artifact)
            all_artifacts.append(artifact)

        missing_success = success_names - {item["name"] for item in artifacts}

        if missing_success:
            raise ArtifactRecoveryError(
                f"trial {tid}: runner-success factors have no recovered artifact: {sorted(missing_success)}"
            )

        candidates = checkpoints.get(tid, [])
        exact_candidates: list[tuple[str, Path]] = []

        for label, checkpoint in candidates:
            if checkpoint not in checkpoint_string_cache:
                checkpoint_string_cache[checkpoint] = _pickle_strings(checkpoint)

            strings = checkpoint_string_cache[checkpoint]

            if all(source in strings for source in artifact_sources):
                exact_candidates.append((label, checkpoint))

        if artifacts and not exact_candidates:
            raise ArtifactRecoveryError(
                f"trial {tid}: no coding checkpoint contains all recovered factor.py sources exactly"
            )

        selected_checkpoint = None

        if exact_candidates:
            label, checkpoint = max(
                exact_candidates,
                key=lambda item: (
                    item[1].stat().st_mtime_ns,
                    str(item[1]),
                ),
            )

            selected_checkpoint = {
                "ref": _checkpoint_ref(
                    label,
                    checkpoint,
                    checkpoint_roots[label],
                ),
                "sha256": _sha256_file(checkpoint),
                "bytes": checkpoint.stat().st_size,
                "matching_checkpoint_count": len(exact_candidates),
                "inspection_method": ("pickletools-opcode-string-scan-no-unpickle"),
            }

        record.update(
            {
                "artifact_count": len(artifacts),
                "runner_current_successful_count": sum(
                    bool(item["runner_current_successful"]) for item in artifacts
                ),
                "checkpoint_exact_match": bool(exact_candidates),
                "checkpoint": selected_checkpoint,
                "artifacts": artifacts,
            }
        )

        trial_records.append(record)

    # Resolve observed cumulative runner libraries back to immutable artifacts.
    name_index: dict[str, list[dict[str, Any]]] = defaultdict(list)

    for artifact in all_artifacts:
        name_index[artifact["name"]].append(artifact)

    library_states = []

    for tid in sorted(runners):
        payload = runners[tid].get("payload") or {}
        cumulative = _cumulative_runner_factors(payload)

        resolved = []

        for factor in cumulative:
            candidates = [
                item
                for item in name_index.get(factor["name"], [])
                if int(item["trial_id"]) <= tid and bool(item["runner_current_successful"])
            ]

            if len(candidates) != 1:
                raise ArtifactRecoveryError(
                    f"trial {tid}: cumulative factor "
                    f"{factor['name']!r} resolves to "
                    f"{len(candidates)} accepted artifacts"
                )

            artifact = candidates[0]

            resolved.append(
                {
                    "name": factor["name"],
                    "formulation": factor["formulation"],
                    "artifact_id": artifact["artifact_id"],
                    "source_trial_id": artifact["trial_id"],
                    "sha256": artifact["sha256"],
                    "relative_path": artifact["relative_path"],
                }
            )

        library_states.append(
            {
                "trial_id": tid,
                "factor_count": len(resolved),
                "factors": resolved,
            }
        )

    tree_entries = sorted(
        (
            item["relative_path"],
            item["sha256"],
        )
        for item in all_artifacts
    )

    tree_payload = "\n".join(f"{sha}  {path}" for path, sha in tree_entries).encode()

    artifact_tree_sha256 = _sha256_bytes(tree_payload)

    final_library = library_states[-1] if library_states else None

    manifest: dict[str, Any] = {
        "schema": SCHEMA,
        "source_event_schema": ("agent-alpha-audit.reconciliation.v2"),
        "recovery_policy": {
            "artifact_source": ("factor.py from workspace_path captured in canonical coder_result"),
            "checkpoint_validation": (
                "exact source string must occur in a coding "
                "checkpoint parsed with pickletools; "
                "checkpoint is never unpickled"
            ),
            "runner_acceptance_source": ("runner_result.factor_state.current_successful"),
            "cumulative_library_source": ("runner_result.factor_state.cumulative_successful"),
        },
        "summary": {
            "logical_trial_count": len(trial_ids),
            "coder_trial_count": len(coders),
            "runner_trial_count": len(runners),
            "recovered_artifact_count": len(all_artifacts),
            "checkpoint_exact_artifact_count": sum(
                item["artifact_count"] for item in trial_records if item["checkpoint_exact_match"]
            ),
            "runner_current_successful_artifact_count": sum(
                bool(item["runner_current_successful"]) for item in all_artifacts
            ),
            "not_runner_current_successful_artifact_count": sum(
                not bool(item["runner_current_successful"]) for item in all_artifacts
            ),
            "observed_cumulative_library_state_count": len(library_states),
            "final_cumulative_library_factor_count": (final_library["factor_count"] if final_library else 0),
        },
        "artifact_tree_sha256": artifact_tree_sha256,
        "trial_records": trial_records,
        "observed_cumulative_library_states": library_states,
        "final_observed_cumulative_library": final_library,
    }

    manifest_path = out_dir / "manifest.json"
    manifest_path.write_text(
        json.dumps(
            manifest,
            indent=2,
            sort_keys=True,
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )
    manifest_path.chmod(0o444)

    return manifest


def _parse_checkpoint_roots(
    values: list[str],
) -> dict[str, Path]:
    roots = {}

    for value in values:
        if "=" not in value:
            raise ArtifactRecoveryError("--checkpoint-root must be LABEL=PATH")

        label, raw_path = value.split("=", 1)

        if not label:
            raise ArtifactRecoveryError("checkpoint root label cannot be empty")

        if label in roots:
            raise ArtifactRecoveryError(f"duplicate checkpoint root label: {label}")

        roots[label] = Path(raw_path)

    if not roots:
        raise ArtifactRecoveryError("at least one checkpoint root is required")

    return roots


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--logical-events",
        type=Path,
        required=True,
    )
    parser.add_argument(
        "--out-dir",
        type=Path,
        required=True,
    )
    parser.add_argument(
        "--checkpoint-root",
        action="append",
        default=[],
        metavar="LABEL=PATH",
    )
    args = parser.parse_args()

    manifest = recover_rdagent_artifacts(
        logical_events=args.logical_events,
        out_dir=args.out_dir,
        checkpoint_roots=_parse_checkpoint_roots(args.checkpoint_root),
    )

    print(
        json.dumps(
            {
                "schema": manifest["schema"],
                **manifest["summary"],
                "artifact_tree_sha256": manifest["artifact_tree_sha256"],
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
