# AgentAlphaAudit

> **Selection correction is impossible if the system only saves its winner.**

> 

**A reproducible audit harness for autonomous quantitative research agents.**

*Can an AI-generated alpha survive its own research process?*

AgentAlphaAudit is not another alpha-mining agent. It records the *entire* research trajectory and asks whether the agent's actual output object survives point-in-time data rules, holdout isolation, realistic trading assumptions, search/selection adjustment, factor redundancy checks, and frozen out-of-sample evaluation. For RD-Agent v0.8.0 factor mining, that output object is the **cumulative factor library**, not one cherry-picked factor.

**First audit target: Microsoft RD-Agent(Q) 0.8.0 — factor-mining path.**

The current public RD-Agent(Q) workflow iteratively proposes hypotheses, implements factor/model experiments, runs Qlib evaluation, generates feedback, and uses that feedback in subsequent research. Its finance documentation also exposes configurable train/validation/test segments. Those properties make it an ideal first system for a transparent alpha-audit case study.

Upstream references:

- https://github.com/microsoft/RD-Agent
- https://github.com/microsoft/RD-Agent/blob/v0.8.0/rdagent/app/qlib_rd_loop/quant.py
- https://github.com/microsoft/RD-Agent/tree/v0.8.0/rdagent/scenarios/qlib/experiment
- https://github.com/microsoft/RD-Agent/blob/v0.8.0/rdagent/scenarios/qlib/developer/factor_runner.py


## Real RD-Agent(Q) case study

The first confirmatory case study audits a **30-loop Microsoft RD-Agent(Q) v0.8.0 factor-mining run** under a locked research protocol.

- **169 raw execution events** captured across the original run and resumed continuations
- reconciled into **161 logical events and 30 logical research trials**
- preserved retry and failure provenance rather than silently treating resumes as new trials
- reconciliation v2 validates the locked protocol across all **7** resume streams and reconstructs execution attempts by distinct proposal boundaries rather than independently choosing the latest event per tag
- reconciliation arithmetic is explicit: **169 raw rows = 7 run-config observations + 162 trial-event observations; 162 trial observations -> 160 canonical trial events (one exact duplicate group and one superseded Trial 18 proposal attempt); + 1 canonical run-config = 161 logical events across 30 trials**
- **21/30** loop states contain an observed runner snapshot; failed/no-runner loops carry the last successful cumulative state forward rather than adding unimplemented proposals
- exported **30 trial** and **30 cumulative-library timeline** audit targets while preserving all failed/no-runner loops in the search denominator
- recovered **79 executable factor implementations**, all with exact coding-checkpoint source matches; **64** correspond to runner `current_successful` artifacts
- bound the recovered artifacts to the locked evaluation specification and exact RD-Agent runner-defined compositions rather than reconstructing libraries by historical union
- strict-eval manifest v4 marks **21/30 trial experiments** replay-input ready; the remaining 9 have no canonical runner result and remain explicitly non-ready
- **21/21 observed cumulative-library runner snapshots** are replay-input ready; carried-forward states remain visible in the 30-loop chronology but are not counted as new observed states
- recovered the final primary outcome directly from the **Loop 29 RD-Agent runner state**: a **12-factor cumulative library**, with all 12 artifact hashes verified
- locked the agent-visible search/selection calendar to **871 trading days (2017-01-03 through 2020-07-31)** from the physically truncated research provider
- physical research-data cutoff enforced before the frozen OOS period

The confirmatory audit is complete. Of **30 captured trials**, 21 had exact runner-backed compositions ready for deterministic replay; **20 replayed successfully**, Trial 20 failed by factor-execution timeout, and nine remained non-replay-ready. Missing and failed trials remain in the raw search denominator.

### Final audited result

The primary RD-Agent outcome is the **Loop 29 cumulative library of 12 factors**, not the best individual trial. The exact same library was evaluated on the agent-visible selection period and then unchanged on the frozen OOS period, using the locked 10 bps one-way cost convention.

| Primary 12-factor library | Selection 2017-01-03–2020-07-31 | Frozen OOS 2020-08-03–2026-09-10 |
| --- | ---: | ---: |
| Trading days | 871 | 1,483 |
| Net annualized return | 21.06% | **7.30%** |
| Net CAGR | 20.13% | **4.59%** |
| Net Sharpe | 0.906 | **0.307** |
| Max drawdown | -31.62% | **-44.79%** |
| IC | 0.0323 | **0.0139** |
| Rank IC | 0.0369 | **0.0115** |

The library therefore survives frozen OOS with positive signal, but with substantial decay: net Sharpe falls by **0.599** and retains only **33.9%** of its selection-period level. Qlib's benchmark-relative, cost-adjusted annualized excess return remains positive, declining from **8.53% to 5.86%**, while information ratio declines from **0.921 to 0.558**. IC and Rank IC fall materially as well, so the deterioration is not merely a benchmark or transaction-cost effect.

The fixed secondary trial-level search diagnostic selects Trial 4 by `highest_strict_selection_sharpe`. Its observed annualized Sharpe is 0.920 versus an expected-search maximum of about 0.163. The Deflated Sharpe probability is **0.916**, with bootstrap 95% interval **[0.907, 0.928]**, using raw search count 30 and 20 usable trial Sharpe estimates. Effective-trial estimation is suppressed because return coverage is below the locked 80% threshold. This DSR is a **secondary search diagnostic**, not a significance test for the final cumulative library.

Frozen-OOS Ridge-factor construction preserves the original RD-Agent all-market `D.instruments()` semantics rather than recomputing only within CSI300. The full factor input spans 2008-12-29–2026-09-10, contains **15,114,871 rows across 6,093 instruments**, and reproduces the original data **bit-for-bit through 2020-07-31**.

Machine-readable final evidence is in [`case_studies/rdagent_q_30loop/audited_results.json`](case_studies/rdagent_q_30loop/audited_results.json).

Machine-readable case-study evidence:
[`summary.json`](case_studies/rdagent_q_30loop/summary.json) ·
[`reconciliation.json`](case_studies/rdagent_q_30loop/reconciliation.json)

The reproducible environment is intentionally pinned to **Python 3.11** (`>=3.11,<3.12`) because that is the tested compatibility surface for the locked RD-Agent/Qlib stack; Python 3.12 compatibility is not claimed.

### Why this matters

Agent failures are not only model failures. Long-running agentic workflows can fail through implementation bugs, timeouts, resource exhaustion, interrupted sessions, contaminated resumes and evaluation inconsistencies. AgentAlphaAudit keeps those events visible while separating **execution history** from the **logical research trajectory**, so reliability and selection effects can be audited rather than hidden.

## What this repository audits

```text
RD-Agent / future quant agent
            │
            ▼
      Sidecar capture
  every hypothesis + result
            │
            ▼
      Trial Ledger (SQLite)
            │
    ┌───────┴────────────┐
    ▼                    ▼
Reproduction       Statistical audit
upstream metric    raw/effective trials
upstream split     Deflated Sharpe diagnostic
    │              validation reuse / holdout access
    │              redundancy / robustness
    └──────────┬─────────┘
               ▼
        Strict evaluator
   PIT → lag → costs → OOS
               │
               ▼
       Alpha Audit Waterfall
               │
               ▼
       Agent Alpha Scorecard
       REJECT / INVESTIGATE / PROMOTE
```

The design principle is simple: **selection correction is impossible if the system only saves its winner.** Every attempted hypothesis is therefore first-class audit evidence.

## v0.5 deliverables

- **RD-Agent(Q) runtime probe** at public workflow boundaries: proposal, experiment generation, coding, running and feedback; v1 confirmatory scope is the factor-mining path.
- **JSON-only sidecar capture**; the audit harness does not deserialize RD-Agent session pickle artifacts.
- **SQLite trial ledger** storing hypothesis lineage, factor expressions, code hashes, runner metrics, decisions, feedback and holdout-access status.
- **Raw trial accounting as a lower bound** including accepted/rejected/duplicate emitted hypotheses; latent alternatives considered inside one LLM call are not observable.
- **Effective trial count** from the eigenvalue participation ratio of candidate return correlations, secondary-only and suppressed when return-series coverage is low.
- **Deflated-Sharpe diagnostic** as a secondary single-trial search diagnostic, with raw captured-proposal lower bound as headline N, cross-trial Sharpe dispersion, empirical winner skew/kurtosis, bootstrap uncertainty propagated to DSR probability, and point probability suppressed below 20 usable trial Sharpes.
- **Alpha Audit Waterfall** for reported → reproduced → PIT → lag → costs → frozen OOS decay; search adjustment is reported separately as DSR/effective-trial evidence so unlike quantities are not placed on one Sharpe axis.
- **100-point Agent Alpha Scorecard**, explicitly framed as a proposed governance specification rather than a universal quality score.
- **Known-truth FDP tail diagnostics** for synthetic/null stress tests only.
- **Sequential-Alpha-Control v0.4** retained under `stress_tests/` as a case study of why mean error metrics can hide bursty false-discovery episodes.
- **Two-unit strict evaluator contract**: every trial is rerun for search diagnostics, while cumulative factor-library states are rerun for the primary RD-Agent outcome. The user's A-share platform remains a deterministic engine rather than being coupled to agent internals.
- **Observed-runtime hard gate**: installed RD-Agent YAML templates are only preflight. Every actual `QlibFBWorkspace.execute()` captures and hashes the workspace config passed to `qrun`; its train/valid/test segments and provider URI must match the lock before execution. `QUANT_PROP_SETTING` is never treated as date evidence.
- **Physical holdout gate**: the Qlib calendar is derived from the exact provider URI used by those templates, so a different user-supplied calendar cannot certify isolation.

## Important statistical boundary

For a real factor we do **not** know whether it is a true or false discovery. Therefore AgentAlphaAudit never reports empirical real-market FDP as if the truth labels were known.

FDP/FDR tail statistics belong in controlled-null or synthetic stress tests. Real agent runs instead report observable audit quantities such as:

- total trials and effective trials;
- validation-to-OOS decay;
- holdout accesses;
- trial lineage and duplicated/redundant signals;
- factor correlation / residual information;
- cost and lag sensitivity;
- frozen-OOS survival.

That distinction is deliberate and comes directly from the earlier Sequential-Alpha-Control audit work.

## Quick demo

The bundled demo is **synthetic** and exists only to prove the pipeline works end to end.

```bash
export PYTHONPATH=$PWD/src
./scripts/run_demo.sh
```

It produces:

```text
outputs/demo.sqlite
outputs/demo_report.json
outputs/AGENT_ALPHA_SCORECARD_DEMO.md
outputs/audit_waterfall_demo.svg
```

The example waterfall values are illustrative, not RD-Agent results.

## Auditing a real RD-Agent(Q) run

### 1. Freeze provenance

In the RD-Agent checkout that will actually be audited:

```bash
git rev-parse HEAD > rdagent_commit.txt
python -V > python_version.txt
python -m pip freeze > environment.lock.txt
```

Also freeze train/validation/OOS dates, universe, cost assumptions, research-loop budget and the scorecard before the run.

Do **not** silently update RD-Agent during the audit. The public repository is actively changing, including ongoing work around Qlib holdout isolation.

### 2. Capture every loop (v1 confirmatory uses the factor path)

Run the **2-loop pilot first** with a completely filled but still DRAFT lock. Supplying the draft lock intentionally dry-runs the exact template/provider/physical-holdout gate that confirmatory mode will later use:

```bash
export PYTHONPATH=/path/to/AgentAlphaAudit/src:$PYTHONPATH
python /path/to/AgentAlphaAudit/scripts/run_rdagent_audited.py \
  --events /path/to/pilot/audit_events.jsonl \
  --scenario factor \
  --run-kind pilot \
  --loop-n 2 \
  --run-lock /path/to/DRAFT_RUN_LOCK.json
```

Only after the pilot passes should that contract be frozen to `LOCKED` and the confirmatory run started:

```bash
python /path/to/AgentAlphaAudit/scripts/run_rdagent_audited.py \
  --events /path/to/audit_run/audit_events.jsonl \
  --scenario factor \
  --run-kind confirmatory \
  --run-lock /path/to/LOCKED_RUN_LOCK.json
```

The probe fails loudly if the expected RD-Agent API is unavailable. It does not use `except Exception: pass` and does not rely on opaque session parsing.

### 3. Build the ledger

```bash
python -m agent_alpha_audit ingest-rdagent \
  --events /path/to/audit_run/audit_events.jsonl \
  --db /path/to/audit_run/audit.sqlite \
  --run-id rdagent-q-001
```

### 4. Re-evaluate **all trials** with the strict engine

Export every captured trial, not only the winner:

```bash
python -m agent_alpha_audit export-eval-manifest \
  --db /path/to/audit_run/audit.sqlite \
  --run-id rdagent-q-001 \
  --out /path/to/audit_run/strict_eval_manifest.json
```

The manifest contains **both** every trial and every cumulative factor-library state. Run your deterministic evaluator on all evaluable units. Trial requests must write `validation_returns.csv` (`date,return`) so search diagnostics can be computed; cumulative-library requests feed the primary outcome/waterfall. A generic external-command runner is included:

```bash
python -m agent_alpha_audit run-strict-evaluator \
  --manifest /path/to/audit_run/strict_eval_manifest.json \
  --out-dir /path/to/audit_run/strict_eval \
  --command 'python your_ashare_adapter.py --request {request} --outdir {outdir}' \
  --timeout-seconds 1800

python -m agent_alpha_audit assemble-returns \
  --manifest /path/to/audit_run/strict_eval_manifest.json \
  --eval-dir /path/to/audit_run/strict_eval \
  --out /path/to/audit_run/trial_returns.csv \
  --coverage-json /path/to/audit_run/return_coverage.json
```

A 30-loop run therefore implies about 30 trial-level reruns **plus cumulative-library evaluations**. Missing/failed candidates remain in `raw_trials_lower_bound`; they reduce coverage instead of disappearing. Confirmatory trial returns must use identical validation dates; unequal supports hard-fail.

### 5. Build selection diagnostics

```bash
python -m agent_alpha_audit report \
  --db /path/to/audit_run/audit.sqlite \
  --run-id rdagent-q-001 \
  --returns-csv /path/to/audit_run/trial_returns.csv \
  --out /path/to/audit_run/audit_report.json
```

There is no single-trial “winner” in the primary waterfall: the primary outcome is the final cumulative factor library. The report still computes a fixed secondary sensitivity set—last accepted trial, strict-selection Sharpe maximum, and upstream-reported-metric maximum. Manual `--winner-column` remains a recorded override only. The headline count is `raw_trials_lower_bound`; effective N is secondary and suppressed under low return-series coverage.

### 6. Re-evaluate waterfall stages with the strict engine

The strict evaluator is separate from RD-Agent. It should reproduce the upstream result first, then change one assumption at a time:

```text
agent reported
    ↓
exact reproduction
    ↓
point-in-time universe
    ↓
availability / execution lag
    ↓
transaction costs
    ↓
frozen OOS

Search adjustment (raw/effective trials, DSR) is reported alongside the waterfall rather than converted into a pseudo-"adjusted Sharpe".
```

See `docs/ASHARE_EVALUATOR_CONTRACT.md` for the machine-readable boundary to the A-share engine.

## Proposed Agent Alpha Scorecard

| Category | Weight |
|---|---:|
| Data integrity / PIT | 20 |
| Holdout isolation | 20 |
| Search transparency | 15 |
| Multiple-testing adjustment | 15 |
| Trading realism | 10 |
| Robustness | 10 |
| Reproducibility / provenance | 10 |
| **Total** | **100** |

A high score means **the evidence package is auditable**. It does not mean the factor will make money.

Full specification: `docs/AGENT_ALPHA_SCORECARD_SPEC.md`.

## Repository layout

```text
AgentAlphaAudit/
├── src/agent_alpha_audit/
│   ├── adapters/             # RD-Agent sidecar → normalized trials
│   ├── audit/                # DSR, effective trials, FDP tails, scorecard, waterfall
│   ├── integrations/         # optional runtime probes
│   ├── ledger.py             # immutable-ish trial evidence store
│   └── cli.py
├── scripts/
│   ├── run_rdagent_audited.py
│   └── run_demo.sh
├── docs/
│   ├── AUDIT_PROTOCOL.md
│   ├── RDAGENT_INTEGRATION.md
│   ├── AGENT_ALPHA_SCORECARD_SPEC.md
│   └── ASHARE_EVALUATOR_CONTRACT.md
├── stress_tests/
│   └── sequential_alpha_control/
├── examples/
├── tests/
└── outputs/
```

## Critical path: all-trial search audit + cumulative-library outcome audit

The statistical half of this project is **not available from winner-only metrics**. RD-Agent/Qlib summary metrics are insufficient for DSR, effective-trial diagnostics and redundancy analysis. v0.5 therefore makes the strict-evaluator path explicit:

`ledger → export ALL trials + cumulative library states → deterministic evaluator reruns all audit units → per-trial validation_returns.csv → aligned trial_returns.csv → DSR/dependence diagnostics + cumulative-library waterfall`.

A 30-loop audit means roughly 30 strict trial-level evaluations **plus cumulative-library state evaluations**, not one winner rerun. Failed or untranslatable candidates stay in `raw_trials_lower_bound` and reduce return-series coverage rather than disappearing.

Confirmatory runs first reconcile **all installed RD-Agent Qlib execution-template segment blocks** as preflight, then hard-gate **every workspace config actually passed to `qrun`**. Each observed config is hashed and its segments/provider URI must match the lock. The provider's own calendar must end before frozen OOS. Upstream `test` remains agent-visible and is never relabeled frozen OOS. Any hard gate reading an upstream object/file must have a real pinned-package contract test in CI.

## Current status

- **Confirmatory search:** complete — 30/30 RD-Agent(Q) factor-mining loops finished.
- **Evidence reconciliation:** complete — 169 raw events across 7 streams reconcile to 161 logical events and 30 logical trials with retry/supersession provenance preserved.
- **Artifact recovery:** complete — 79/79 recovered implementations have exact coding-checkpoint source matches.
- **Evaluation specification:** complete — train, model-validation, agent-visible selection and frozen-OOS periods, providers, costs and evaluator-side determinism controls are locked.
- **Composition binding:** complete — 21 runner-observed trial compositions and 21 observed cumulative-library snapshots are bound to immutable artifacts.
- **Strict replay-input readiness:** complete — 21/30 trial experiments and 21/21 observed cumulative-library snapshots satisfy the v4 evidence gate.
- **Selection calendar:** complete — 871 research-provider trading days, 2017-01-03 through 2020-07-31, are hash-bound to the evaluation contract.
- **Strict deterministic reevaluation:** not yet completed.
- **Frozen-OOS performance:** **not claimed yet**.
- **Selection-adjusted / final audited performance:** **not claimed yet**.

The public case study therefore documents a completed autonomous-agent search, exact replay-input evidence chain, strict selection replay, secondary search-adjustment diagnostic, and primary frozen-OOS evaluation. The final library retains positive OOS signal, but its selection-period performance materially overstates OOS strength.
