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


def test_selection_rules_are_secondary_and_low_n_suppresses_point_probability(tmp_path):
    db,f=_setup(tmp_path,3)
    r=build_run_report(db,'r',returns_csv=f)
    sens=r['trial_selection_sensitivity']
    assert sens['last_agent_accepted']['column']=='trial_1'
    assert sens['highest_upstream_reported_metric']['column']=='trial_2'
    dsr=sens['last_agent_accepted']['dsr']
    assert 'probability' not in dsr
    assert 'probability_ci95' in dsr
    assert dsr['point_estimate_status'].startswith('suppressed_')


def test_manual_winner_requires_reason(tmp_path):
    db,f=_setup(tmp_path)
    with pytest.raises(ValueError):
        build_run_report(db,'r',returns_csv=f,winner_column='trial_0')
