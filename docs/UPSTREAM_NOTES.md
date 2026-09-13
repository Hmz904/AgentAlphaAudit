# Upstream notes for first audit target

**Pinned target: RD-Agent v0.8.0 (`274e274`, released 2025-11-03).**

Verified version-specific contracts used by the harness:

- `RDLoop.direct_exp_gen`, `coding`, `running`, and `feedback` exist; the factor path uses `FactorRDLoop` and v1 confirmatory instrumentation is serial/in-process.
- v0.8.0 `feedback()` appends `(experiment, feedback)` to `trace.hist` and returns `None`.
- `Experiment.result` is backed by `running_info.result`.
- workflow subprocess/parallel execution must be disabled for an in-process monkeypatch probe.
- Qlib train/valid/test dates are defined in installed execution-template YAMLs, not `QUANT_PROP_SETTING`.
- v0.8.0 factor templates such as `conf_baseline.yaml` and `conf_combined_factors.yaml` use `train=[2008-01-01,2014-12-31]`, `valid=[2015-01-01,2016-12-31]`, `test=[2017-01-01,2020-08-01]`.
- `QlibFBWorkspace` injects the template folder and executes a chosen `conf*.yaml`; the factor runner can switch among multiple templates depending on state, so the audit reconciles **all execution templates with explicit segment blocks**.
- the factor converter carries prior factor experiments in `based_experiments`; the factor runner combines historical factor data with the newly generated factors before Qlib evaluation. Therefore cumulative factor library state, not a single factor, is the v1 primary outcome unit.
- `process_factor_data` includes only factor implementations with truthy per-task CoSTEER feedback; the runtime probe records the same successful-factor state for cumulative-library reconstruction.
- upstream `test` is agent-visible when its result feeds subsequent research and is never equated with frozen OOS.

Primary upstream source: https://github.com/microsoft/RD-Agent/tree/v0.8.0


## Observed runtime config (v0.5)

Static template discovery is preflight only. The audit now observes the exact YAML file inside `experiment_workspace.workspace_path` immediately before `QlibFBWorkspace.execute()` invokes `qrun`; the event stores the file SHA256, train/valid/test segments, provider URI and run environment. Locked runs fail before qrun if this observed config differs from the run lock.

The factor-path upstream test interval ending 2020-08-01 is agent-visible. A genuine later frozen OOS therefore requires a separate full-history evaluator dataset extending past that date, while the RD-Agent research provider remains physically truncated before frozen OOS.
