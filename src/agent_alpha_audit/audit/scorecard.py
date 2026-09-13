from __future__ import annotations

from dataclasses import asdict

from ..models import AuditEvidence

RULES = {
    "Data integrity / PIT": [("pit_verified", 12), ("availability_lag_verified", 8)],
    "Holdout isolation": [("frozen_oos", 10), ("no_feedback_from_oos", 10)],
    "Search transparency": [("all_trials_logged", 10), ("prompt_code_hashes", 5)],
    "Multiple-testing adjustment": [("trial_adjustment_reported", 10), ("effective_trials_estimated", 5)],
    "Trading realism": [("costs_included", 5), ("turnover_reported", 3), ("execution_constraints", 2)],
    "Robustness": [("subperiod_robustness", 4), ("parameter_robustness", 3), ("factor_redundancy_checked", 3)],
    "Reproducibility / provenance": [("pinned_versions", 4), ("data_snapshot_hash", 3), ("rerun_command", 3)],
}


def score(evidence: AuditEvidence) -> dict:
    d = asdict(evidence)
    categories = {}
    total = 0
    for category, rules in RULES.items():
        got = sum(points for key, points in rules if d[key])
        possible = sum(points for _, points in rules)
        categories[category] = {"score": got, "max": possible}
        total += got
    return {"total": total, "max": 100, "categories": categories}


def render_markdown(evidence: AuditEvidence, title: str = "Agent Alpha Scorecard") -> str:
    s = score(evidence)
    lines = [f"# {title}", "", "> Proposed audit specification; not a universal scientific quality score.", ""]
    lines += ["| Category | Score |", "|---|---:|"]
    for k, v in s["categories"].items():
        lines.append(f"| {k} | {v['score']} / {v['max']} |")
    lines += [f"| **Total** | **{s['total']} / 100** |", "", "## Evidence checklist", ""]
    d = asdict(evidence)
    for category, rules in RULES.items():
        lines.append(f"### {category}")
        for key, points in rules:
            mark = "PASS" if d[key] else "MISSING"
            lines.append(f"- [{mark}] `{key}` ({points} pts)")
        lines.append("")
    if evidence.notes:
        lines += ["## Notes", ""]
        for k, v in evidence.notes.items():
            lines.append(f"- **{k}:** {v}")
    return "\n".join(lines) + "\n"
