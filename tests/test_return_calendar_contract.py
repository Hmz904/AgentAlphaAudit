from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pandas as pd
import pytest

from agent_alpha_audit.strict_eval import (
    assemble_trial_returns,
)


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write_returns(
    root: Path,
    trial: int,
    dates: list[str],
) -> None:
    d = root / f"trial_{trial}"
    d.mkdir(parents=True, exist_ok=True)

    pd.DataFrame(
        {
            "date": dates,
            "return": [0.01] * len(dates),
        }
    ).to_csv(
        d / "validation_returns.csv",
        index=False,
    )


def _write_spec(tmp_path: Path) -> Path:
    p = tmp_path / "evaluation_spec.json"

    spec = {
        "schema": ("agent-alpha-audit.rdagent-evaluation-spec.v1"),
        "spec_sha256": "semantic-spec-sha",
        "periods": {
            "agent_visible_selection": {
                "start": "2017-01-01",
                "end": "2020-08-01",
                "role": ("adaptive_search_selection_period; trial return series for DSR/search correction"),
            }
        },
        "phases": {
            "strict_selection_replay": {
                "required_trial_output": {
                    "compatibility_filename": ("validation_returns.csv"),
                    "semantic_name": ("selection_period_returns"),
                    "date_support": ("locked agent-visible selection calendar, identical across trials"),
                }
            }
        },
    }

    p.write_text(json.dumps(spec))
    return p


def _write_v4(
    tmp_path: Path,
    spec: Path,
    readiness: list[bool],
) -> Path:
    p = tmp_path / "manifest_v4.json"

    manifest = {
        "schema": ("agent-alpha-audit.strict-eval-manifest.v4"),
        "raw_trials_lower_bound": len(readiness),
        "evidence": {
            "evaluation_spec": {
                "file_sha256": _sha(spec),
                "spec_sha256": "semantic-spec-sha",
            }
        },
        "trial_items": [
            {
                "trial_id": str(i),
                "strict_replay_ready": ready,
            }
            for i, ready in enumerate(readiness)
        ],
    }

    p.write_text(json.dumps(manifest))
    return p


def _write_calendar(
    tmp_path: Path,
    dates: list[str],
) -> Path:
    p = tmp_path / "selection_calendar.csv"

    pd.DataFrame({"date": dates}).to_csv(p, index=False)

    return p


def test_v4_requires_explicit_locked_calendar(
    tmp_path: Path,
) -> None:
    spec = _write_spec(tmp_path)
    manifest = _write_v4(
        tmp_path,
        spec,
        [True],
    )

    with pytest.raises(
        ValueError,
        match="reference_calendar_csv",
    ):
        assemble_trial_returns(
            manifest,
            tmp_path / "eval",
            tmp_path / "out.csv",
            evaluation_spec_path=spec,
        )


def test_v4_first_trial_cannot_define_calendar(
    tmp_path: Path,
) -> None:
    spec = _write_spec(tmp_path)
    manifest = _write_v4(
        tmp_path,
        spec,
        [True],
    )
    calendar = _write_calendar(
        tmp_path,
        [
            "2017-01-03",
            "2017-01-04",
        ],
    )

    eval_dir = tmp_path / "eval"

    _write_returns(
        eval_dir,
        0,
        [
            "2017-01-04",
            "2017-01-05",
        ],
    )

    with pytest.raises(
        ValueError,
        match="locked reference calendar",
    ):
        assemble_trial_returns(
            manifest,
            eval_dir,
            tmp_path / "out.csv",
            reference_calendar_csv=calendar,
            evaluation_spec_path=spec,
        )


def test_v4_uses_selection_semantics_and_skips_unready(
    tmp_path: Path,
) -> None:
    spec = _write_spec(tmp_path)
    manifest = _write_v4(
        tmp_path,
        spec,
        [True, False],
    )

    dates = [
        "2017-01-03",
        "2017-01-04",
    ]

    calendar = _write_calendar(
        tmp_path,
        dates,
    )

    eval_dir = tmp_path / "eval"

    _write_returns(
        eval_dir,
        0,
        dates,
    )

    # Deliberately present on disk, but must not enter
    # the strict sample because trial 1 is not ready.
    _write_returns(
        eval_dir,
        1,
        dates,
    )

    result = assemble_trial_returns(
        manifest,
        eval_dir,
        tmp_path / "out.csv",
        reference_calendar_csv=calendar,
        evaluation_spec_path=spec,
    )

    assert result["schema"] == "agent-alpha-audit.return-coverage.v3"
    assert result["return_semantic_name"] == "selection_period_returns"
    assert result["compatibility_filename"] == "validation_returns.csv"
    assert result["date_alignment_policy"] == "locked_reference_calendar"
    assert result["reference_calendar_source"] == "explicit_locked_calendar"
    assert result["reference_calendar_n"] == 2
    assert result["selection_period_start"] == "2017-01-01"
    assert result["selection_period_end"] == "2020-08-01"

    # Denominator remains all captured search units.
    assert result["raw_trials_lower_bound"] == 2
    assert result["trials_with_aligned_returns"] == 1
    assert result["coverage"] == 0.5

    details = {x["trial_id"]: x["status"] for x in result["details"]}

    assert details == {
        "0": "included",
        "1": "not_strict_replay_ready",
    }
