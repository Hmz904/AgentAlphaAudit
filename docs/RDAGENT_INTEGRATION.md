# RD-Agent integration contract (v0.8.0 target)

## Pinned first case study

AgentAlphaAudit v1 targets the **factor-mining path** of RD-Agent(Q) v0.8.0. The full joint factor/model loop can be instrumented in pilot mode, but it is not the first locked confirmatory claim.

## Runtime probe boundaries

The probe records proposal → experiment generation → coding → running → feedback in-process and serially. It rechecks subprocess/parallel settings during every feedback step because monkeypatch instrumentation would not propagate into workflow subprocesses.

RD-Agent v0.8.0 `feedback()` writes the feedback object into `trace.hist` and returns `None`, so the probe reads the just-appended trace entry. Qlib experiment metrics are extracted explicitly through `Experiment.result` rather than object repr.

## Time segments: source of truth

`QUANT_PROP_SETTING` is **not** the source of Qlib train/valid/test dates in v0.8.0. The source of truth for this audit is the installed package's YAML execution templates under:

```text
rdagent/scenarios/qlib/experiment/factor_template/*.yaml
rdagent/scenarios/qlib/experiment/model_template/*.yaml
```

The confirmatory launcher scans every execution template with an explicit `segments:` block and requires all of them to match the run lock. It also requires exactly one `provider_uri` across those templates.

The runtime Qlib calendar is then derived from:

```text
<provider_uri>/calendars/day.txt
```

An optional `--qlib-calendar` argument is only diagnostic and must resolve to that exact derived path.

## Primary audit unit

RD-Agent's factor workflow carries previous factor experiments into subsequent experiments and the factor runner combines historical factors with the new factor before Qlib execution. Therefore:

```text
search unit   = trial_experiment
primary unit  = cumulative_factor_library_at_loop_k
```

The strict-evaluation manifest exports both.

## CI contract

The `rdagent-080-contract` CI job installs the real `rdagent==0.8.0` package and checks both:

- feedback/experiment object contracts;
- installed Qlib template discovery and segment/provider contracts.


## Runtime config observation

Installed template YAMLs are a preflight contract only. v0.5 also monkeypatches `QlibFBWorkspace.execute` in-process and records the exact config file from `experiment_workspace.workspace_path` immediately before upstream calls `qrun`. The event tag is `runtime_qlib_config` and includes the config SHA256, parsed segments, provider URI and run environment. In a locked run, mismatch raises before qrun.
