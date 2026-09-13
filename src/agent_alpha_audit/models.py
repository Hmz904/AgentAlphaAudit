from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass
class TrialRecord:
    run_id: str
    trial_id: str
    agent: str
    timestamp: str | None = None
    parent_trial_id: str | None = None
    model: str | None = None
    action: str | None = None
    hypothesis: str | None = None
    rationale: str | None = None
    factor_names: list[str] = field(default_factory=list)
    factor_expressions: list[str] = field(default_factory=list)
    prompt_hash: str | None = None
    code_hash: str | None = None
    data_snapshot: str | None = None
    train_start: str | None = None
    train_end: str | None = None
    valid_start: str | None = None
    valid_end: str | None = None
    test_start: str | None = None
    test_end: str | None = None
    metrics: dict[str, float] = field(default_factory=dict)
    decision: bool | None = None
    feedback_seen: str | None = None
    holdout_access: str = "unknown"  # yes/no/unknown
    cost_bps: float | None = None
    artifacts: dict[str, str] = field(default_factory=dict)
    raw_payload_hash: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class AuditEvidence:
    pit_verified: bool = False
    availability_lag_verified: bool = False
    frozen_oos: bool = False
    no_feedback_from_oos: bool = False
    all_trials_logged: bool = False
    prompt_code_hashes: bool = False
    trial_adjustment_reported: bool = False
    effective_trials_estimated: bool = False
    costs_included: bool = False
    turnover_reported: bool = False
    execution_constraints: bool = False
    subperiod_robustness: bool = False
    parameter_robustness: bool = False
    factor_redundancy_checked: bool = False
    pinned_versions: bool = False
    data_snapshot_hash: bool = False
    rerun_command: bool = False
    notes: dict[str, str] = field(default_factory=dict)
