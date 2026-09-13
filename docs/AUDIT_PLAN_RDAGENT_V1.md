# RD-Agent(Q) v0.8.0 audit plan — factor-mining path

**Status: DRAFT / NOT LOCKED. Do not use for confirmatory claims until the run lock says `LOCKED`.**

## Objective

Audit the **factor-mining path of Microsoft RD-Agent(Q) v0.8.0** as a reproducible research system. The v1 case study does not claim to audit every RD-Agent scenario or the full joint factor–model optimizer.

The audit asks two different questions and keeps their units separate:

1. **Search-unit question:** what happened across every emitted research trial?
2. **Outcome-unit question:** what happened to the cumulative factor library RD-Agent had built by loop `k`?

This distinction is mandatory. RD-Agent's factor runner combines historical factor experiments with the new factor before Qlib evaluation, so a single “winner factor” is not the object corresponding to the upstream factor-library headline.

## Frozen audit units

### Search unit

`trial_experiment`

Every emitted hypothesis/experiment remains a search trial, including failed implementations, rejected feedback, duplicates and candidates with no reproducible return series. This unit feeds:

- `raw_trials_lower_bound`;
- trial-return coverage;
- cross-trial Sharpe dispersion;
- redundancy/correlation diagnostics;
- single-trial selection sensitivity.

### Primary outcome unit

`cumulative_factor_library_at_loop_k`

The primary waterfall evaluates cumulative factor-library states, with the **final cumulative library** as the headline outcome. The strict-evaluation manifest therefore contains both every trial and cumulative library snapshots.

Single-trial rules such as “last accepted” are **secondary sensitivity analyses only** and never define the primary RD-Agent result.

## Pilot versus confirmatory run

A maximum of **2 pilot loops** may be used only to validate installation, upstream template discovery, event capture, Qlib execution, metric parsing and strict-evaluator interfaces. Pilot hypotheses/results are not part of confirmatory evidence and must use a separate event log/database.

**Pilot pass criteria now include confirmatory-gate dry run:**

- installed RD-Agent execution templates are discovered from the actual package;
- all static train/valid/test segment blocks reconcile to the draft lock;
- the exact workspace config used by at least one pilot `qrun` is observed, hashed and reconciles to the draft lock;
- one unique runtime `provider_uri` is found;
- the derived provider calendar exists under that exact provider root;
- hypothesis, decision, feedback and numeric Qlib metrics are non-empty;
- at least one strict-evaluator request can be executed and returns the expected schema.

The first confirmatory run uses **30 research loops** unless changed in the lock *before* any confirmatory result is observed.

## Upstream time-window fact that constrains the design

In RD-Agent v0.8.0, Qlib execution dates live in the installed template YAMLs under `rdagent/scenarios/qlib/experiment/{factor_template,model_template}`. They do **not** live in `QUANT_PROP_SETTING`.

The v0.8.0 factor execution templates use a test/backtest interval ending **2020-08-01** (for example `conf_baseline.yaml` and `conf_combined_factors.yaml`). The upstream label `test` is agent-visible research evidence, not frozen OOS.

Therefore the real audit needs **two data views**:

1. an RD-Agent research provider physically truncated before `frozen_oos_start`; and
2. a separate strict-evaluator snapshot that extends through frozen OOS.

If the available CN dataset stops at the upstream test endpoint, the data must be extended/updated before the audit can have a genuine later OOS. Qlib documents both community data and update/conversion workflows; alternatively, all agent-visible splits can be moved earlier and a later historical interval reserved. Exact reproduction on the upstream split remains mandatory before interpreting any loss caused by shortening the research interval.

## Hard configuration gate: observed qrun workspace config, not PropSetting

Confirmatory startup scans the **installed RD-Agent package actually being executed**. It recursively inspects every YAML family under `rdagent/scenarios/qlib/experiment/`; known execution families are `factor_template` and `model_template`. If a future unknown family contains a train/valid/test segment block, the audit fails closed until that upstream contract is reviewed.

This static scan is only preflight. During every `QlibFBWorkspace.execute()` call, AgentAlphaAudit observes the **exact workspace YAML about to be passed to `qrun`**, recording:

- workspace path and qlib config filename;
- file SHA256;
- train/valid/test segments;
- `provider_uri`;
- the `run_env` accompanying that execution.

The observed runtime config must equal the lock and the preflight provider URI **before qrun starts**. A mismatch is a hard failure. Thus the gate audits observed execution, not only installed-template claims.

The Qlib calendar used as physical-holdout evidence is derived as:

`<provider_uri>/calendars/day.txt`

A user-supplied calendar is never accepted as independent evidence unless it resolves to this exact path. This prevents proving holdout isolation with one calendar while RD-Agent reads another data root.

## Upstream-contract rule

**Any hard gate that reads an upstream RD-Agent object/file must have a contract test against the real pinned RD-Agent package.**

Faithful stubs remain useful for mandatory unit tests, but fixtures invented specifically to contain the fields a parser expects are not sufficient evidence. This rule exists because the project twice encountered the same failure mode: a parser passed a hand-shaped fixture while targeting the wrong upstream object.

The CI `rdagent-080-contract` job therefore installs `rdagent==0.8.0` and runs both runtime-object and installed-template contract tests.

## Research trajectory

Every proposed trial is counted, including:

- implementation failure;
- factor-empty failure;
- duplicate/redundant candidate;
- rejected feedback decision;
- accepted candidate.

The headline count is `raw_trials_lower_bound`, because alternatives considered internally within one LLM call are not observable from this probe.

## Exact-reproduction requirement before frozen-OOS shrinkage

The first audit leg reproduces the upstream result on the original upstream split. Only then is the agent-visible history shortened to create a physically inaccessible frozen tail. This separates:

1. performance lost because less history was available to the agent; and
2. performance lost from PIT/lag/cost/selection/OOS auditing.

## Strict re-evaluation workload

Selection correction is impossible if only the final outcome has returns. The strict evaluator therefore runs on:

1. **every captured trial** — to build aligned trial return series for search diagnostics; and
2. **cumulative factor-library states** — to audit the actual RD-Agent factor-library outcome.

For a 30-loop run this is approximately `30 + K` evaluations, where `K` is the number of cumulative library states that can be reconstructed/evaluated. Failed/untranslatable trial candidates remain in raw N and reduce coverage.

`trial_returns.csv` requires **identical validation dates for every included trial** in confirmatory mode. Unequal supports hard-fail rather than inflating cross-trial Sharpe dispersion through unequal sampling error.

## Trial-selection sensitivity (secondary only)

The report fixes three single-trial rules in advance:

1. last agent-accepted trial;
2. highest strict-validation Sharpe;
3. highest upstream-reported metric using a fixed priority list.

If they produce materially different DSR diagnostics, the difference itself is reported as evidence that “the winner” is not uniquely defined. A manual override remains possible only with a recorded reason.

## DSR policy

DSR is **secondary search evidence**, not the primary cumulative-library outcome.

- headline `N` = `raw_trials_lower_bound`;
- cross-trial Sharpe dispersion comes from strict-evaluator trial returns;
- winner skew/kurtosis come from the selected trial return series;
- `n_eff` is secondary and suppressed below 80% trial-return coverage;
- `sigma_SR` gets a fixed-seed bootstrap interval;
- that interval is propagated into `probability_ci95`;
- with fewer than **20** usable trial Sharpe estimates, the DSR point probability is suppressed and only the uncertainty interval is shown.

Cross-trial dispersion contains both selection noise and genuine strategy heterogeneity. With real signals this can make DSR conservative; that direction is explicitly disclosed rather than presented as a calibrated probability law for all factor searches.

## Primary visualization

`Alpha Audit Waterfall`: upstream cumulative-library result → exact reproduction → PIT → lag → costs → frozen OOS.

Search diagnostics (raw/effective trials, DSR interval, selection sensitivity) are shown beside the waterfall, never converted into a fake “adjusted Sharpe” bar.

## Statistical boundary

Real-market FDP is not observable and is not reported. FDP/FDR tails from `stress_tests/` are used only in controlled-null settings with known truth.

## Interpretation policy

- Large decay is not automatically evidence of wrongdoing or a bug; it is attributed to the first audit stage where it appears.
- Small decay is a legitimate positive result for RD-Agent.
- Failed exact reproduction blocks interpretation of later decay.
- A low Agent Alpha Score is an evidence/governance result, not a statement that the strategy necessarily loses money.
