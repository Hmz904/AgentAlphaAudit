# Strict A-share evaluator contract

The deterministic strict evaluator serves **two audit units**:

1. `trial_experiment` — every captured trial, used for search accounting/DSR/redundancy;
2. `cumulative_factor_library_at_loop_k` — the primary RD-Agent factor-mining outcome trajectory.

The evaluator must not rerun only a hand-picked winner.

## Trial request

```json
{
  "run_id": "rdagent-confirmatory-001",
  "trial_id": "17",
  "evaluation_unit": "trial_experiment",
  "hypothesis": "...",
  "factor_expressions": ["..."],
  "strict_evaluator_required": true,
  "evaluable": true
}
```

If a trial cannot be translated, record failure. It stays in `raw_trials_lower_bound` and lowers return-series coverage.

## Cumulative-library request

```json
{
  "run_id": "rdagent-confirmatory-001",
  "loop_k": "17",
  "evaluation_unit": "cumulative_factor_library_at_loop_k",
  "factor_expressions": ["factor_1", "factor_2", "..."],
  "strict_evaluator_required": true,
  "evaluable": true
}
```

The final cumulative-library request is the primary outcome unit for the v1 waterfall. Trial-level selection rules are secondary diagnostics only.

## Output

Every evaluable request writes `result.json` containing data/universe hashes, lag/cost assumptions, metrics and PIT checks.

Every **trial** request additionally writes mandatory `validation_returns.csv`:

```csv
date,return
2023-01-06,0.0012
2023-01-13,-0.0008
```

Confirmatory trial series must have **identical date support**. `assemble-returns` rejects unequal validation windows rather than comparing Sharpe estimates based on unequal sample sizes.

Cumulative-library requests may also emit `validation_returns.csv`/`frozen_oos_returns.csv` for waterfall and robustness reporting, but they are not mixed into cross-trial sigma_SR.

## Execution boundary

`run-strict-evaluator` tokenizes the configured command and executes it with `shell=False` plus a finite timeout. The external A-share adapter is responsible for deterministic evaluation; AgentAlphaAudit is responsible for manifest completeness, provenance and evidence assembly.
