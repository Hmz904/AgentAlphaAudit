from __future__ import annotations

import json
from pathlib import Path

import pytest

from agent_alpha_audit.composition_binding import (
    CompositionBindingError,
    build_composition_binding,
)


def _artifact(
    name: str,
    trial: int,
    token: str,
) -> dict:
    return {
        "factor_name": name,
        "source_trial_id": trial,
        "sha256": token * 64,
        "relative_path": (f"trials/trial_{trial:02d}/{name}/factor.py"),
        "runner_current_successful": True,
    }


def _runner(
    trial: int,
    current: list[str],
    cumulative: list[str],
) -> dict:
    return {
        "trial_id": trial,
        "tag": "runner_result",
        "payload": {
            "factor_state": {
                "current_successful": [{"name": name} for name in current],
                "cumulative_successful": [{"name": name} for name in cumulative],
            }
        },
    }


def _coder(trial: int) -> dict:
    return {
        "trial_id": trial,
        "tag": "coder_result",
        "payload": {},
    }


def _write_jsonl(
    path: Path,
    rows: list[dict],
) -> None:
    path.write_text(
        "".join(json.dumps(row) + "\n" for row in rows),
        encoding="utf-8",
    )


def _spec(path: Path) -> None:
    path.write_text(
        json.dumps(
            {
                "schema": ("agent-alpha-audit.rdagent-evaluation-spec.v1"),
                "spec_sha256": "spec-sha",
            }
        ),
        encoding="utf-8",
    )


def test_binding_uses_exact_runner_snapshots_not_union(
    tmp_path: Path,
) -> None:
    a = _artifact("A", 0, "a")
    b = _artifact("B", 0, "b")
    c = _artifact("C", 1, "c")

    events = tmp_path / "events.jsonl"

    _write_jsonl(
        events,
        [
            _coder(0),
            _runner(
                0,
                ["A", "B"],
                ["A", "B"],
            ),
            _coder(1),
            _runner(
                1,
                ["C"],
                ["A", "C"],
            ),
        ],
    )

    recovery = {
        "schema": ("agent-alpha-audit.artifact-recovery.v1"),
        "artifact_tree_sha256": "tree-sha",
        "summary": {
            "logical_trial_count": 2,
            "runner_trial_count": 2,
            "recovered_artifact_count": 3,
            "runner_current_successful_artifact_count": 3,
            "observed_cumulative_library_state_count": 2,
            "final_cumulative_library_factor_count": 2,
        },
        "trial_records": [
            {
                "trial_id": 0,
                "coder_result_observed": True,
                "runner_result_observed": True,
                "runner_current_successful_count": 2,
                "artifacts": [a, b],
            },
            {
                "trial_id": 1,
                "coder_result_observed": True,
                "runner_result_observed": True,
                "runner_current_successful_count": 1,
                "artifacts": [c],
            },
        ],
        "observed_cumulative_library_states": [
            {
                "trial_id": 0,
                "factor_count": 2,
                "factors": [
                    {
                        "name": "A",
                        "source_trial_id": 0,
                        "sha256": a["sha256"],
                        "relative_path": a["relative_path"],
                    },
                    {
                        "name": "B",
                        "source_trial_id": 0,
                        "sha256": b["sha256"],
                        "relative_path": b["relative_path"],
                    },
                ],
            },
            {
                "trial_id": 1,
                "factor_count": 2,
                "factors": [
                    {
                        "name": "A",
                        "source_trial_id": 0,
                        "sha256": a["sha256"],
                        "relative_path": a["relative_path"],
                    },
                    {
                        "name": "C",
                        "source_trial_id": 1,
                        "sha256": c["sha256"],
                        "relative_path": c["relative_path"],
                    },
                ],
            },
        ],
        "final_observed_cumulative_library": {
            "trial_id": 1,
            "factor_count": 2,
            "factors": [
                {
                    "name": "A",
                    "source_trial_id": 0,
                    "sha256": a["sha256"],
                    "relative_path": a["relative_path"],
                },
                {
                    "name": "C",
                    "source_trial_id": 1,
                    "sha256": c["sha256"],
                    "relative_path": c["relative_path"],
                },
            ],
        },
    }

    art = tmp_path / "art.json"
    art.write_text(
        json.dumps(recovery),
        encoding="utf-8",
    )

    spec = tmp_path / "spec.json"
    _spec(spec)

    out = tmp_path / "binding.json"

    result = build_composition_binding(
        logical_events=events,
        artifact_manifest=art,
        evaluation_spec=spec,
        out_path=out,
    )

    second = result["cumulative_libraries"][1]

    assert [x["name"] for x in second["artifacts"]] == ["A", "C"]

    assert "B" not in [x["name"] for x in second["artifacts"]]

    assert result["summary"] == {
        "logical_trial_count": 2,
        "trial_experiment_binding_count": 2,
        "trial_experiment_unbound_count": 0,
        "bound_current_successful_artifact_count": 3,
        "cumulative_library_binding_count": 2,
        "final_cumulative_library_trial_id": 1,
        "final_cumulative_library_factor_count": 2,
    }


def test_no_runner_is_unbound_not_invented(
    tmp_path: Path,
) -> None:
    a = _artifact("A", 0, "a")
    ghost = _artifact("Ghost", 1, "g")

    events = tmp_path / "events.jsonl"

    _write_jsonl(
        events,
        [
            _coder(0),
            _runner(0, ["A"], ["A"]),
            _coder(1),
        ],
    )

    recovery = {
        "schema": ("agent-alpha-audit.artifact-recovery.v1"),
        "artifact_tree_sha256": "tree-sha",
        "summary": {
            "logical_trial_count": 2,
            "runner_trial_count": 1,
            "recovered_artifact_count": 2,
            "runner_current_successful_artifact_count": 1,
            "observed_cumulative_library_state_count": 1,
            "final_cumulative_library_factor_count": 1,
        },
        "trial_records": [
            {
                "trial_id": 0,
                "coder_result_observed": True,
                "runner_result_observed": True,
                "runner_current_successful_count": 1,
                "artifacts": [a],
            },
            {
                "trial_id": 1,
                "coder_result_observed": True,
                "runner_result_observed": False,
                "runner_current_successful_count": 0,
                "artifacts": [ghost],
            },
        ],
        "observed_cumulative_library_states": [
            {
                "trial_id": 0,
                "factor_count": 1,
                "factors": [
                    {
                        "name": "A",
                        "source_trial_id": 0,
                        "sha256": a["sha256"],
                        "relative_path": a["relative_path"],
                    }
                ],
            }
        ],
        "final_observed_cumulative_library": {
            "trial_id": 0,
            "factor_count": 1,
            "factors": [
                {
                    "name": "A",
                    "source_trial_id": 0,
                    "sha256": a["sha256"],
                    "relative_path": a["relative_path"],
                }
            ],
        },
    }

    art = tmp_path / "art.json"
    art.write_text(
        json.dumps(recovery),
        encoding="utf-8",
    )

    spec = tmp_path / "spec.json"
    _spec(spec)

    result = build_composition_binding(
        logical_events=events,
        artifact_manifest=art,
        evaluation_spec=spec,
        out_path=tmp_path / "binding.json",
    )

    trial1 = result["trial_experiments"][1]

    assert trial1["composition_bound"] is False
    assert trial1["artifacts"] == []
    assert trial1["reason"] == "no_canonical_runner_result"


def test_rejects_cumulative_state_drift(
    tmp_path: Path,
) -> None:
    a = _artifact("A", 0, "a")
    b = _artifact("B", 0, "b")
    b["runner_current_successful"] = False

    events = tmp_path / "events.jsonl"

    _write_jsonl(
        events,
        [
            _coder(0),
            _runner(
                0,
                ["A"],
                ["A"],
            ),
        ],
    )

    recovery = {
        "schema": ("agent-alpha-audit.artifact-recovery.v1"),
        "artifact_tree_sha256": "tree-sha",
        "summary": {
            "logical_trial_count": 1,
            "runner_trial_count": 1,
            "recovered_artifact_count": 2,
            "runner_current_successful_artifact_count": 1,
            "observed_cumulative_library_state_count": 1,
            "final_cumulative_library_factor_count": 1,
        },
        "trial_records": [
            {
                "trial_id": 0,
                "coder_result_observed": True,
                "runner_result_observed": True,
                "runner_current_successful_count": 1,
                "artifacts": [a, b],
            }
        ],
        "observed_cumulative_library_states": [
            {
                "trial_id": 0,
                "factor_count": 1,
                "factors": [
                    {
                        "name": "B",
                        "source_trial_id": 0,
                        "sha256": b["sha256"],
                        "relative_path": b["relative_path"],
                    }
                ],
            }
        ],
        "final_observed_cumulative_library": {
            "trial_id": 0,
            "factor_count": 1,
            "factors": [
                {
                    "name": "B",
                    "source_trial_id": 0,
                    "sha256": b["sha256"],
                    "relative_path": b["relative_path"],
                }
            ],
        },
    }

    art = tmp_path / "art.json"
    art.write_text(
        json.dumps(recovery),
        encoding="utf-8",
    )

    spec = tmp_path / "spec.json"
    _spec(spec)

    with pytest.raises(
        CompositionBindingError,
        match="does not exactly match runner",
    ):
        build_composition_binding(
            logical_events=events,
            artifact_manifest=art,
            evaluation_spec=spec,
            out_path=tmp_path / "binding.json",
        )
