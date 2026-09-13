from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

SCHEMA = "agent-alpha-audit.composition-binding.v1"


class CompositionBindingError(ValueError):
    pass


def _load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _load_jsonl(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def _sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _canonical_sha256(value: Any) -> str:
    data = json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")
    return hashlib.sha256(data).hexdigest()


def _tid(value: Any) -> str:
    return str(value)


def _public_tid(value: Any) -> int | str:
    text = str(value)
    return int(text) if text.isdigit() else text


def _sort_tid(value: Any) -> tuple[bool, int | str]:
    text = str(value)
    return (
        not text.isdigit(),
        int(text) if text.isdigit() else text,
    )


def _factor_name(value: Any) -> str:
    if isinstance(value, str):
        return value

    if not isinstance(value, dict):
        raise CompositionBindingError(f"factor representation is not a dict/string: {type(value)!r}")

    for key in ("factor_name", "name"):
        name = value.get(key)
        if name:
            return str(name)

    nested = value.get("factor")
    if isinstance(nested, dict):
        for key in ("factor_name", "name"):
            name = nested.get(key)
            if name:
                return str(name)

    raise CompositionBindingError(f"factor name unavailable; keys={sorted(value)}")


def _factor_names(values: Any) -> list[str]:
    if values is None:
        return []

    if not isinstance(values, list):
        raise CompositionBindingError("runner factor state must be a list")

    return [_factor_name(value) for value in values]


def _artifact_ref(
    artifact: dict[str, Any],
    *,
    default_trial_id: Any,
) -> dict[str, Any]:
    name = _factor_name(artifact)

    sha256 = artifact.get("sha256")
    relative_path = artifact.get("relative_path")

    if not sha256:
        raise CompositionBindingError(f"artifact {name!r} missing sha256")

    if not relative_path:
        raise CompositionBindingError(f"artifact {name!r} missing relative_path")

    source_trial_id = artifact.get(
        "source_trial_id",
        default_trial_id,
    )

    ref: dict[str, Any] = {
        "name": name,
        "source_trial_id": _public_tid(source_trial_id),
        "sha256": str(sha256),
        "relative_path": str(relative_path),
    }

    slot = artifact.get(
        "slot_index",
        artifact.get("slot"),
    )

    if slot is not None:
        ref["slot_index"] = slot

    return ref


def _runner_events(
    rows: list[dict[str, Any]],
) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}

    for row in rows:
        if row.get("tag") != "runner_result":
            continue

        trial_id = _tid(row.get("trial_id"))

        if trial_id in out:
            raise CompositionBindingError(f"multiple canonical runner_result events for trial {trial_id}")

        out[trial_id] = row.get("payload") or {}

    return out


def _coder_trials(
    rows: list[dict[str, Any]],
) -> set[str]:
    return {_tid(row.get("trial_id")) for row in rows if row.get("tag") == "coder_result"}


def _resolve_current_factor(
    *,
    name: str,
    trial_artifacts: list[dict[str, Any]],
    trial_id: str,
) -> dict[str, Any]:
    matches = [ref for ref in trial_artifacts if ref["name"] == name]

    if len(matches) != 1:
        raise CompositionBindingError(
            f"trial {trial_id}: current-success factor {name!r} resolves to {len(matches)} artifacts"
        )

    return matches[0]


def _resolve_cumulative_factor(
    *,
    factor: dict[str, Any],
    all_artifacts: list[dict[str, Any]],
    trial_id: str,
) -> dict[str, Any]:
    name = _factor_name(factor)

    matches = [ref for ref in all_artifacts if ref["name"] == name]

    if factor.get("source_trial_id") is not None:
        source = _tid(factor["source_trial_id"])
        matches = [ref for ref in matches if _tid(ref["source_trial_id"]) == source]

    if factor.get("sha256"):
        sha = str(factor["sha256"])
        matches = [ref for ref in matches if ref["sha256"] == sha]

    if factor.get("relative_path"):
        path = str(factor["relative_path"])
        matches = [ref for ref in matches if ref["relative_path"] == path]

    if len(matches) != 1:
        raise CompositionBindingError(
            f"trial {trial_id}: cumulative factor {name!r} resolves to {len(matches)} artifacts"
        )

    return matches[0]


def _composition_sha256(
    artifacts: list[dict[str, Any]],
) -> str:
    identity = [
        {
            "name": ref["name"],
            "source_trial_id": ref["source_trial_id"],
            "sha256": ref["sha256"],
            "relative_path": ref["relative_path"],
        }
        for ref in artifacts
    ]
    return _canonical_sha256(identity)


def build_composition_binding(
    *,
    logical_events: Path,
    artifact_manifest: Path,
    evaluation_spec: Path,
    out_path: Path,
) -> dict[str, Any]:
    rows = _load_jsonl(logical_events)
    recovery = _load_json(artifact_manifest)
    spec = _load_json(evaluation_spec)

    if recovery.get("schema") != ("agent-alpha-audit.artifact-recovery.v1"):
        raise CompositionBindingError("unexpected artifact recovery schema")

    if spec.get("schema") != ("agent-alpha-audit.rdagent-evaluation-spec.v1"):
        raise CompositionBindingError("unexpected evaluation-spec schema")

    trial_records = recovery.get("trial_records")
    cumulative_states = recovery.get("observed_cumulative_library_states")
    final_state = recovery.get("final_observed_cumulative_library")

    if not isinstance(trial_records, list):
        raise CompositionBindingError("trial_records missing")

    if not isinstance(cumulative_states, list):
        raise CompositionBindingError("observed cumulative states missing")

    if not isinstance(final_state, dict):
        raise CompositionBindingError("final cumulative state missing")

    runners = _runner_events(rows)
    coder_trials = _coder_trials(rows)

    records_by_trial: dict[str, dict[str, Any]] = {}
    artifacts_by_trial: dict[
        str,
        list[dict[str, Any]],
    ] = {}

    all_artifacts: list[dict[str, Any]] = []

    for record in trial_records:
        trial_id = _tid(record.get("trial_id"))

        if trial_id in records_by_trial:
            raise CompositionBindingError(f"duplicate recovery trial record {trial_id}")

        records_by_trial[trial_id] = record

        raw_artifacts = record.get("artifacts") or []

        if not isinstance(raw_artifacts, list):
            raise CompositionBindingError(f"trial {trial_id}: artifacts is not a list")

        refs = [
            _artifact_ref(
                artifact,
                default_trial_id=trial_id,
            )
            for artifact in raw_artifacts
        ]

        artifacts_by_trial[trial_id] = refs
        all_artifacts.extend(refs)

    expected_recovered = (recovery.get("summary") or {}).get("recovered_artifact_count")

    if expected_recovered is not None and len(all_artifacts) != int(expected_recovered):
        raise CompositionBindingError(
            f"recovered artifact count mismatch: {len(all_artifacts)} != {expected_recovered}"
        )

    # Immutable identities must themselves be unique.
    identities = [
        (
            _tid(ref["source_trial_id"]),
            ref["name"],
            ref["sha256"],
            ref["relative_path"],
        )
        for ref in all_artifacts
    ]

    if len(identities) != len(set(identities)):
        raise CompositionBindingError("duplicate immutable artifact identity")

    trial_bindings: list[dict[str, Any]] = []

    for trial_id in sorted(
        records_by_trial,
        key=_sort_tid,
    ):
        record = records_by_trial[trial_id]
        runner = runners.get(trial_id)

        record_runner_observed = bool(record.get("runner_result_observed"))
        event_runner_observed = runner is not None

        if record_runner_observed != event_runner_observed:
            raise CompositionBindingError(
                f"trial {trial_id}: runner observation disagrees between recovery and logical events"
            )

        coder_observed = bool(record.get("coder_result_observed"))

        if coder_observed != (trial_id in coder_trials):
            raise CompositionBindingError(
                f"trial {trial_id}: coder observation disagrees between recovery and logical events"
            )

        if runner is None:
            trial_bindings.append(
                {
                    "trial_id": _public_tid(trial_id),
                    "coder_result_observed": coder_observed,
                    "runner_result_observed": False,
                    "composition_bound": False,
                    "reason": "no_canonical_runner_result",
                    "current_successful_count": 0,
                    "artifacts": [],
                    "composition_sha256": None,
                }
            )
            continue

        factor_state = runner.get("factor_state") or {}
        current = factor_state.get("current_successful") or []
        current_names = _factor_names(current)

        refs = [
            _resolve_current_factor(
                name=name,
                trial_artifacts=artifacts_by_trial[trial_id],
                trial_id=trial_id,
            )
            for name in current_names
        ]

        if len({ref["name"] for ref in refs}) != len(refs):
            raise CompositionBindingError(f"trial {trial_id}: duplicate current-success factor name")

        recorded_count = record.get("runner_current_successful_count")

        if recorded_count is not None and int(recorded_count) != len(refs):
            raise CompositionBindingError(f"trial {trial_id}: runner-success count mismatch")

        # If recovery stored explicit acceptance flags,
        # use them as an additional invariant.
        raw_artifacts = record.get("artifacts") or []
        flagged = [
            _factor_name(artifact)
            for artifact in raw_artifacts
            if artifact.get("runner_current_successful") is True
        ]

        if flagged and flagged != current_names and set(flagged) != set(current_names):
            raise CompositionBindingError(
                f"trial {trial_id}: recovery runner flags disagree with runner state"
            )

        trial_bindings.append(
            {
                "trial_id": _public_tid(trial_id),
                "coder_result_observed": coder_observed,
                "runner_result_observed": True,
                "composition_bound": True,
                "reason": None,
                "current_successful_count": len(refs),
                "artifacts": refs,
                "composition_sha256": _composition_sha256(refs),
            }
        )

    cumulative_bindings: list[dict[str, Any]] = []

    for state in cumulative_states:
        trial_id = _tid(state.get("trial_id"))

        if trial_id not in runners:
            raise CompositionBindingError(
                f"cumulative state at trial {trial_id} has no canonical runner_result"
            )

        raw_factors = state.get("factors") or []

        if not isinstance(raw_factors, list):
            raise CompositionBindingError(f"trial {trial_id}: cumulative factors is not a list")

        refs = [
            _resolve_cumulative_factor(
                factor=factor,
                all_artifacts=all_artifacts,
                trial_id=trial_id,
            )
            for factor in raw_factors
        ]

        state_names = [ref["name"] for ref in refs]

        runner_state = runners[trial_id].get("factor_state") or {}
        runner_names = _factor_names(runner_state.get("cumulative_successful") or [])

        if state_names != runner_names:
            raise CompositionBindingError(
                f"trial {trial_id}: recovered cumulative state does not exactly match runner order/state"
            )

        factor_count = int(
            state.get(
                "factor_count",
                len(refs),
            )
        )

        if factor_count != len(refs):
            raise CompositionBindingError(f"trial {trial_id}: cumulative factor count mismatch")

        cumulative_bindings.append(
            {
                "trial_id": _public_tid(trial_id),
                "composition_bound": True,
                "factor_count": len(refs),
                "artifacts": refs,
                "composition_sha256": _composition_sha256(refs),
            }
        )

    if len(cumulative_bindings) != len(runners):
        raise CompositionBindingError("not every observed runner has exactly one cumulative-library binding")

    final_trial = _tid(final_state.get("trial_id"))

    matching_final = [binding for binding in cumulative_bindings if _tid(binding["trial_id"]) == final_trial]

    if len(matching_final) != 1:
        raise CompositionBindingError("final cumulative state does not map to exactly one binding")

    final_binding = matching_final[0]

    final_raw = final_state.get("factors") or []
    final_refs = [
        _resolve_cumulative_factor(
            factor=factor,
            all_artifacts=all_artifacts,
            trial_id=final_trial,
        )
        for factor in final_raw
    ]

    if final_refs != final_binding["artifacts"]:
        raise CompositionBindingError("final cumulative library disagrees with its observed state")

    runner_bound_count = sum(bool(item["composition_bound"]) for item in trial_bindings)

    current_ref_count = sum(item["current_successful_count"] for item in trial_bindings)

    summary = recovery.get("summary") or {}

    expected_runner_trials = int(
        summary.get(
            "runner_trial_count",
            len(runners),
        )
    )
    expected_current = int(
        summary.get(
            "runner_current_successful_artifact_count",
            current_ref_count,
        )
    )
    expected_states = int(
        summary.get(
            "observed_cumulative_library_state_count",
            len(cumulative_bindings),
        )
    )
    expected_final = int(
        summary.get(
            "final_cumulative_library_factor_count",
            final_binding["factor_count"],
        )
    )

    observed_checks = {
        "runner_trials": (runner_bound_count == expected_runner_trials),
        "runner_current_successful_artifacts": (current_ref_count == expected_current),
        "cumulative_states": (len(cumulative_bindings) == expected_states),
        "final_factor_count": (final_binding["factor_count"] == expected_final),
    }

    if not all(observed_checks.values()):
        raise CompositionBindingError(f"summary invariant failure: {observed_checks}")

    result: dict[str, Any] = {
        "schema": SCHEMA,
        "status": "COMPOSITION_BINDING_COMPLETE",
        "source_evidence": {
            "artifact_recovery_schema": recovery["schema"],
            "artifact_recovery_manifest_sha256": (_sha256_file(artifact_manifest)),
            "artifact_tree_sha256": recovery["artifact_tree_sha256"],
            "evaluation_spec_schema": spec["schema"],
            "evaluation_spec_file_sha256": (_sha256_file(evaluation_spec)),
            "evaluation_spec_sha256": spec["spec_sha256"],
        },
        "binding_policy": {
            "trial_experiment_source": ("canonical runner_result.factor_state.current_successful"),
            "cumulative_library_source": ("canonical runner_result.factor_state.cumulative_successful"),
            "artifact_identity": ("source_trial_id + factor name + sha256 + relative_path"),
            "no_runner_policy": ("no composition is invented; trial remains unbound"),
            "coder_only_policy": (
                "recovered implementations not accepted by "
                "runner remain forensic evidence and are not "
                "silently included"
            ),
            "cumulative_policy": (
                "bind each observed runner snapshot exactly; never reconstruct cumulative libraries by union"
            ),
        },
        "summary": {
            "logical_trial_count": len(trial_bindings),
            "trial_experiment_binding_count": (runner_bound_count),
            "trial_experiment_unbound_count": (len(trial_bindings) - runner_bound_count),
            "bound_current_successful_artifact_count": (current_ref_count),
            "cumulative_library_binding_count": len(cumulative_bindings),
            "final_cumulative_library_trial_id": (final_binding["trial_id"]),
            "final_cumulative_library_factor_count": (final_binding["factor_count"]),
        },
        "trial_experiments": trial_bindings,
        "cumulative_libraries": cumulative_bindings,
        "final_cumulative_library": final_binding,
    }

    result["binding_sha256"] = _canonical_sha256(result)

    serialized = (
        json.dumps(
            result,
            indent=2,
            sort_keys=True,
            ensure_ascii=False,
        )
        + "\n"
    )

    if "/home/" in serialized:
        raise CompositionBindingError("composition binding leaks absolute home path")

    out_path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )
    out_path.write_text(
        serialized,
        encoding="utf-8",
    )

    return result
