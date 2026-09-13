from pathlib import Path

from agent_alpha_audit.adapters.rdagent import RDAgentSidecarAdapter


def test_parse_fixture():
    p = Path(__file__).parents[1] / 'examples' / 'rdagent_events.jsonl'
    trials = RDAgentSidecarAdapter().parse(p, 'demo')
    assert len(trials) == 3
    assert trials[0].hypothesis.startswith('Short-term reversal')
    assert trials[1].metrics['sharpe'] == 1.37
    assert trials[2].decision is False
    assert trials[0].factor_expressions
