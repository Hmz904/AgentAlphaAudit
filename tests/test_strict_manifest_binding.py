from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from agent_alpha_audit.strict_manifest_binding import (
    StrictManifestBindingError,
    bind_strict_eval_manifest_v4,
)


def _canonical_sha(value) -> str:
    return hashlib.sha256(
        json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
    ).hexdigest()


def _file_sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _build_fixture(tmp_path: Path):
    artifact_root = tmp_path / "artifact_recovery_v1"
    factor = artifact_root / "trials" / "trial_00" / "slot_00__A" / "factor.py"
    factor.parent.mkdir(parents=True)
    factor.write_text("def A():\n    return 1\n")

    factor_sha = _file_sha(factor)

    recovery = {
        "schema": ("agent-alpha-audit.artifact-recovery.v1"),
        "artifact_tree_sha256": "tree-sha",
    }

    recovery_path = artifact_root / "manifest.json"
    recovery_path.write_text(json.dumps(recovery))
    recovery_file_sha = _file_sha(recovery_path)

    spec = {
        "schema": ("agent-alpha-audit.rdagent-evaluation-spec.v1"),
        "evidence": {
            "artifact_recovery": {
                "manifest_sha256": recovery_file_sha,
                "artifact_tree_sha256": "tree-sha",
            }
        },
    }
    spec["spec_sha256"] = _canonical_sha(spec)

    spec_path = tmp_path / "spec.json"
    spec_path.write_text(json.dumps(spec))
    spec_file_sha = _file_sha(spec_path)

    artifact_ref = {
        "name": "A",
        "source_trial_id": 0,
        "sha256": factor_sha,
        "relative_path": ("trials/trial_00/slot_00__A/factor.py"),
    }

    composition_sha = _canonical_sha(
        [
            {
                "name": "A",
                "source_trial_id": 0,
                "sha256": factor_sha,
                "relative_path": artifact_ref["relative_path"],
            }
        ]
    )

    binding = {
        "schema": ("agent-alpha-audit.composition-binding.v1"),
        "source_evidence": {
            "artifact_recovery_manifest_sha256": (recovery_file_sha),
            "artifact_tree_sha256": "tree-sha",
            "evaluation_spec_file_sha256": (spec_file_sha),
            "evaluation_spec_sha256": (spec["spec_sha256"]),
        },
        "trial_experiments": [
            {
                "trial_id": 0,
                "runner_result_observed": True,
                "composition_bound": True,
                "composition_sha256": composition_sha,
                "artifacts": [artifact_ref],
            },
            {
                "trial_id": 1,
                "runner_result_observed": False,
                "composition_bound": False,
                "composition_sha256": None,
                "artifacts": [],
            },
        ],
        "cumulative_libraries": [
            {
                "trial_id": 0,
                "composition_bound": True,
                "factor_count": 1,
                "composition_sha256": composition_sha,
                "artifacts": [artifact_ref],
            }
        ],
    }
    binding["binding_sha256"] = _canonical_sha(binding)

    binding_path = tmp_path / "binding.json"
    binding_path.write_text(json.dumps(binding))

    trial0 = {
        "run_id": "run",
        "trial_id": "0",
        "evaluation_unit": "trial_experiment",
        "captured": True,
        "has_factor_representation": True,
        "coder_result_observed": True,
        "runner_result_observed": True,
        "implementation_artifact_present": False,
        "evaluation_spec_present": False,
        "strict_replay_ready": False,
        "evaluable": False,
    }

    trial1 = {
        "run_id": "run",
        "trial_id": "1",
        "evaluation_unit": "trial_experiment",
        "captured": True,
        "has_factor_representation": True,
        "coder_result_observed": True,
        "runner_result_observed": False,
        "implementation_artifact_present": False,
        "evaluation_spec_present": False,
        "strict_replay_ready": False,
        "evaluable": False,
    }

    cumulative0 = {
        "run_id": "run",
        "loop_k": "0",
        "evaluation_unit": ("cumulative_factor_library_at_loop_k"),
        "factor_count": 1,
        "runner_snapshot_observed": True,
        "state_observed": True,
        "cumulative_state_source": ("runner_successful_factor_state"),
        "strict_replay_ready": False,
        "evaluable": False,
    }

    cumulative1 = {
        "run_id": "run",
        "loop_k": "1",
        "evaluation_unit": ("cumulative_factor_library_at_loop_k"),
        "factor_count": 1,
        "runner_snapshot_observed": False,
        "state_observed": True,
        "cumulative_state_source": ("carried_forward_last_runner_state"),
        "strict_replay_ready": False,
        "evaluable": False,
    }

    v3 = {
        "schema": ("agent-alpha-audit.strict-eval-manifest.v3"),
        "run_id": "run",
        "search_unit": "trial_experiment",
        "primary_outcome_unit": ("cumulative_factor_library_at_loop_k"),
        "raw_trials_lower_bound": 2,
        "captured_trial_count": 2,
        "trial_factor_representation_count": 2,
        "strict_replay_ready_trial_count": 0,
        "observed_runner_snapshot_count": 1,
        "strict_replay_ready_cumulative_count": 0,
        "trial_items": [trial0, trial1],
        "items": [trial0, trial1],
        "cumulative_library_items": [
            cumulative0,
            cumulative1,
        ],
        "primary_final_library": cumulative0,
        "primary_final_library_loop_k": "0",
    }

    v3_path = tmp_path / "v3.json"
    v3_path.write_text(json.dumps(v3))

    return {
        "v3": v3_path,
        "recovery": recovery_path,
        "spec": spec_path,
        "binding": binding_path,
        "factor": factor,
    }


def test_v4_readiness_requires_observed_bound_composition(
    tmp_path: Path,
) -> None:
    f = _build_fixture(tmp_path)

    result = bind_strict_eval_manifest_v4(
        manifest_v3_path=f["v3"],
        artifact_manifest_path=f["recovery"],
        evaluation_spec_path=f["spec"],
        composition_binding_path=f["binding"],
        out_path=tmp_path / "v4.json",
    )

    assert result["strict_replay_ready_trial_count"] == 1
    assert result["strict_replay_ready_cumulative_count"] == 1

    assert result["trial_items"][0]["strict_replay_ready"] is True
    assert result["trial_items"][1]["strict_replay_ready"] is False

    assert result["cumulative_library_items"][0]["strict_replay_ready"] is True
    assert result["cumulative_library_items"][1]["strict_replay_ready"] is False

    assert result["primary_final_library"]["strict_replay_ready"] is True


def test_v4_rejects_tampered_artifact_bytes(
    tmp_path: Path,
) -> None:
    f = _build_fixture(tmp_path)

    f["factor"].write_text("def A():\n    return 999\n")

    with pytest.raises(
        StrictManifestBindingError,
        match="artifact hash mismatch",
    ):
        bind_strict_eval_manifest_v4(
            manifest_v3_path=f["v3"],
            artifact_manifest_path=f["recovery"],
            evaluation_spec_path=f["spec"],
            composition_binding_path=f["binding"],
            out_path=tmp_path / "v4.json",
        )


def test_v4_rejects_evaluation_spec_drift(
    tmp_path: Path,
) -> None:
    f = _build_fixture(tmp_path)

    binding = json.loads(f["binding"].read_text())

    binding["source_evidence"]["evaluation_spec_sha256"] = "wrong"

    binding["binding_sha256"] = _canonical_sha({k: v for k, v in binding.items() if k != "binding_sha256"})

    f["binding"].write_text(json.dumps(binding))

    with pytest.raises(
        StrictManifestBindingError,
        match="semantic hash drift",
    ):
        bind_strict_eval_manifest_v4(
            manifest_v3_path=f["v3"],
            artifact_manifest_path=f["recovery"],
            evaluation_spec_path=f["spec"],
            composition_binding_path=f["binding"],
            out_path=tmp_path / "v4.json",
        )
