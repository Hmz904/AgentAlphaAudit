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

## RD-Agent evaluation specification v1

For the locked RD-Agent(Q) confirmatory case, the evaluator distinguishes
three periods and three evaluation phases.

The 2015--2016 segment is the **model-validation** segment used by the
combination model. It is not the search-selection sample. The
2017-01-01--2020-08-01 agent-visible test segment is the
**adaptive-search selection period** and is therefore the return support
used for trial-level search diagnostics such as Sharpe dispersion and DSR.
The frozen 2020-08-03--2026-09-10 segment remains never-agent-visible.

The primary captured RD-Agent configuration is
`conf_combined_factors.yaml`. It combines the fixed Alpha158 baseline
feature set with the recovered factor library through
`combined_factors_df.parquet`, then fits `LGBModel`. The SOTA neural-model
configuration is a comparator and is not substituted for the primary
combination model.

The evaluator has three phases:

1. **Upstream reproduction** uses the physically truncated research
   provider and preserves the captured upstream model and asymmetric
   transaction costs. Its purpose is compatibility checking. Because the
   upstream LightGBM configuration did not explicitly set a seed or
   deterministic flag, this phase is not itself claimed to be
   deterministically reproducible.

2. **Strict selection replay** uses the same physically truncated
   provider and the locked 2017--2020 selection period, but applies the
   predeclared strict symmetric transaction cost and evaluator-side
   deterministic LightGBM controls. Trial-level returns from this phase
   are the appropriate inputs to search-correction diagnostics.

3. **Strict frozen OOS** uses the independent full-history provider,
   the locked 2020-08-03--2026-09-10 holdout, the same strict costs and
   deterministic controls, and unchanged training/model-validation
   segments. The data-handler horizon is extended to the locked frozen
   OOS end because the captured template's 2022-08-01 handler boundary
   predates the locked holdout end.

Under pyqlib 0.9.7 `TopkDropoutStrategy`, the current trade step consumes
the prediction from `shift=1`, so the contract records a one-trading-step
signal-to-trade lag. Trading uses the captured close-price execution
convention.

For backward compatibility, `validation_returns.csv` remains the current
trial-return filename, but its semantic role for this case is
`selection_period_returns`. A future schema may rename the file; code must
not reinterpret the 2015--2016 model-validation segment as the DSR sample.

A global evaluation specification alone does not make a trial or library
strict-replay-ready. Immutable recovered artifacts must still be bound to
the exact trial experiment or cumulative-library composition before the
manifest readiness gate can become true.
