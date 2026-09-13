import numpy as np
import pandas as pd
import pytest

from agent_alpha_audit.audit.report import build_run_report
from agent_alpha_audit.ledger import TrialLedger
from agent_alpha_audit.models import TrialRecord


def _setup(tmp_path, n=3):
    db=tmp_path/'x.sqlite'; l=TrialLedger(db)
    rng=np.random.default_rng(0)
    data={}
    for i in range(n):
        decision=(i==1)
        l.upsert(TrialRecord(run_id='r',trial_id=str(i),agent='x',decision=decision,metrics={'information_ratio':float(i)/10}))
        data[f'trial_{i}']=rng.normal(.0002*i,0.01,252)
    l.close()
    f=tmp_path/'ret.csv'; pd.DataFrame(data).to_csv(f,index=False)
    return db,f


def test_dsr_only_applies_to_strict_selection_sharpe_argmax(tmp_path):
    db, f = _setup(tmp_path, 3)
    report = build_run_report(db, "r", returns_csv=f)
    sens = report["trial_selection_sensitivity"]

    last = sens["last_agent_accepted"]
    assert last["column"] == "trial_1"
    assert last["dsr_applicable"] is False
    assert last["dsr"] is None

    upstream = sens["highest_upstream_reported_metric"]
    assert upstream["column"] == "trial_2"
    assert upstream["dsr_applicable"] is False
    assert upstream["dsr"] is None

    strict = sens["highest_strict_selection_sharpe"]
    assert strict["dsr_applicable"] is True
    assert strict["dsr"] is not None

    # Only three usable trial Sharpes identify sigma_SR here, so the
    # DSR point probability remains suppressed under the >=20 policy.
    assert "probability" not in strict["dsr"]
    assert "probability_ci95" in strict["dsr"]
    assert strict["dsr"]["point_estimate_status"].startswith(
        "suppressed_"
    )


def test_manual_winner_requires_reason(tmp_path):
    db,f=_setup(tmp_path)
    with pytest.raises(ValueError):
        build_run_report(db,'r',returns_csv=f,winner_column='trial_0')



def test_manual_override_is_explicitly_dsr_inapplicable(tmp_path):
    db, f = _setup(tmp_path, 3)

    report = build_run_report(
        db,
        "r",
        returns_csv=f,
        winner_column="trial_0",
        winner_override_reason="audit sensitivity check",
    )

    rec = report["trial_selection_sensitivity"][
        "manual_override"
    ]

    assert rec["column"] == "trial_0"
    assert rec["dsr_applicable"] is False
    assert rec["dsr"] is None
