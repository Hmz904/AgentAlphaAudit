from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path
from typing import Any

SCHEMA = "agent-alpha-audit.strict-eval-manifest.v4"


class StrictManifestBindingError(ValueError):
    pass


def _load(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _canonical_sha256(value: Any) -> str:
    payload = json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _verify_self_hash(
    document: dict[str, Any],
    field: str,
) -> str:
    observed = document.get(field)

    if not observed:
        raise StrictManifestBindingError(f"missing internal hash field {field}")

    payload = copy.deepcopy(document)
    payload.pop(field, None)

    expected = _canonical_sha256(payload)

    if observed != expected:
        raise StrictManifestBindingError(f"{field} verification failed")

    return str(observed)


def _tid(value: Any) -> str:
    return str(value)


def _composition_sha256(
    artifacts: list[dict[str, Any]],
) -> str:
    identity = [
        {
            "name": item["name"],
            "source_trial_id": item["source_trial_id"],
            "sha256": item["sha256"],
            "relative_path": item["relative_path"],
        }
        for item in artifacts
    ]

    return _canonical_sha256(identity)


def _verify_artifact_ref(
    *,
    ref: dict[str, Any],
    artifact_root: Path,
) -> dict[str, Any]:
    required = {
        "name",
        "source_trial_id",
        "sha256",
        "relative_path",
    }

    missing = required - set(ref)

    if missing:
        raise StrictManifestBindingError(f"artifact ref missing fields: {sorted(missing)}")

    relative = Path(str(ref["relative_path"]))

    if relative.is_absolute():
        raise StrictManifestBindingError("artifact relative_path is absolute")

    root = artifact_root.resolve()
    target = (root / relative).resolve()

    try:
        target.relative_to(root)
    except ValueError as exc:
        raise StrictManifestBindingError("artifact relative_path escapes bundle root") from exc

    if not target.is_file():
        raise StrictManifestBindingError(f"artifact missing: {relative}")

    observed_sha = _sha256_file(target)

    if observed_sha != str(ref["sha256"]):
        raise StrictManifestBindingError(f"artifact hash mismatch: {relative}")

    out = {
        "name": str(ref["name"]),
        "source_trial_id": ref["source_trial_id"],
        "sha256": str(ref["sha256"]),
        "relative_path": str(relative),
    }

    if ref.get("slot_index") is not None:
        out["slot_index"] = ref["slot_index"]

    return out


def _verified_composition(
    *,
    binding: dict[str, Any],
    artifact_root: Path,
) -> dict[str, Any]:
    if not binding.get("composition_bound"):
        raise StrictManifestBindingError("cannot verify an unbound composition")

    raw = binding.get("artifacts") or []

    if not isinstance(raw, list):
        raise StrictManifestBindingError("composition artifacts must be a list")

    artifacts = [
        _verify_artifact_ref(
            ref=ref,
            artifact_root=artifact_root,
        )
        for ref in raw
    ]

    observed = binding.get("composition_sha256")

    if not observed:
        raise StrictManifestBindingError("composition_sha256 missing")

    expected = _composition_sha256(artifacts)

    if observed != expected:
        raise StrictManifestBindingError("composition hash verification failed")

    return {
        "composition_sha256": str(observed),
        "artifact_count": len(artifacts),
        "artifacts": artifacts,
        "artifact_hashes_verified": True,
    }


def bind_strict_eval_manifest_v4(
    *,
    manifest_v3_path: Path,
    artifact_manifest_path: Path,
    evaluation_spec_path: Path,
    composition_binding_path: Path,
    out_path: Path,
) -> dict[str, Any]:
    v3 = _load(manifest_v3_path)
    recovery = _load(artifact_manifest_path)
    spec = _load(evaluation_spec_path)
    binding = _load(composition_binding_path)

    if v3.get("schema") != ("agent-alpha-audit.strict-eval-manifest.v3"):
        raise StrictManifestBindingError("unexpected source strict manifest schema")

    if recovery.get("schema") != ("agent-alpha-audit.artifact-recovery.v1"):
        raise StrictManifestBindingError("unexpected artifact recovery schema")

    if spec.get("schema") != ("agent-alpha-audit.rdagent-evaluation-spec.v1"):
        raise StrictManifestBindingError("unexpected evaluation spec schema")

    if binding.get("schema") != ("agent-alpha-audit.composition-binding.v1"):
        raise StrictManifestBindingError("unexpected composition binding schema")

    spec_sha = _verify_self_hash(
        spec,
        "spec_sha256",
    )
    binding_sha = _verify_self_hash(
        binding,
        "binding_sha256",
    )

    artifact_manifest_file_sha = _sha256_file(artifact_manifest_path)
    evaluation_spec_file_sha = _sha256_file(evaluation_spec_path)
    composition_binding_file_sha = _sha256_file(composition_binding_path)
    manifest_v3_file_sha = _sha256_file(manifest_v3_path)

    source = binding.get("source_evidence") or {}

    if source.get("artifact_recovery_manifest_sha256") != artifact_manifest_file_sha:
        raise StrictManifestBindingError(
            "composition binding points to a different artifact recovery manifest"
        )

    if source.get("artifact_tree_sha256") != recovery.get("artifact_tree_sha256"):
        raise StrictManifestBindingError("artifact tree hash drift")

    if source.get("evaluation_spec_file_sha256") != evaluation_spec_file_sha:
        raise StrictManifestBindingError("composition binding points to a different evaluation spec file")

    if source.get("evaluation_spec_sha256") != spec_sha:
        raise StrictManifestBindingError("evaluation spec semantic hash drift")

    spec_artifact = spec.get("evidence", {}).get("artifact_recovery", {})

    if (
        spec_artifact.get("manifest_sha256")
        and spec_artifact["manifest_sha256"] != artifact_manifest_file_sha
    ):
        raise StrictManifestBindingError("evaluation spec points to a different artifact recovery manifest")

    if spec_artifact.get("artifact_tree_sha256") and spec_artifact["artifact_tree_sha256"] != recovery.get(
        "artifact_tree_sha256"
    ):
        raise StrictManifestBindingError("evaluation spec artifact tree hash drift")

    artifact_root = artifact_manifest_path.parent

    trial_binding_rows = binding.get("trial_experiments") or []
    cumulative_binding_rows = binding.get("cumulative_libraries") or []

    trial_bindings = {_tid(item["trial_id"]): item for item in trial_binding_rows}

    cumulative_bindings = {_tid(item["trial_id"]): item for item in cumulative_binding_rows}

    if len(trial_bindings) != len(trial_binding_rows):
        raise StrictManifestBindingError("duplicate trial composition binding")

    if len(cumulative_bindings) != len(cumulative_binding_rows):
        raise StrictManifestBindingError("duplicate cumulative composition binding")

    evaluation_spec_ref = {
        "schema": spec["schema"],
        "spec_sha256": spec_sha,
        "file_sha256": evaluation_spec_file_sha,
        "verified": True,
    }

    composition_binding_ref = {
        "schema": binding["schema"],
        "binding_sha256": binding_sha,
        "file_sha256": composition_binding_file_sha,
        "verified": True,
    }

    trial_items: list[dict[str, Any]] = []

    for source_item in v3.get(
        "trial_items",
        v3.get("items", []),
    ):
        item = copy.deepcopy(source_item)
        trial_id = _tid(item["trial_id"])

        comp = trial_bindings.get(trial_id)

        if comp is None:
            raise StrictManifestBindingError(f"trial {trial_id} missing from composition binding")

        runner_observed = bool(item.get("runner_result_observed"))

        if runner_observed != bool(comp.get("runner_result_observed")):
            raise StrictManifestBindingError(f"trial {trial_id}: runner observation drift")

        implementation = None

        if comp.get("composition_bound"):
            implementation = _verified_composition(
                binding=comp,
                artifact_root=artifact_root,
            )

        implementation_present = bool(implementation and implementation["artifact_count"] > 0)

        ready = bool(
            runner_observed
            and implementation_present
            and evaluation_spec_ref["verified"]
            and composition_binding_ref["verified"]
        )

        if ready:
            reason = None
        elif not runner_observed:
            reason = "no canonical runner result; trial composition is not observed"
        elif not implementation_present:
            reason = "runner-observed trial has no verified nonempty implementation composition"
        else:
            reason = "evaluation evidence binding incomplete"

        item.update(
            {
                "implementation_artifact": implementation,
                "implementation_artifact_present": (implementation_present),
                "evaluation_spec": evaluation_spec_ref,
                "evaluation_spec_present": True,
                "evaluation_spec_verified": True,
                "composition_binding": (composition_binding_ref),
                "composition_binding_present": True,
                "strict_replay_ready": ready,
                "evaluable": ready,
                "reason_if_not_evaluable": reason,
            }
        )

        trial_items.append(item)

    cumulative_items: list[dict[str, Any]] = []

    for source_item in v3.get(
        "cumulative_library_items",
        [],
    ):
        item = copy.deepcopy(source_item)
        loop_k = _tid(item["loop_k"])
        observed = bool(item.get("runner_snapshot_observed"))

        comp = cumulative_bindings.get(loop_k)

        if observed and comp is None:
            raise StrictManifestBindingError(
                f"loop {loop_k}: observed runner snapshot has no composition binding"
            )

        if not observed and comp is not None:
            raise StrictManifestBindingError(
                f"loop {loop_k}: composition binding exists for a non-observed carried-forward state"
            )

        implementation = None

        if comp is not None:
            implementation = _verified_composition(
                binding=comp,
                artifact_root=artifact_root,
            )

            if int(item["factor_count"]) != int(implementation["artifact_count"]):
                raise StrictManifestBindingError(f"loop {loop_k}: factor count drift")

        implementation_present = bool(implementation and implementation["artifact_count"] > 0)

        ready = bool(
            observed
            and implementation_present
            and evaluation_spec_ref["verified"]
            and composition_binding_ref["verified"]
        )

        if ready:
            reason = None
        elif not observed:
            reason = (
                "no runner snapshot observed at this loop; "
                "carried-forward state retained for chronology "
                "but not counted as an independently observed "
                "strict replay unit"
            )
        elif not implementation_present:
            reason = "observed cumulative state lacks a verified nonempty artifact composition"
        else:
            reason = "evaluation evidence binding incomplete"

        item.update(
            {
                "implementation_artifact": implementation,
                "implementation_artifact_present": (implementation_present),
                "evaluation_spec": evaluation_spec_ref,
                "evaluation_spec_present": True,
                "evaluation_spec_verified": True,
                "composition_binding": (composition_binding_ref),
                "composition_binding_present": True,
                "strict_replay_ready": ready,
                "evaluable": ready,
                "reason_if_not_evaluable": reason,
            }
        )

        cumulative_items.append(item)

    ready_trials = sum(bool(item["strict_replay_ready"]) for item in trial_items)
    ready_cumulative = sum(bool(item["strict_replay_ready"]) for item in cumulative_items)

    observed_runner_snapshots = sum(bool(item.get("runner_snapshot_observed")) for item in cumulative_items)

    if observed_runner_snapshots != len(cumulative_bindings):
        raise StrictManifestBindingError(
            "observed runner snapshot count does not match cumulative composition binding count"
        )

    if (
        int(
            v3.get(
                "observed_runner_snapshot_count",
                observed_runner_snapshots,
            )
        )
        != observed_runner_snapshots
    ):
        raise StrictManifestBindingError("v3 observed runner snapshot count drift")

    primary_loop = v3.get("primary_final_library_loop_k")

    primary_matches = [item for item in cumulative_items if _tid(item["loop_k"]) == _tid(primary_loop)]

    if len(primary_matches) != 1:
        raise StrictManifestBindingError("primary final library loop is ambiguous")

    primary = primary_matches[0]

    if not primary["runner_snapshot_observed"]:
        raise StrictManifestBindingError("primary final library is not an observed runner snapshot")

    if not primary["strict_replay_ready"]:
        raise StrictManifestBindingError("primary final library failed strict binding")

    result: dict[str, Any] = {
        "schema": SCHEMA,
        "source_manifest_schema": v3["schema"],
        "status": "STRICT_REPLAY_BINDINGS_VERIFIED",
        "run_id": v3["run_id"],
        "search_unit": v3["search_unit"],
        "primary_outcome_unit": v3["primary_outcome_unit"],
        "policy": (
            "All captured trials remain search-accounting "
            "targets. Strict replay readiness requires an "
            "observed canonical runner composition, verified "
            "immutable artifact bytes, a hash-verified global "
            "evaluation specification, and a hash-verified "
            "composition binding. Carried-forward cumulative "
            "states remain in the loop chronology but are not "
            "counted as independently observed replay units."
        ),
        "evidence": {
            "source_manifest_v3_file_sha256": (manifest_v3_file_sha),
            "artifact_recovery": {
                "schema": recovery["schema"],
                "manifest_file_sha256": (artifact_manifest_file_sha),
                "artifact_tree_sha256": recovery["artifact_tree_sha256"],
            },
            "evaluation_spec": evaluation_spec_ref,
            "composition_binding": (composition_binding_ref),
        },
        "raw_trials_lower_bound": v3["raw_trials_lower_bound"],
        "captured_trial_count": v3["captured_trial_count"],
        "trial_factor_representation_count": v3["trial_factor_representation_count"],
        "strict_replay_ready_trial_count": (ready_trials),
        "observed_runner_snapshot_count": (observed_runner_snapshots),
        "strict_replay_ready_cumulative_count": (ready_cumulative),
        "trial_items": trial_items,
        "cumulative_library_items": cumulative_items,
        "primary_final_library": primary,
        "primary_final_library_loop_k": primary["loop_k"],
        "items": trial_items,
    }

    result["manifest_sha256"] = _canonical_sha256(result)

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
        raise StrictManifestBindingError("v4 manifest leaks an absolute home path")

    out_path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )
    out_path.write_text(
        serialized,
        encoding="utf-8",
    )

    return result
