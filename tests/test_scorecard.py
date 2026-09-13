from agent_alpha_audit.audit.scorecard import score
from agent_alpha_audit.models import AuditEvidence


def test_scorecard_max_is_100():
    e = AuditEvidence(**{k: True for k in AuditEvidence.__dataclass_fields__ if k != 'notes'})
    assert score(e)['total'] == 100
