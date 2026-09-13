from __future__ import annotations

import json
from pathlib import Path

REQUIRED_LOCK_FIELDS = [
    "rdagent_commit",
    "python_version",
    "environment_lock_sha256",
    "qlib_data_snapshot_sha256",
    "llm_model",
    "confirmatory_loop_budget",
    "train_start",
    "train_end",
    "validation_start",
    "validation_end",
    "agent_visible_test_start",
    "agent_visible_test_end",
    "frozen_oos_start",
    "frozen_oos_end",
    "one_way_cost_bps",
    "audit_scenario",
    "primary_outcome_unit",
]


def validate_run_lock(path: str | Path, require_locked: bool = True) -> dict:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if require_locked and data.get("status") != "LOCKED":
        raise ValueError("run lock status must be LOCKED before a confirmatory run")
    missing = [k for k in REQUIRED_LOCK_FIELDS if data.get(k) in (None, "", "UNRECORDED")]
    if missing:
        raise ValueError("run lock missing required fields: " + ", ".join(missing))
    if int(data["confirmatory_loop_budget"]) <= 0:
        raise ValueError("confirmatory_loop_budget must be positive")
    if data["audit_scenario"] != "factor":
        raise ValueError("v1 confirmatory audit is locked to RD-Agent factor-mining path (audit_scenario='factor')")
    if data["primary_outcome_unit"] != "cumulative_factor_library_at_loop_k":
        raise ValueError("v1 primary_outcome_unit must be cumulative_factor_library_at_loop_k")
    return data
