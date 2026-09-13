from pathlib import Path

from agent_alpha_audit.adapters.rdagent import RDAgentSidecarAdapter
from agent_alpha_audit.ledger import TrialLedger


def test_ledger_roundtrip(tmp_path):
    fixture = Path(__file__).parents[1] / 'examples' / 'rdagent_events.jsonl'
    trials = RDAgentSidecarAdapter().parse(fixture, 'demo')
    db = tmp_path / 'ledger.sqlite'
    ledger = TrialLedger(db)
    for t in trials:
        ledger.upsert(t)
    back = ledger.trials('demo')
    ledger.close()
    assert len(back) == 3
    assert back[1].metrics['rank_ic'] == 0.022
