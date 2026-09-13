"""Optional contract checks against the actual pinned RD-Agent package.

Run with: ``pip install -e '.[dev,rdagent]' && pytest -q``.
The mandatory faithful-stub test catches the same v0.8.0 behaviors without the
heavy RD-Agent dependency; these tests turn package compatibility into executable
evidence when the target environment is available.
"""

import importlib.metadata

import pandas as pd
import pytest

from agent_alpha_audit.integrations.rdagent_probe import _runner_snapshot
from agent_alpha_audit.utils import safe_jsonable


def _require_080():
    pytest.importorskip("rdagent")
    version = importlib.metadata.version("rdagent")
    if version != "0.8.0":
        pytest.skip(f"contract target is rdagent==0.8.0, found {version}")


def test_rdagent_080_hypothesis_feedback_contract():
    _require_080()
    from rdagent.core.proposal import HypothesisFeedback

    fb = HypothesisFeedback(
        observations="obs",
        hypothesis_evaluation="eval",
        new_hypothesis="next",
        reason="reason",
        decision=False,
    )
    payload = safe_jsonable(fb)
    assert payload["decision"] is False
    assert payload["observations"] == "obs"


def test_rdagent_080_qlib_experiment_result_contract():
    _require_080()
    from rdagent.scenarios.qlib.experiment.factor_experiment import QlibFactorExperiment

    exp = QlibFactorExperiment(sub_tasks=[])
    exp.result = pd.Series(
        [0.12, 1.21],
        index=pd.MultiIndex.from_tuples(
            [("excess_return_with_cost", "annualized_return"), ("excess_return_with_cost", "information_ratio")]
        ),
    )
    payload = _runner_snapshot(exp)
    assert payload["result"]["excess_return_with_cost.annualized_return"] == 0.12
    assert payload["result"]["excess_return_with_cost.information_ratio"] == 1.21
