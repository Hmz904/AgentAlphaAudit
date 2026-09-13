from __future__ import annotations

import json
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _case_dir() -> Path:
    return ROOT / "case_studies" / "rdagent_q_30loop"


def test_core_dependencies_include_pytables():
    data = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))

    deps = data["project"]["dependencies"]

    assert any(dep.lower().startswith("tables") for dep in deps)


def test_public_status_matches_completed_audit():
    case = _case_dir()

    summary = json.loads((case / "summary.json").read_text(encoding="utf-8"))

    readme = (ROOT / "README.md").read_text(encoding="utf-8")

    assert summary["audit_status"] == "STRICT_REPLAY_COMPLETE_FROZEN_OOS_COMPLETE"

    assert summary["primary_outcome"]["strict_replay_completed"] is True

    stale = (
        "Strict deterministic reevaluation: **not yet completed**",
        "Frozen-OOS performance: **not claimed yet**",
        "Selection-adjusted / final audited performance: **not claimed yet**",
        "STRICT_REPLAY_INPUTS_READY_EVALUATION_PENDING",
    )

    for text in stale:
        assert text not in readme

    assert "Strict deterministic reevaluation: **complete**" in readme

    assert "Frozen-OOS performance: **complete**" in readme


def test_headline_performance_is_composition_bound():
    audited = json.loads((_case_dir() / "audited_results.json").read_text(encoding="utf-8"))

    primary = audited["primary_performance"]["primary_outcome"]

    selection = primary["composition_sha256_selection"]

    frozen = primary["composition_sha256_frozen_oos"]

    assert selection
    assert selection == frozen

    assert primary["composition_identity_verified"] is True


def test_dsr_is_explicitly_secondary_and_fragile():
    audited = json.loads((_case_dir() / "audited_results.json").read_text(encoding="utf-8"))

    dsr = audited["search_adjustment"]

    assert dsr["usable_trial_sharpe_count"] == 20

    assert dsr["minimum_trials_for_point_dsr"] == 20

    assert dsr["point_estimate_threshold_margin"] == 0

    dist = dsr["observed_trial_sharpe_distribution"]

    assert dist["usable_trial_count"] == 20
    assert dist["sample_std"] < 0.1

    note = dsr["interpretation_limit"].lower()

    assert "secondary" in dsr["role"].lower()

    assert "standalone significance" in note
