# Preregistration V4 — post-selection calibration reuse with marginally valid p-values

Frozen after `ANALYTIC_NOTES_V4.md` was written and before any V4 Monte Carlo output is inspected.

## Primary question

When each null p-value is marginally valid, does reuse of one fresh post-selection parent-calibration error across related factor mutations cause practically meaningful online-FDR inflation, and is adaptive reset-on-rejection different from static shared dependence?

## Frozen DGP

- sequential hypotheses N = 500;
- Monte Carlo replicates = 5000;
- alpha = 0.05;
- LORD++ initial wealth = 0.025;
- SAFFRON lambda = 0.5;
- pi1 = 0.02;
- alternative z-scale mean theta = 1.25;
- rho in {0.50, 0.75, 0.90};
- K=n, so the standardized corrected statistic is

      Z_t = theta_t + sqrt(1-rho^2) U_t + rho A_t.

- truth labels and U innovations are shared across reuse arms within each method/rho/replicate where possible.

Every tested candidate starts as a mutation from a pre-existing selected parent; there are no root tests in the V4 stream.

## Reuse arms

1. `fresh_each`: A_t iid N(0,1) for every test.
2. `global_reuse`: one A ~ N(0,1) is used for all 500 tests.
3. `reset_on_reject`: one A is reused until a rejection; after each rejection a new independent A is drawn for the new parent lineage.

## Procedures

Primary procedures:

- LORD++
- SAFFRON

Anchor:

- Bonferroni at alpha/N. It is included because valid marginal p-values are sufficient for its FWER guarantee under arbitrary dependence.

## Primary reported quantities

For every method x arm x rho:

- mean FDR = E[V/max(R,1)] with Monte Carlo SE;
- median and 95th percentile FDP;
- mean R, V, S;
- power = S/M1;
- pooled P(null p <= .05), P(null p <= .01), mean null p;
- probability of any false rejection;
- for reset-on-reject: mean number of calibration refreshes and mean longest run under one calibration draw.

## Calibration interpretation

`fresh_each` is the implementation sanity arm. It passes if, for both LORD++ and SAFFRON at all rho values:

- 0.045 <= P(null p <= .05) <= 0.055; and
- mean FDR <= 0.060.

`global_reuse` has exact marginal null uniformity analytically for each fixed test index; departures in pooled realized p-values may occur from finite Monte Carlo but are not themselves the scientific target.

## Frozen GO / NO-GO rule

V4 receives **GO** only if all of the following hold:

1. `fresh_each` passes the sanity gate in all six LORD++/SAFFRON cells;
2. Bonferroni has Pr(any false rejection) <= 0.060 in every arm/rho cell;
3. at rho >= 0.75, either `global_reuse` or `reset_on_reject` produces mean FDR > 0.075 for LORD++ or SAFFRON in at least two method/rho cells;
4. the corresponding arm exceeds the matched `fresh_each` FDR by at least 0.025 in those cells.

V4 receives **NO-GO** otherwise.

The threshold is intentionally material rather than merely statistically significant with 5000 replicates.

## Secondary comparison

The difference `reset_on_reject - global_reuse` is reported descriptively. It is called an adaptive-reset amplification only if its mean FDR is larger by at least 0.025 in at least two matched cells at rho >= .75. This secondary label does not change the primary GO decision.

No rho, pi1, theta, N, replicate count, or threshold will be changed after V4 outputs are inspected.
