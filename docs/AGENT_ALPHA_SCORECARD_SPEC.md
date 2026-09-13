# Agent Alpha Scorecard — proposed v0.5 specification

This is a **governance checklist**, not a universal scientific rating of an agent.

| Category | Weight | Evidence |
|---|---:|---|
| Data integrity / PIT | 20 | PIT universe + availability timestamps / lags |
| Holdout isolation | 20 | runtime-template/lock reconciliation + provider-root physical cutoff + no OOS-derived iterative feedback |
| Search transparency | 15 | every trial logged + prompt/code hashes |
| Multiple-testing adjustment | 15 | search adjustment + effective trial estimate |
| Trading realism | 10 | costs + turnover + market execution constraints |
| Robustness | 10 | subperiod + parameter + redundancy/incremental-alpha checks |
| Reproducibility / provenance | 10 | pinned versions + data identity + rerun command |
| **Total** | **100** | |

## Interpretation

A high score means the **evidence package is auditable**. It does not mean the factor will make money, that the agent is generally intelligent, or that future returns are guaranteed.

Missing information scores zero rather than being assumed to pass. An explicit `unknown` holdout status is not equivalent to isolation.
