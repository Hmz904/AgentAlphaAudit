from __future__ import annotations

from pathlib import Path

import pytest

import agent_alpha_audit.rdagent_evaluator as evaluator


def test_frozen_oos_skips_selection_finalizer(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    def fail_if_called(**kwargs):
        raise AssertionError("selection finalizer must not run for frozen OOS")

    monkeypatch.setattr(
        evaluator,
        "finalize_selection_returns",
        fail_if_called,
    )

    result = evaluator._finalize_qrun_phase_outputs(
        phase_name="strict_frozen_oos",
        ret_path=tmp_path / "ret.pkl",
        metrics_path=tmp_path / "qlib_res.csv",
        reference_calendar_csv=None,
        root=tmp_path,
    )

    assert result == {
        "return_semantic_name": ("frozen_oos_portfolio_report"),
        "validation_returns_written": False,
        "selection_return_contract_written": False,
    }

    assert not (tmp_path / "validation_returns.csv").exists()

    assert not (tmp_path / "selection_return_contract_v1.json").exists()


def test_selection_phase_uses_locked_calendar(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    observed = {}

    def fake_finalize(**kwargs):
        observed.update(kwargs)
        return {"return_semantic_name": ("selection_period_returns")}

    monkeypatch.setattr(
        evaluator,
        "finalize_selection_returns",
        fake_finalize,
    )

    calendar = tmp_path / "calendar.csv"
    calendar.write_text(
        "date\n2020-01-02\n",
        encoding="utf-8",
    )

    ret = tmp_path / "ret.pkl"
    metrics = tmp_path / "qlib_res.csv"

    result = evaluator._finalize_qrun_phase_outputs(
        phase_name="strict_selection_replay",
        ret_path=ret,
        metrics_path=metrics,
        reference_calendar_csv=calendar,
        root=tmp_path,
    )

    assert result["return_semantic_name"] == "selection_period_returns"

    assert Path(observed["reference_calendar_csv"]) == calendar

    assert Path(observed["ret_path"]) == ret

    assert Path(observed["qlib_metrics_path"]) == metrics


def test_selection_phase_rejects_missing_calendar(
    tmp_path: Path,
):
    with pytest.raises(evaluator.StrictReplayError):
        evaluator._finalize_qrun_phase_outputs(
            phase_name="strict_selection_replay",
            ret_path=tmp_path / "ret.pkl",
            metrics_path=tmp_path / "qlib_res.csv",
            reference_calendar_csv=None,
            root=tmp_path,
        )
