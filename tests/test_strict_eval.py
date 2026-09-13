import json
import sys

import pandas as pd
import pytest

from agent_alpha_audit.ledger import TrialLedger
from agent_alpha_audit.models import TrialRecord
from agent_alpha_audit.strict_eval import (
    assemble_trial_returns,
    export_strict_eval_manifest,
    run_external_evaluator,
)


def ready_artifacts(cumulative=None):
    out = {
        "implementation_artifact": "artifact://factor.py",
        "evaluation_spec": '{"version": 1}',
    }
    if cumulative is not None:
        out["cumulative_factor_expressions"] = json.dumps(cumulative)
    return out


def test_manifest_separates_capture_from_replay_readiness(tmp_path):
    db = tmp_path / "x.sqlite"
    led = TrialLedger(db)

    # Captured expression but no executable artifact/spec:
    # must NOT be called strict-replay-ready.
    led.upsert(
        TrialRecord(
            run_id="r",
            trial_id="0",
            agent="x",
            factor_expressions=["f0"],
        )
    )

    # Same expression evidence plus explicit implementation + spec.
    led.upsert(
        TrialRecord(
            run_id="r",
            trial_id="1",
            agent="x",
            factor_expressions=["f1"],
            artifacts=ready_artifacts(),
        )
    )
    led.close()

    manifest = tmp_path / "manifest.json"
    m = export_strict_eval_manifest(db, "r", manifest)

    assert m["schema"] == "agent-alpha-audit.strict-eval-manifest.v3"
    assert m["raw_trials_lower_bound"] == 2
    assert m["captured_trial_count"] == 2
    assert m["trial_factor_representation_count"] == 2
    assert m["strict_replay_ready_trial_count"] == 1

    assert m["trial_items"][0]["captured"] is True
    assert m["trial_items"][0]["has_factor_representation"] is True
    assert m["trial_items"][0]["strict_replay_ready"] is False
    assert m["trial_items"][0]["evaluable"] is False

    assert m["trial_items"][1]["strict_replay_ready"] is True
    assert m["trial_items"][1]["evaluable"] is True


def test_failed_trial_does_not_pollute_cumulative_library(tmp_path):
    db = tmp_path / "x.sqlite"
    led = TrialLedger(db)

    # Loop 0 has a genuine runner snapshot.
    led.upsert(
        TrialRecord(
            run_id="r",
            trial_id="0",
            agent="x",
            factor_expressions=["proposal_f0"],
            artifacts={
                "cumulative_factor_expressions": json.dumps(
                    ["implemented_f0"]
                )
            },
        )
    )

    # Loop 1 has a proposal but no runner snapshot.
    led.upsert(
        TrialRecord(
            run_id="r",
            trial_id="1",
            agent="x",
            factor_expressions=["FAILED_PROPOSAL_MUST_NOT_ENTER_LIBRARY"],
        )
    )
    led.close()

    m = export_strict_eval_manifest(
        db, "r", tmp_path / "manifest.json"
    )

    assert (
        m["cumulative_library_items"][0]["factor_expressions"]
        == ["implemented_f0"]
    )
    assert (
        m["cumulative_library_items"][0]["cumulative_state_source"]
        == "runner_successful_factor_state"
    )

    assert (
        m["cumulative_library_items"][1]["factor_expressions"]
        == ["implemented_f0"]
    )
    assert (
        m["cumulative_library_items"][1]["cumulative_state_source"]
        == "carried_forward_last_runner_state"
    )

    assert (
        "FAILED_PROPOSAL_MUST_NOT_ENTER_LIBRARY"
        not in m["cumulative_library_items"][1]["factor_expressions"]
    )


def test_primary_is_last_observed_runner_snapshot(tmp_path):
    db = tmp_path / "x.sqlite"
    led = TrialLedger(db)

    led.upsert(
        TrialRecord(
            run_id="r",
            trial_id="0",
            agent="x",
            factor_expressions=["p0"],
            artifacts={
                "cumulative_factor_expressions": json.dumps(["f0"])
            },
        )
    )

    led.upsert(
        TrialRecord(
            run_id="r",
            trial_id="1",
            agent="x",
            factor_expressions=["failed_p1"],
        )
    )

    led.upsert(
        TrialRecord(
            run_id="r",
            trial_id="2",
            agent="x",
            factor_expressions=["p2"],
            artifacts={
                "cumulative_factor_expressions": json.dumps(
                    ["f0", "f2"]
                )
            },
        )
    )

    led.upsert(
        TrialRecord(
            run_id="r",
            trial_id="3",
            agent="x",
            factor_expressions=["failed_p3"],
        )
    )

    led.close()

    m = export_strict_eval_manifest(
        db, "r", tmp_path / "manifest.json"
    )

    assert m["primary_final_library_loop_k"] == "2"
    assert (
        m["primary_final_library"]["factor_expressions"]
        == ["f0", "f2"]
    )
    assert (
        m["primary_final_library"]["cumulative_state_source"]
        == "runner_successful_factor_state"
    )


def test_assembler_coverage_uses_raw_search_denominator(tmp_path):
    db = tmp_path / "x.sqlite"
    led = TrialLedger(db)

    led.upsert(
        TrialRecord(
            run_id="r",
            trial_id="0",
            agent="x",
            factor_expressions=["f0"],
            artifacts=ready_artifacts(),
        )
    )
    led.upsert(
        TrialRecord(
            run_id="r",
            trial_id="1",
            agent="x",
            factor_expressions=["f1"],
            artifacts=ready_artifacts(),
        )
    )
    led.upsert(
        TrialRecord(
            run_id="r",
            trial_id="2",
            agent="x",
            factor_expressions=[],
        )
    )
    led.close()

    manifest = tmp_path / "manifest.json"
    export_strict_eval_manifest(db, "r", manifest)

    root = tmp_path / "eval"
    for tid in ("0", "1"):
        d = root / f"trial_{tid}"
        d.mkdir(parents=True)
        pd.DataFrame(
            {
                "date": ["2023-01-01", "2023-01-02"],
                "return": [0.01, -0.01],
            }
        ).to_csv(
            d / "validation_returns.csv",
            index=False,
        )

    out = tmp_path / "returns.csv"
    c = assemble_trial_returns(manifest, root, out)

    assert c["trials_with_aligned_returns"] == 2
    assert c["coverage"] == 2 / 3
    assert c["date_alignment_policy"] == "strict_identical"


def test_assembler_rejects_different_validation_windows(tmp_path):
    db = tmp_path / "x.sqlite"
    led = TrialLedger(db)

    for i in range(2):
        led.upsert(
            TrialRecord(
                run_id="r",
                trial_id=str(i),
                agent="x",
                factor_expressions=[f"f{i}"],
                artifacts=ready_artifacts(),
            )
        )

    led.close()
    manifest = tmp_path / "m.json"
    export_strict_eval_manifest(db, "r", manifest)

    root = tmp_path / "eval"

    d = root / "trial_0"
    d.mkdir(parents=True)
    pd.DataFrame(
        {
            "date": ["2023-01-01", "2023-01-02"],
            "return": [0, 1],
        }
    ).to_csv(
        d / "validation_returns.csv",
        index=False,
    )

    d = root / "trial_1"
    d.mkdir(parents=True)
    pd.DataFrame(
        {
            "date": ["2023-01-02", "2023-01-03"],
            "return": [0, 1],
        }
    ).to_csv(
        d / "validation_returns.csv",
        index=False,
    )

    with pytest.raises(ValueError):
        assemble_trial_returns(
            manifest,
            root,
            tmp_path / "out.csv",
        )


def test_external_evaluator_uses_shell_false_and_timeout(tmp_path):
    manifest = tmp_path / "m.json"
    manifest.write_text(
        json.dumps(
            {
                "trial_items": [
                    {
                        "trial_id": "0",
                        "evaluation_unit": "trial_experiment",
                        "evaluable": True,
                    }
                ],
                "cumulative_library_items": [],
            }
        )
    )

    script = tmp_path / "writer.py"
    script.write_text(
        "import pathlib,sys;"
        'pathlib.Path(sys.argv[2]).joinpath("result.json")'
        '.write_text("{}")'
    )

    out = tmp_path / "eval"

    r = run_external_evaluator(
        manifest,
        out,
        f"{sys.executable} {script} {{request}} {{outdir}}",
        timeout_seconds=10,
    )

    assert r["results"][0]["status"] == "ok"
