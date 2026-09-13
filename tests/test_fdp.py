import pytest

from agent_alpha_audit.audit.fdp import summarize_known_truth_fdp


def test_fdp_tail_and_mfdr_are_distinct():
    # 90 quiet runs, 10 catastrophic bursts.
    v = [0] * 90 + [97] * 10
    r = [0] * 90 + [100] * 10
    s = summarize_known_truth_fdp(v, r)
    assert s['mean_fdp'] == pytest.approx(0.097)
    assert s['median_fdp'] == 0.0
    assert s['fdp_q95'] == pytest.approx(0.97)
    assert s['mFDR_ratio_EV_ER'] == pytest.approx(0.97)
