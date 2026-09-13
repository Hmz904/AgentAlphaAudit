import numpy as np
import pytest

from agent_alpha_audit.audit.statistics import (
    cross_trial_sharpe_std,
    deflated_sharpe_probability,
    effective_number_of_trials,
    winner_return_moments,
)


def test_effective_trials_bounds_and_correlation():
    rng = np.random.default_rng(1)
    x = rng.normal(size=(500, 5))
    neff_ind = effective_number_of_trials(x)
    base = rng.normal(size=(500, 1))
    y = np.repeat(base, 5, axis=1) + 0.01 * rng.normal(size=(500, 5))
    neff_corr = effective_number_of_trials(y)
    assert 1 <= neff_corr < neff_ind <= 5


def test_dsr_uses_cross_trial_sharpe_dispersion_and_penalizes_more_trials():
    p1 = deflated_sharpe_probability(
        1.5, 252, 1, trial_sharpe_std_annualized=0.8, skewness=-0.3, kurtosis_value=4.5
    ).probability
    p100 = deflated_sharpe_probability(
        1.5, 252, 100, trial_sharpe_std_annualized=0.8, skewness=-0.3, kurtosis_value=4.5
    ).probability
    assert p100 < p1


def test_dsr_refuses_optimistic_gaussian_moment_defaults():
    with pytest.raises(ValueError):
        deflated_sharpe_probability(1.5, 252, 10, trial_sharpe_std_annualized=0.8)


def test_cross_trial_dispersion_and_winner_moments_are_data_driven():
    rng = np.random.default_rng(42)
    x = rng.normal(size=(400, 4)) * 0.01 + np.array([0.0000, 0.0003, 0.0006, 0.0010])
    sigma, srs = cross_trial_sharpe_std(x)
    sk, ku, n = winner_return_moments(x[:, 3])
    assert sigma == pytest.approx(np.std(srs, ddof=1))
    assert n == 400
    assert np.isfinite(sk) and np.isfinite(ku)


def test_dsr_probability_interval_propagates_sigma_uncertainty():
    from agent_alpha_audit.audit.statistics import deflated_sharpe_probability_interval
    lo,hi=deflated_sharpe_probability_interval(
        annualized_sharpe_value=1.5,
        n_observations=252,
        n_trials=30,
        sigma_ci=(0.0,1.5),
        periods_per_year=252,
        skewness=0.0,
        kurtosis_value=3.0,
    )
    assert 0 <= lo <= hi <= 1
    assert hi > lo
