import numpy as np
import pandas as pd

from agent_alpha_audit.audit.report import build_run_report
from agent_alpha_audit.ledger import TrialLedger
from agent_alpha_audit.models import TrialRecord


def _make_ledger(path, n):
    ledger = TrialLedger(path)
    for i in range(n):
        ledger.upsert(TrialRecord(run_id="r", trial_id=str(i), agent="x", decision=(i == 0), metrics={'information_ratio':float(i)}))
    ledger.close()


def test_report_raw_trials_are_headline_and_neff_suppressed_on_low_coverage(tmp_path):
    db = tmp_path / "x.sqlite"
    _make_ledger(db, 10)
    rng = np.random.default_rng(3)
    returns = pd.DataFrame({"trial_0": rng.normal(0.0005, 0.01, 252), "trial_1": rng.normal(0.0, 0.01, 252)})
    csv = tmp_path / "returns.csv"
    returns.to_csv(csv, index=False)
    report = build_run_report(db, "r", returns_csv=csv)
    assert report["trial_accounting"]["raw_trials_lower_bound"] == 10
    assert report["trial_return_evidence"]["coverage_of_raw_trial_lower_bound"] == 0.2
    assert report["trial_return_evidence"]["effective_trials_secondary"] is None
    assert report['audit_units']['primary_outcome_unit']=='cumulative_factor_library_at_loop_k'
    # With only two trial returns there is no sigma bootstrap CI, so DSR is not emitted.
    assert report['trial_selection_sensitivity']['last_agent_accepted']['dsr'] is None
