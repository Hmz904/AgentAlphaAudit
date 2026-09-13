from __future__ import annotations

import inspect

from agent_alpha_audit.rdagent_evaluator import run_strict_selection_qrun


def test_frozen_oos_qrun_is_separate_from_selection_return_contract():
    sig = inspect.signature(run_strict_selection_qrun)
    source = inspect.getsource(run_strict_selection_qrun)

    assert "phase_name" in sig.parameters

    # Selection replay keeps its locked-calendar return contract.
    assert 'phase_name == "strict_selection_replay"' in source
    assert "finalize_selection_returns(" in source
    assert "sha256_file(reference_calendar_csv)" in source

    # Frozen OOS must not manufacture selection-period artifacts.
    assert 'phase_name == "strict_frozen_oos"' in source
    assert '"frozen_oos_portfolio_report"' in source
    assert '"validation_returns_written": False' in source
    assert '"selection_return_contract_written": False' in source
