# V4 results — post-selection calibration reuse with marginally valid p-values

`ANALYTIC_NOTES_V4.md` was written first and `PREREGISTRATION_V4.md` was frozen before V4 Monte Carlo output was inspected. Primary parameters are `N=500`, `pi1=.02`, alternative z-mean `1.25`, 5,000 replicates, and `rho in {.50,.75,.90}`.

## 1. Literal preregistered result: GO

The frozen V4 rule is satisfied.

- `fresh_each` passes its null-calibration/FDR sanity gate in all six LORD++/SAFFRON cells.
- Bonferroni has `Pr(any false rejection) <= .060` in every arm/rho cell.
- SAFFRON under `global_reuse` has FDR .08436 at rho=.75 and .10628 at rho=.90, exceeding .075 and exceeding the matched `fresh_each` values by .05772 and .08258.
- The secondary adaptive-reset amplification rule is **not** satisfied.

Key cells:

| method | arm | rho | FDR | MC SE | FDP q95 | mean R | mean V | P(null p<=.05) | Pr(any false) |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|
| LORD++ | fresh_each | .75 | .00830 | .00128 | 0 | .0216 | .0084 | .04993 | .0084 |
| LORD++ | global_reuse | .75 | .00663 | .00109 | 0 | .4692 | .4312 | .05455 | .0078 |
| SAFFRON | fresh_each | .75 | .02663 | .00226 | 0 | .0504 | .0288 | .04993 | .0274 |
| **SAFFRON** | **global_reuse** | **.75** | **.08436** | **.00382** | **.9746** | **28.09** | **27.38** | .05455 | .0908 |
| LORD++ | fresh_each | .90 | .00490 | .00098 | 0 | .0174 | .0050 | .04974 | .0050 |
| LORD++ | global_reuse | .90 | .00253 | .00063 | 0 | .3696 | .3460 | .04844 | .0036 |
| SAFFRON | fresh_each | .90 | .02370 | .00214 | 0 | .0438 | .0258 | .04974 | .0244 |
| **SAFFRON** | **global_reuse** | **.90** | **.10628** | **.00427** | **.9767** | **41.18** | **40.12** | .04844 | .1118 |
| Bonferroni | global_reuse | .75 | .01269 | .00140 | 0 | .1492 | .0692 | .05455 | .0182 |
| Bonferroni | global_reuse | .90 | .00177 | .00043 | 0 | .0896 | .0300 | .04844 | .0044 |

The algebraic marginal-validity claim does not come from these empirical `P(p<=.05)` columns: for any fixed test index in `global_reuse`, the null statistic is exactly a linear combination of independent normals with variance one.

## 2. The result is method-specific

LORD++ remains strongly conservative under the same shared-nuisance streams. V4 therefore does not support a claim that calibration reuse generically breaks online FDR.

The observed failure is specific here to SAFFRON under sufficiently persistent latent calibration dependence. This is compatible with its independence-based theoretical regime; V4 is a stress test, not an implementation critique.

## 3. Adaptive reset did not amplify the failure

SAFFRON `reset_on_reject` FDR is .0660 at rho=.75 and .0436 at rho=.90 in the frozen run, both below the corresponding `global_reuse` results. The preregistered adaptive-reset amplification condition is false.

Thus the strongest V4 signal is **persistent reuse of one nuisance estimate**, not rejection-triggered parent refresh itself.

## 4. Post-hoc robustness tempers the literal GO

Independent-seed checks were run only after the frozen decision:

| run | reps | SAFFRON global FDR rho=.75 | rho=.90 |
|---|---:|---:|---:|
| frozen primary | 5,000 | .08436 | .10628 |
| seed 20260912 | 5,000 | .07096 | .11162 |
| precision seed 20260913 | 20,000 | .07243 | .10468 |

Therefore rho=.90 is robustly above the material threshold, while rho=.75 is not replication-stable relative to the frozen .075 cutoff. The formal frozen decision remains GO, but the scientific claim should be stated as **clear high-dependence SAFFRON inflation, borderline at rho=.75**, not as a robust two-cell threshold crossing.

## 5. Mechanism diagnosis

The post-hoc A-decile diagnostic shows a burst process. At rho=.90, the highest shared-calibration-error decile has SAFFRON FDR .920, mean R 379.4 and mean V 370.4; lower deciles mostly make no discoveries. See `POSTHOC_V4_DIAGNOSIS.md`.

This explains why median FDP is zero while the FDP 95th percentile is near one.

## 6. Current conclusion

V4 is the first stage of this project that avoids V1's central tautology: the global-reuse arm has valid one-test marginal null p-values by construction, while a dependence-sensitive online procedure can still suffer large tail error under persistent shared nuisance reuse.

However, dependence sensitivity of independence-based online-FDR procedures is not itself new theory. The potentially novel quant-research question is whether realistic factor-agent workflows create this kind of persistent nuisance reuse, how to diagnose its effective dependence, and whether a practical selective/dependence-robust controller can preserve useful power.
