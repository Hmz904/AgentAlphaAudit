from __future__ import annotations

from collections import Counter

from ..models import TrialRecord


def trial_summary(trials: list[TrialRecord]) -> dict:
    expressions = [e for t in trials for e in t.factor_expressions]
    counts = Counter(expressions)
    holdout_yes = sum(t.holdout_access == "yes" for t in trials)
    decisions = [t.decision for t in trials if t.decision is not None]
    captured = len(trials)
    return {
        # RD-Agent can internally consider alternatives before emitting one finalized
        # hypothesis per loop. The sidecar observes emitted proposals, not latent LLM
        # candidates, so this count is deliberately labeled a lower bound on search.
        "raw_trials_lower_bound": captured,
        "captured_proposals": captured,
        "search_count_scope": "finalized hypotheses emitted by RD-Agent; internal alternatives are not observable",
        "accepted_trials": sum(x is True for x in decisions),
        "rejected_trials": sum(x is False for x in decisions),
        "decision_unknown": captured - len(decisions),
        "unique_factor_expressions": len(counts),
        "duplicate_factor_expressions": sum(max(0, n - 1) for n in counts.values()),
        "holdout_access_yes": holdout_yes,
        "holdout_access_no": sum(t.holdout_access == "no" for t in trials),
        "holdout_access_unknown": sum(t.holdout_access == "unknown" for t in trials),
    }
