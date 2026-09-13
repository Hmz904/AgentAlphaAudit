# Post-hoc V4 diagnosis

Written after the frozen V4 primary decision. Nothing here changes the preregistered decision in `results_v4/go_no_go_v4.json`.

## 1. Primary decision versus robustness

The frozen 5,000-replicate run returned **GO** because SAFFRON with `global_reuse` exceeded the material FDR threshold 0.075 at both rho=.75 and rho=.90, while `fresh_each` passed its sanity gate and Bonferroni retained Pr(any false rejection) <= .060.

That literal result is retained.

Two post-hoc independent-seed checks show that the rho=.90 effect is stable but the rho=.75 threshold crossing is not:

| run | reps | rho=.75 SAFFRON global FDR | rho=.90 SAFFRON global FDR |
|---|---:|---:|---:|
| frozen primary | 5,000 | .08436 | .10628 |
| seed 20260912 | 5,000 | .07096 | .11162 |
| precision seed 20260913 | 20,000 | .07243 | .10468 |

Therefore the scientific interpretation is weaker than the literal preregistered label: there is a robust high-dependence failure at rho=.90, while rho=.75 is near/below the preregistered material threshold in the larger precision run. We do **not** retroactively change the primary GO, but we also do not call the two-cell criterion replication-stable.

## 2. This is not the V1 invalid-p problem

For `global_reuse`, at every fixed test position under a null,

    Z_t = sqrt(1-rho^2) U_t + rho A,

with U_t and A independent standard normals. Hence Z_t is exactly N(0,1) marginally and the one-sided p-value is exactly Uniform(0,1) marginally. The simulation is not used to prove this algebraic fact.

Bonferroni is an important empirical anchor: in the frozen run, Pr(any false rejection) under global reuse is .0392, .0182, and .0044 for rho=.50,.75,.90. Thus the V4 failure is not caused by feeding every method anti-conservative one-test p-values.

## 3. Failure is concentrated in a latent-calibration tail

For the global-reuse arm, the shared calibration error A can be reconstructed exactly from the frozen RNG stream. Binning runs by A shows an extreme tail mechanism.

For SAFFRON at rho=.75, the highest A decile has mean A=1.82, mean R=280.2, mean V=273.4 and FDR=.762; the first six deciles make essentially no rejections. At rho=.90, the highest A decile has mean A=1.73, mean R=379.4, mean V=370.4 and FDR=.920.

Thus the large mean FDR is a burst phenomenon: a persistently positive nuisance draw creates a long run of left-shifted conditional p-values, and SAFFRON can enter a rejection avalanche. This also explains the very large FDP 95th percentiles (.975 and .977 approximately) despite median FDP=0.

This mechanism is consistent with, rather than a contradiction of, SAFFRON's independence-based guarantee. It should be described as a realistic dependence stress test, not as a flaw in SAFFRON.

## 4. LORD++ and adaptive reset

LORD++ stays strongly conservative in the same global-reuse streams. The experiment therefore does not support a generic claim that all online-FDR methods fail under calibration reuse.

`reset_on_reject` also does not amplify the effect relative to global reuse. At rho=.75/.90, SAFFRON FDR is .0660/.0436 in the frozen run, below the global-reuse values .0844/.1063. The adaptive-reset amplification criterion is false.

The reset arm's pooled null p-values become conservative at high rho because positive calibration states tend to terminate sooner through rejection while negative states persist. This duration selection is itself informative, but it is post-hoc and not a positive V4 finding.

## 5. What V4 contributes and what it does not

V4 supplies a clean stress test that V1 lacked: a shared-nuisance mechanism where each fixed-index p-value is marginally valid, Bonferroni remains controlled, but SAFFRON can show heavy-tail FDR inflation at sufficiently strong persistent dependence.

It does **not** establish a new theorem about online FDR; dependence sensitivity of independence-based online procedures is already part of the theory. The potential quant-specific contribution is the mapping from factor-research practice (reusing one parent/calibration estimate across many related hypotheses) to a concrete latent-dependence failure mode and an auditable diagnostic.

The next genuinely new step would need a practical controller or inference construction that detects/absorbs this shared nuisance without throwing away most power, or a selective-inference method conditioning on the mutation/selection history.
