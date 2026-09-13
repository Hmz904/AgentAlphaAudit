from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np
from scipy.stats import kurtosis, norm, skew

EULER_GAMMA = 0.5772156649015329


@dataclass
class DeflatedSharpeResult:
    observed_sharpe: float
    n_trials: float
    trial_sharpe_std: float
    benchmark_sharpe: float
    winner_skew: float
    winner_kurtosis: float
    probability: float


def annualized_sharpe(returns: np.ndarray, periods_per_year: int = 252) -> float:
    x = np.asarray(returns, dtype=float)
    x = x[np.isfinite(x)]
    if x.size < 3:
        raise ValueError("need at least 3 finite observations")
    sd = float(np.std(x, ddof=1))
    if sd <= 0:
        raise ValueError("return standard deviation must be positive")
    return float(np.mean(x) / sd * math.sqrt(periods_per_year))


def winner_return_moments(returns: np.ndarray) -> tuple[float, float, int]:
    x = np.asarray(returns, dtype=float)
    x = x[np.isfinite(x)]
    if x.size < 4:
        raise ValueError("need at least 4 finite observations for skew/kurtosis")
    return (
        float(skew(x, bias=False)),
        float(kurtosis(x, fisher=False, bias=False)),
        int(x.size),
    )


def cross_trial_sharpe_std(returns: np.ndarray, periods_per_year: int = 252) -> tuple[float, np.ndarray]:
    """Cross-sectional SD of candidate Sharpe ratios, as required by DSR.

    ``returns`` has shape (time, trials). Columns with fewer than three finite
    observations or zero variance are excluded from the Sharpe dispersion estimate.
    """
    x = np.asarray(returns, dtype=float)
    if x.ndim != 2 or x.shape[1] == 0:
        raise ValueError("returns must have shape (time, trials)")
    vals: list[float] = []
    for j in range(x.shape[1]):
        col = x[:, j]
        try:
            vals.append(annualized_sharpe(col, periods_per_year=periods_per_year))
        except ValueError:
            continue
    arr = np.asarray(vals, dtype=float)
    if arr.size < 2:
        raise ValueError("need at least two valid trial return series to estimate cross-trial Sharpe dispersion")
    return float(np.std(arr, ddof=1)), arr


def effective_number_of_trials(returns: np.ndarray) -> float:
    """Participation-ratio effective dimension of a trial-return matrix.

    This is a secondary dependence diagnostic only. It must not replace the raw
    captured proposal count in headline trial accounting or DSR reporting.
    """
    x = np.asarray(returns, dtype=float)
    if x.ndim != 2 or x.shape[1] == 0:
        raise ValueError("returns must have shape (time, trials)")
    if x.shape[1] == 1:
        return 1.0
    keep = np.nanstd(x, axis=0) > 0
    x = x[:, keep]
    if x.shape[1] <= 1:
        return 1.0
    # Fill each column's missing values with its own mean.
    means = np.nanmean(x, axis=0)
    inds = np.where(~np.isfinite(x))
    if inds[0].size:
        x = x.copy()
        x[inds] = means[inds[1]]
    corr = np.corrcoef(x, rowvar=False)
    corr = np.atleast_2d(corr)
    vals = np.linalg.eigvalsh(corr)
    vals = np.clip(vals, 0.0, None)
    denom = float(np.square(vals).sum())
    if denom <= 0:
        return 1.0
    neff = float(vals.sum() ** 2 / denom)
    return max(1.0, min(neff, float(x.shape[1])))



def bootstrap_std_ci(values: np.ndarray, n_boot: int = 2000, confidence: float = 0.95, seed: int = 20260911) -> tuple[float, float]:
    """Bootstrap CI for the cross-trial Sharpe dispersion.

    Resamples trial Sharpe estimates, not time observations. This quantifies the
    finite-search uncertainty in sigma_SR and is intentionally reported beside DSR.
    """
    x = np.asarray(values, dtype=float)
    x = x[np.isfinite(x)]
    if x.size < 3:
        raise ValueError("need at least three trial Sharpe estimates for a bootstrap CI")
    rng = np.random.default_rng(seed)
    idx = rng.integers(0, x.size, size=(n_boot, x.size))
    boots = np.std(x[idx], axis=1, ddof=1)
    alpha = (1.0 - confidence) / 2.0
    return float(np.quantile(boots, alpha)), float(np.quantile(boots, 1.0 - alpha))

def _expected_max_standard_normal(n_trials: float) -> float:
    if n_trials <= 1:
        return 0.0
    n = max(float(n_trials), 1.000001)
    a = norm.ppf(1.0 - 1.0 / n)
    b = norm.ppf(1.0 - 1.0 / (n * math.e))
    return float((1.0 - EULER_GAMMA) * a + EULER_GAMMA * b)


def deflated_sharpe_probability(
    annualized_sharpe_value: float,
    n_observations: int,
    n_trials: float,
    trial_sharpe_std_annualized: float,
    periods_per_year: int = 252,
    skewness: float | None = None,
    kurtosis_value: float | None = None,
) -> DeflatedSharpeResult:
    """Bailey–López de Prado style Deflated Sharpe diagnostic.

    The benchmark dispersion is the *cross-sectional standard deviation of Sharpe
    ratios across the observed trials*, not ``1/sqrt(T-1)``. Winner skewness and
    Pearson kurtosis are required rather than silently defaulted to Gaussian values.

    ``n_trials`` should be the raw search-count lower bound for the headline audit.
    A dependence-adjusted effective count, if reported at all, is secondary.
    """
    if n_observations < 4:
        raise ValueError("n_observations must be >= 4")
    if periods_per_year <= 0:
        raise ValueError("periods_per_year must be positive")
    if n_trials < 1:
        raise ValueError("n_trials must be >= 1")
    if trial_sharpe_std_annualized < 0 or not math.isfinite(trial_sharpe_std_annualized):
        raise ValueError("trial_sharpe_std_annualized must be finite and non-negative")
    if skewness is None or kurtosis_value is None:
        raise ValueError("winner skewness and kurtosis must be supplied; optimistic Gaussian defaults are disabled")

    sr = float(annualized_sharpe_value) / math.sqrt(periods_per_year)
    sigma_sr_ann = float(trial_sharpe_std_annualized)
    benchmark_ann = sigma_sr_ann * _expected_max_standard_normal(n_trials)
    sr0 = benchmark_ann / math.sqrt(periods_per_year)

    # PSR denominator uses the selected strategy's return moments and observed SR.
    denom2 = 1.0 - float(skewness) * sr + ((float(kurtosis_value) - 1.0) / 4.0) * sr * sr
    denom = math.sqrt(max(denom2, 1e-12))
    z = (sr - sr0) * math.sqrt(n_observations - 1.0) / denom
    prob = float(norm.cdf(z))
    return DeflatedSharpeResult(
        observed_sharpe=float(annualized_sharpe_value),
        n_trials=float(n_trials),
        trial_sharpe_std=sigma_sr_ann,
        benchmark_sharpe=float(benchmark_ann),
        winner_skew=float(skewness),
        winner_kurtosis=float(kurtosis_value),
        probability=prob,
    )


def deflated_sharpe_probability_interval(
    annualized_sharpe_value: float,
    n_observations: int,
    n_trials: float,
    sigma_ci: tuple[float, float],
    periods_per_year: int,
    skewness: float,
    kurtosis_value: float,
) -> tuple[float, float]:
    """Propagate a sigma_SR interval into a DSR-probability interval.

    DSR probability is monotone non-increasing in sigma_SR because the expected
    maximum Sharpe benchmark rises with cross-trial dispersion. The lower
    probability endpoint therefore uses sigma_hi; sigma_lo may legitimately be 0
    in tiny bootstrap samples.
    """
    lo, hi = map(float, sigma_ci)
    if lo < 0 or hi < lo:
        raise ValueError("invalid sigma_SR interval")
    p_lo = deflated_sharpe_probability(
        annualized_sharpe_value, n_observations, n_trials, hi, periods_per_year, skewness, kurtosis_value
    ).probability
    p_hi = deflated_sharpe_probability(
        annualized_sharpe_value, n_observations, n_trials, lo, periods_per_year, skewness, kurtosis_value
    ).probability
    return float(min(p_lo, p_hi)), float(max(p_lo, p_hi))
