# Audit protocol

AgentAlphaAudit separates **capture**, **upstream contract verification**, **exact reproduction**, **strict re-evaluation**, and **promotion**. It never treats an agent's final output as if it were one pre-specified test.

## Rule 0 — upstream-object gates require real contract tests

Any hard gate that reads a third-party object, configuration file or runtime path must have at least one test against the real pinned upstream package in CI. Hand-shaped fixtures are insufficient for such gates.

This applies to RD-Agent feedback objects, Qlib experiment results, runtime template discovery, **actual workspace configs passed to qrun**, provider-path discovery and any future upstream integration.

## Stage 0 — freeze the audit contract

Before confirmatory research starts, record the exact RD-Agent version/commit, LLM settings, runtime package environment, data snapshot, universe, all agent-visible date intervals, frozen-OOS dates, execution lag/cost assumptions, research-loop budget, audit scenario and primary outcome unit.

v1 is locked to:

- `audit_scenario = factor`;
- `primary_outcome_unit = cumulative_factor_library_at_loop_k`.

A maximum two-loop pilot exists only to validate integration. Pilot evidence is never pooled into the confirmatory run.

## Stage 0.5 — verify what RD-Agent will actually execute

Do not infer dates from `QUANT_PROP_SETTING`. Scan the installed runtime package's Qlib execution templates only as **preflight**. Then, for every Qlib execution, observe the exact workspace YAML immediately before `qrun`, record its SHA256, and hard-fail unless its train/valid/test segments and provider URI match the lock. Unknown future template families containing executable segment blocks fail closed.

Physical holdout evidence comes only from the calendar under that same provider root. A separate user-selected calendar cannot establish isolation. `holdout_access=no` additionally requires at least one observed runtime config and all observed configs to pass the runtime gate.

## Stage 1 — capture the trajectory

Every emitted proposal is recorded, including failed code, duplicate expressions, rejected hypotheses and candidates that never survive strict re-evaluation.

The headline search count is `raw_trials_lower_bound`: latent alternatives considered inside one LLM call remain unobservable.

## Stage 2 — exact reproduction

Reproduce the upstream cumulative factor-library result before shortening the visible interval. This distinguishes loss from less research history from loss due to stricter audit assumptions.

## Stage 3 — strict re-evaluation

There are two audit units:

- **trial experiments:** all captured trials, for search statistics;
- **cumulative factor-library states:** primary outcome trajectory and waterfall.

Every evaluable trial is rerun under a common validation contract. Confirmatory `trial_returns.csv` requires identical date support across included trial columns; different sample windows hard-fail.

Change one strict assumption at a time: PIT universe, data availability/lag, costs, robustness, then frozen OOS.

## Stage 3.5 — search diagnostics

DSR is reported beside, not on, the Sharpe waterfall.

- raw N is the headline count;
- `n_eff` is secondary only and requires adequate return coverage;
- sigma_SR is cross-sectional SD of trial Sharpes and receives a fixed-seed bootstrap interval;
- DSR probability receives an interval propagated from sigma_SR uncertainty;
- fewer than 20 usable trial Sharpes => suppress DSR point probability;
- selection sensitivity is reported under last-accepted, validation-Sharpe-max and upstream-metric-max rules.

Cross-trial dispersion mixes selection noise and true strategy heterogeneity, so DSR can be conservative when genuine signals are present.

## Stage 4 — controlled-null stress tests

True FDP is unknown in live market data. FDP/FDR tails are restricted to controlled-null/synthetic experiments.

## Stage 5 — promotion

Promotion requires the evidence bundle specified by the scorecard. The scorecard is a governance checklist, not universal calibration.
