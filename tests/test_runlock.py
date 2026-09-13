import json

import pytest

from agent_alpha_audit.runlock import REQUIRED_LOCK_FIELDS, validate_run_lock


def test_locked_run_requires_all_fields(tmp_path):
    d = {"status": "LOCKED"}
    for k in REQUIRED_LOCK_FIELDS:
        d[k] = 1 if k in {"confirmatory_loop_budget", "one_way_cost_bps"} else "x"
    d['audit_scenario']='factor'
    d['primary_outcome_unit']='cumulative_factor_library_at_loop_k'
    p = tmp_path / "lock.json"; p.write_text(json.dumps(d))
    assert validate_run_lock(p)["status"] == "LOCKED"
    d["llm_model"] = None; p.write_text(json.dumps(d))
    with pytest.raises(ValueError): validate_run_lock(p)
