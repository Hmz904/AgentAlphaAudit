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
- exported **30/30 trial-level** and **30/30 cumulative-library** states for deterministic strict reevaluation
- recovered the final primary outcome directly from the RD-Agent runner state: a **12-factor cumulative library**
- physical research-data cutoff enforced before the frozen OOS period

The confirmatory search is complete. **Strict frozen-OOS, uniform-cost and search-adjusted reevaluation is still in progress**, so upstream RD-Agent metrics are not presented as final audited performance.

Machine-readable case-study metadata:
[`case_studies/rdagent_q_30loop/summary.json`](case_studies/rdagent_q_30loop/summary.json)

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

There is no single-trial “winner” in the primary waterfall: the primary outcome is the final cumulative factor library. The report still computes a fixed secondary sensitivity set—last accepted trial, strict-validation Sharpe maximum, and upstream-reported-metric maximum. Manual `--winner-column` remains a recorded override only. The headline count is `raw_trials_lower_bound`; effective N is secondary and suppressed under low return-series coverage.

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
- **Evidence reconciliation:** complete — raw execution history has been reconciled into a logical trial ledger while preserving duplicate/resume provenance.
- **Strict-evaluation export:** complete as an audit-target manifest; implementation/evaluation eligibility is being tightened before reruns.
- **Strict deterministic reevaluation:** in progress.
- **Frozen-OOS performance:** **not claimed yet**.
- **Selection-adjusted / final audited performance:** **not claimed yet**.

The public case study therefore documents a completed autonomous-agent search and its captured audit evidence, not a completed frozen-OOS performance audit.
