from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd

from ..ledger import TrialLedger
from .statistics import (
    annualized_sharpe,
    bootstrap_std_ci,
    cross_trial_sharpe_std,
    deflated_sharpe_probability,
    deflated_sharpe_probability_interval,
    effective_number_of_trials,
    winner_return_moments,
)
from .trials import trial_summary

DEFAULT_EFFECTIVE_TRIAL_COVERAGE = 0.80
MIN_DSR_POINT_TRIALS = 20
UPSTREAM_METRIC_PRIORITY = ("information_ratio", "sharpe", "annualized_return", "rank_ic")


def _numeric_return_columns(df: pd.DataFrame) -> list[str]:
    return [str(c) for c in df.select_dtypes(include=[np.number]).columns if str(c).lower() != "date"]


def _last_accepted(trials, columns: list[str]) -> tuple[str | None, str]:
    accepted = [t for t in trials if t.decision is True]
    accepted.sort(key=lambda t: (not str(t.trial_id).isdigit(), int(t.trial_id) if str(t.trial_id).isdigit() else str(t.trial_id)))
    if not accepted:
        return None, "no accepted trial in ledger"
    tid = accepted[-1].trial_id
    for c in (f"trial_{tid}", str(tid)):
        if c in columns:
            return c, "last_agent_accepted_trial"
    return None, f"last accepted trial {tid} has no aligned return column"


def _highest_validation_sharpe(df: pd.DataFrame, columns: list[str], periods_per_year: int) -> tuple[str | None, str]:
    scored = []
    for c in columns:
        x = pd.to_numeric(df[c], errors="coerce").to_numpy(float)
        try:
            scored.append((annualized_sharpe(x, periods_per_year), c))
        except ValueError:
            pass
    if not scored:
        return None, "no valid return series"
    return max(scored)[1], "highest_strict_validation_sharpe"


def _highest_upstream_metric(trials, columns: list[str]) -> tuple[str | None, str]:
    for metric in UPSTREAM_METRIC_PRIORITY:
        scored = []
        for t in trials:
            v = (t.metrics or {}).get(metric)
            col = f"trial_{t.trial_id}"
            if v is not None and col in columns and np.isfinite(float(v)):
                scored.append((float(v), col))
        if scored:
            return max(scored)[1], f"highest_upstream_{metric}"
    return None, "no upstream reported metric matched an aligned trial column"


def _rounded_dsr(result, sigma_ci=None, probability_ci=None, include_point: bool = True) -> dict:
    d = result.__dict__.copy()
    if not include_point:
        d.pop("probability", None)
    for k, v in list(d.items()):
        if isinstance(v, float):
            d[k] = round(v, 3)
    if sigma_ci is not None:
        d["trial_sharpe_std_ci95"] = [round(float(sigma_ci[0]), 3), round(float(sigma_ci[1]), 3)]
    if probability_ci is not None:
        d["probability_ci95"] = [round(float(probability_ci[0]), 3), round(float(probability_ci[1]), 3)]
    d["point_estimate_status"] = "reported" if include_point else f"suppressed_below_{MIN_DSR_POINT_TRIALS}_trial_sharpe_estimates"
    d["precision_note"] = (
        "Displayed to 3 decimals. DSR probability uncertainty propagates the bootstrap interval for sigma_SR; "
        f"a point probability is suppressed when fewer than {MIN_DSR_POINT_TRIALS} trial Sharpe estimates identify sigma_SR."
    )
    d["conservatism_note"] = (
        "Cross-trial Sharpe dispersion mixes selection noise with genuine cross-strategy heterogeneity; "
        "when true signals exist, this can make DSR conservative."
    )
    return d


def _dsr_for_column(df, selected, sigma_sr, sigma_ci, raw_n, periods_per_year, n_sigma_trials):
    winner = pd.to_numeric(df[selected], errors="coerce").to_numpy(dtype=float)
    winner = winner[np.isfinite(winner)]
    winner_sr = annualized_sharpe(winner, periods_per_year=periods_per_year)
    winner_skew, winner_kurt, n_obs = winner_return_moments(winner)
    res = deflated_sharpe_probability(
        winner_sr, n_obs, raw_n, sigma_sr, periods_per_year=periods_per_year,
        skewness=winner_skew, kurtosis_value=winner_kurt,
    )
    prob_ci = None
    if sigma_ci is not None:
        prob_ci = deflated_sharpe_probability_interval(
            winner_sr, n_obs, raw_n, sigma_ci, periods_per_year, winner_skew, winner_kurt
        )
    include_point = n_sigma_trials >= MIN_DSR_POINT_TRIALS
    out = _rounded_dsr(res, sigma_ci, prob_ci, include_point=include_point)
    out.update({
        "winner_column": selected,
        "winner_sharpe_annualized_from_returns": round(winner_sr, 3),
        "winner_skew": round(winner_skew, 3),
        "winner_kurtosis_pearson": round(winner_kurt, 3),
        "winner_n_observations": n_obs,
        "sigma_sr_trial_count": int(n_sigma_trials),
    })
    return out


def build_run_report(
    ledger_path: str | Path,
    run_id: str,
    returns_csv: str | Path | None = None,
    winner_column: str | None = None,
    winner_override_reason: str | None = None,
    periods_per_year: int = 252,
    min_effective_trial_coverage: float = DEFAULT_EFFECTIVE_TRIAL_COVERAGE,
) -> dict:
    ledger = TrialLedger(ledger_path)
    trials = ledger.trials(run_id)
    ledger.close()
    accounting = trial_summary(trials)
    out: dict = {
        "run_id": run_id,
        "trial_accounting": accounting,
        "audit_units": {
            "search_unit": "trial_experiment",
            "primary_outcome_unit": "cumulative_factor_library_at_loop_k",
            "note": "single-trial selection diagnostics are secondary; the primary waterfall audits the final cumulative factor library",
        },
    }

    if not returns_csv:
        out["warnings"] = [
            "Statistical search diagnostics unavailable until the strict evaluator reruns ALL captured trials and produces aligned validation return series."
        ]
        return out

    df = pd.read_csv(returns_csv)
    numeric_cols = _numeric_return_columns(df)
    raw_n = max(1, int(accounting["raw_trials_lower_bound"]))
    observed_n = len(numeric_cols)
    coverage = min(1.0, observed_n / raw_n)
    evidence: dict = {
        "return_series_columns": numeric_cols,
        "return_series_trials": observed_n,
        "raw_trials_lower_bound": raw_n,
        "coverage_of_raw_trial_lower_bound": round(coverage, 3),
        "effective_trial_coverage_threshold": float(min_effective_trial_coverage),
        "strict_evaluator_policy": "all captured trials; primary outcome evaluated separately as cumulative factor library",
    }
    warnings: list[str] = []

    sigma_sr = None
    sigma_ci = None
    trial_srs = np.array([])
    if observed_n >= 2:
        matrix = df[numeric_cols].to_numpy(dtype=float)
        try:
            sigma_sr, trial_srs = cross_trial_sharpe_std(matrix, periods_per_year=periods_per_year)
            evidence["cross_trial_sharpe_sd_annualized"] = round(sigma_sr, 3)
            evidence["sigma_sr_trial_count"] = len(trial_srs)
            evidence["trial_sharpe_min"] = round(float(np.min(trial_srs)), 3)
            evidence["trial_sharpe_median"] = round(float(np.median(trial_srs)), 3)
            evidence["trial_sharpe_max"] = round(float(np.max(trial_srs)), 3)
            if len(trial_srs) >= 3:
                sigma_ci = bootstrap_std_ci(trial_srs)
                evidence["cross_trial_sharpe_sd_ci95"] = [round(sigma_ci[0], 3), round(sigma_ci[1], 3)]
            if len(trial_srs) < MIN_DSR_POINT_TRIALS:
                warnings.append(
                    f"DSR point probability suppressed: sigma_SR is estimated from only {len(trial_srs)} trial Sharpes (<{MIN_DSR_POINT_TRIALS}); interval only"
                )
        except ValueError as exc:
            warnings.append(f"DSR unavailable: {exc}")
    else:
        warnings.append("DSR unavailable: fewer than two trial return series")

    if observed_n >= 2 and coverage >= min_effective_trial_coverage:
        matrix = df[numeric_cols].to_numpy(dtype=float)
        evidence["effective_trials_secondary"] = round(effective_number_of_trials(matrix), 2)
        evidence["effective_trials_status"] = "computed_secondary_only"
    else:
        evidence["effective_trials_secondary"] = None
        evidence["effective_trials_status"] = "suppressed_low_coverage"
        warnings.append("effective trial count suppressed because candidate-return coverage is below the configured threshold")

    # Fixed, pre-declared sensitivity set. None of these defines the primary RD-Agent
    # outcome; that is the cumulative factor library.
    selections = {
        "last_agent_accepted": _last_accepted(trials, numeric_cols),
        "highest_strict_validation_sharpe": _highest_validation_sharpe(df, numeric_cols, periods_per_year),
        "highest_upstream_reported_metric": _highest_upstream_metric(trials, numeric_cols),
    }
    if winner_column is not None:
        if not winner_override_reason:
            raise ValueError("manual --winner-column requires --winner-override-reason so the auditor's selection is itself recorded")
        selections["manual_override"] = (winner_column, f"manual_override: {winner_override_reason}")

    sensitivity = {}
    if sigma_sr is not None and sigma_ci is not None:
        for rule, (selected, why) in selections.items():
            rec = {"column": selected, "inference": why}
            if selected in df.columns:
                try:
                    rec["dsr"] = _dsr_for_column(
                        df, selected, sigma_sr, sigma_ci, raw_n, periods_per_year, len(trial_srs)
                    )
                except ValueError as exc:
                    rec["error"] = str(exc)
            sensitivity[rule] = rec
    else:
        for rule, (selected, why) in selections.items():
            sensitivity[rule] = {"column": selected, "inference": why, "dsr": None}
    out["trial_selection_sensitivity"] = sensitivity

    if coverage < 1.0:
        warnings.append("trial Sharpe dispersion covers only trials with strict-evaluator return series; missing/failed trials remain in raw N")
    warnings.append("raw trial count is a lower bound because alternatives considered inside one RD-Agent LLM call are not observable")
    warnings.append("DSR is a secondary single-trial selection diagnostic; the primary RD-Agent factor audit unit is the cumulative factor library")
    warnings.append("DSR cross-trial dispersion may be conservative because it includes genuine between-strategy heterogeneity as well as search noise")
    out["trial_return_evidence"] = evidence
    out["warnings"] = warnings
    return out


def write_json(report: dict, path: str | Path) -> None:
    Path(path).write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")
