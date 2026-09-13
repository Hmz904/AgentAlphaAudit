from __future__ import annotations

import json
import pickle
from pathlib import Path

import pytest

from agent_alpha_audit.artifact_recovery import (
    ArtifactRecoveryError,
    recover_rdagent_artifacts,
)


def _write_events(
    path: Path,
    rows: list[dict],
) -> None:
    path.write_text(
        "".join(json.dumps(row) + "\n" for row in rows),
        encoding="utf-8",
    )


def _checkpoint(
    root: Path,
    trial_id: int,
    sources: list[str],
) -> Path:
    path = root / "__session__" / str(trial_id) / "1_coding"
    path.parent.mkdir(parents=True)
    path.write_bytes(
        pickle.dumps(
            {
                "files": [
                    {
                        "path": "factor.py",
                        "source": source,
                    }
                    for source in sources
                ]
            },
            protocol=4,
        )
    )
    return path


def _coder_payload(
    workspace: Path,
    name: str,
) -> dict:
    return {
        "sub_tasks": [
            {
                "factor_name": name,
                "factor_formulation": "x",
                "factor_implementation": True,
            }
        ],
        "sub_workspace_list": [
            {
                "workspace_path": str(workspace),
                "raise_exception": False,
            }
        ],
    }


def test_recovery_copies_and_binds_runner_state(
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()

    source = "def factor():\n    return 1\n"
    (workspace / "factor.py").write_text(
        source,
        encoding="utf-8",
    )

    checkpoint_root = tmp_path / "log"
    _checkpoint(
        checkpoint_root,
        0,
        [source],
    )

    events = tmp_path / "events.jsonl"

    _write_events(
        events,
        [
            {
                "trial_id": "0",
                "tag": "coder_result",
                "payload": _coder_payload(
                    workspace,
                    "Alpha",
                ),
            },
            {
                "trial_id": "0",
                "tag": "runner_result",
                "payload": {
                    "factor_state": {
                        "current_successful": [
                            {
                                "name": "Alpha",
                                "formulation": "x",
                            }
                        ],
                        "cumulative_successful": [
                            {
                                "name": "Alpha",
                                "formulation": "x",
                            }
                        ],
                    }
                },
            },
        ],
    )

    out = tmp_path / "out"

    manifest = recover_rdagent_artifacts(
        logical_events=events,
        out_dir=out,
        checkpoint_roots={
            "log": checkpoint_root,
        },
    )

    assert manifest["summary"]["logical_trial_count"] == 1
    assert manifest["summary"]["recovered_artifact_count"] == 1
    assert manifest["summary"]["runner_current_successful_artifact_count"] == 1

    trial = manifest["trial_records"][0]
    assert trial["checkpoint_exact_match"] is True
    assert trial["artifacts"][0]["runner_current_successful"] is True

    frozen = out / trial["artifacts"][0]["relative_path"]
    assert frozen.read_text(encoding="utf-8") == source

    final_library = manifest["final_observed_cumulative_library"]
    assert final_library["factor_count"] == 1
    assert final_library["factors"][0]["artifact_id"] == trial["artifacts"][0]["artifact_id"]


def test_recovery_rejects_checkpoint_source_mismatch(
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()

    (workspace / "factor.py").write_text(
        "def factor():\n    return 1\n",
        encoding="utf-8",
    )

    checkpoint_root = tmp_path / "log"

    _checkpoint(
        checkpoint_root,
        0,
        ["def factor():\n    return 999\n"],
    )

    events = tmp_path / "events.jsonl"

    _write_events(
        events,
        [
            {
                "trial_id": "0",
                "tag": "coder_result",
                "payload": _coder_payload(
                    workspace,
                    "Alpha",
                ),
            }
        ],
    )

    with pytest.raises(
        ArtifactRecoveryError,
        match="no coding checkpoint",
    ):
        recover_rdagent_artifacts(
            logical_events=events,
            out_dir=tmp_path / "out",
            checkpoint_roots={
                "log": checkpoint_root,
            },
        )


def test_recovery_rejects_unbound_runner_success(
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()

    source = "def factor():\n    return 1\n"
    (workspace / "factor.py").write_text(
        source,
        encoding="utf-8",
    )

    checkpoint_root = tmp_path / "log"
    _checkpoint(
        checkpoint_root,
        0,
        [source],
    )

    events = tmp_path / "events.jsonl"

    _write_events(
        events,
        [
            {
                "trial_id": "0",
                "tag": "coder_result",
                "payload": _coder_payload(
                    workspace,
                    "Alpha",
                ),
            },
            {
                "trial_id": "0",
                "tag": "runner_result",
                "payload": {
                    "factor_state": {
                        "current_successful": [
                            {
                                "name": "Unknown",
                                "formulation": "x",
                            }
                        ],
                        "cumulative_successful": [],
                    }
                },
            },
        ],
    )

    with pytest.raises(
        ArtifactRecoveryError,
        match="have no recovered artifact",
    ):
        recover_rdagent_artifacts(
            logical_events=events,
            out_dir=tmp_path / "out",
            checkpoint_roots={
                "log": checkpoint_root,
            },
        )
