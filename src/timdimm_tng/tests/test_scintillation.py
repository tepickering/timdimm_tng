"""
Tests for the scintillation and time-constant estimators.

Everything here runs on synthetic series with analytically known answers. The two estimator traps
these guard against are both recorded in docs/scintillation_logging_notes.md: taking the mean of
per-frame ratios instead of the ratio of means, and correlating by position in the compacted array
instead of by cube frame index.
"""

import astropy.units as u
import numpy as np
import pytest
from astropy.time import Time

from timdimm_tng.scintillation import (
    assign_apertures,
    fit_tau,
    flux_ratio,
    lag_autocorr,
    median_dt,
    scint_index,
    throughput,
)


def two_identical_apertures(scatter, n=200000, seed=0):
    """
    Two apertures with the same true flux, differing only by independent noise.

    The noise is lognormal, not Gaussian. Scintillation is multiplicative and a measured flux is
    never negative, but more to the point a Gaussian denominator can approach zero, which makes the
    mean of the per-frame ratios a heavy-tailed statistic with no stable value -- it would move with
    the seed and the sample size, and the test would be measuring nothing.

    With lognormal noise of fractional scatter s, the naive estimator has the exact expectation
    ``1 + s**2``, which is what makes the bias assertable rather than merely observable.
    """
    rng = np.random.default_rng(seed)
    true = 1000.0
    sigma = np.sqrt(np.log(1.0 + scatter**2))
    a = true * rng.lognormal(mean=-0.5 * sigma**2, sigma=sigma, size=n)
    b = true * rng.lognormal(mean=-0.5 * sigma**2, sigma=sigma, size=n)
    return np.column_stack([a, b])


@pytest.mark.parametrize("scatter", [0.1, 0.3, 0.5])
def test_throughput_of_two_identical_apertures_is_one(scatter):
    bright, faint = assign_apertures(two_identical_apertures(scatter))

    assert throughput(bright, faint) == pytest.approx(1.0, abs=0.02)


@pytest.mark.parametrize("scatter", [0.1, 0.3, 0.5])
def test_the_naive_estimator_really_is_biased(scatter):
    """
    Not a test of our code -- a test that the bias we are avoiding is real, and that it grows as
    the square of the frame-to-frame scatter. Two *identical* apertures, so the correct answer is
    1.0 and every part of the excess is estimator bias.
    """
    fluxes = two_identical_apertures(scatter)
    mean_of_ratios = np.mean(fluxes[:, 1] / fluxes[:, 0])

    assert mean_of_ratios == pytest.approx(1.0 + scatter**2, rel=0.02)
    assert mean_of_ratios > 1.0 + 0.5 * scatter**2


def test_the_faint_aperture_is_found_when_it_is_at_index_zero():
    fluxes = np.column_stack([np.full(500, 300.0), np.full(500, 1000.0)])

    bright, faint = assign_apertures(fluxes)

    assert bright[0] == 1000.0
    assert faint[0] == 300.0


def test_the_faint_aperture_is_found_when_it_is_at_index_one():
    """find_apertures sorts by x centroid, so the prism's index follows the camera orientation."""
    fluxes = np.column_stack([np.full(500, 1000.0), np.full(500, 300.0)])

    bright, faint = assign_apertures(fluxes)

    assert bright[0] == 1000.0
    assert faint[0] == 300.0


def test_assignment_survives_frames_that_individually_invert_the_ordering():
    rng = np.random.default_rng(1)
    n = 4000
    a = 1000.0 + 400.0 * rng.normal(size=n)   # bright on average, but noisy enough to cross over
    b = 700.0 + 400.0 * rng.normal(size=n)
    fluxes = np.column_stack([a, b])
    assert np.mean(b > a) > 0.2, "the test data must actually contain inversions"

    bright, faint = assign_apertures(fluxes)

    assert np.median(bright) > np.median(faint)
    assert throughput(bright, faint) == pytest.approx(0.7, abs=0.03)


def test_throughput_is_nan_when_a_mean_flux_is_not_positive():
    bright = np.full(500, 1000.0)
    faint = np.zeros(500)

    assert np.isnan(throughput(bright, faint))


def test_a_constant_ratio_has_no_scintillation():
    assert scint_index(np.full(1000, 0.75)) == pytest.approx(0.0, abs=1e-12)


def test_the_index_recovers_a_known_normalised_variance():
    """A ratio with 20% fractional scatter has a normalised variance of 0.04."""
    rng = np.random.default_rng(3)
    ratio = 0.75 * (1.0 + 0.2 * rng.normal(size=200000))

    assert scint_index(ratio) == pytest.approx(0.04, rel=0.02)


def test_the_index_is_scale_free():
    """Normalising by the squared mean makes it independent of the absolute flux level."""
    rng = np.random.default_rng(4)
    ratio = 0.75 * (1.0 + 0.2 * rng.normal(size=50000))

    assert scint_index(ratio) == pytest.approx(scint_index(1000.0 * ratio), rel=1e-9)


def test_flux_ratio_is_faint_over_bright_per_frame():
    bright = np.array([100.0, 200.0, 400.0])
    faint = np.array([50.0, 50.0, 100.0])

    np.testing.assert_allclose(flux_ratio(bright, faint), [0.5, 0.25, 0.25])


def test_the_index_is_nan_when_the_mean_ratio_is_not_positive():
    assert np.isnan(scint_index(np.zeros(500)))


def ar1(n, rho, rng):
    """A first-order autoregressive series: corr at lag k is rho**k, unit variance."""
    x = np.zeros(n)
    noise = rng.normal(size=n)
    scale = np.sqrt(1.0 - rho**2)
    for i in range(1, n):
        x[i] = rho * x[i - 1] + scale * noise[i]
    return x


def test_white_noise_is_uncorrelated_at_lag_one():
    rng = np.random.default_rng(5)
    x = rng.normal(size=20000)

    rho, npairs = lag_autocorr(x, np.arange(20000), 1)

    assert abs(rho) < 0.03
    assert npairs == 19999


def test_a_slow_series_is_strongly_correlated_at_lag_one():
    rng = np.random.default_rng(6)
    x = ar1(20000, 0.95, rng)

    rho, _ = lag_autocorr(x, np.arange(20000), 1)

    assert rho == pytest.approx(0.95, abs=0.02)


def test_correlation_decays_as_rho_to_the_lag():
    rng = np.random.default_rng(7)
    x = ar1(50000, 0.8, rng)
    index = np.arange(50000)

    for lag in (1, 2, 3, 4):
        rho, _ = lag_autocorr(x, index, lag)
        assert rho == pytest.approx(0.8**lag, abs=0.02)


def test_gaps_are_left_as_gaps_rather_than_closed_up():
    """
    The whole point. Delete 20% of the frames: correlating by array position would treat samples
    two or three frames apart as adjacent and drag the lag-1 correlation down.
    """
    rng = np.random.default_rng(8)
    full = ar1(50000, 0.8, rng)
    keep = rng.random(50000) > 0.2
    index = np.arange(50000)[keep]
    x = full[keep]

    rho, npairs = lag_autocorr(x, index, 1)
    naive = np.corrcoef(x[:-1], x[1:])[0, 1]

    assert rho == pytest.approx(0.8, abs=0.02)
    assert npairs == pytest.approx(0.64 * 50000, rel=0.05)

    # Array-adjacent pairs are really k frames apart with probability 0.8 * 0.2**(k-1), so the naive
    # estimator converges to sum(0.8 * 0.2**(k-1) * 0.8**k) = 0.64 / 0.84 = 0.762. Biased low, and
    # by a knowable amount -- that it is only 0.04 is why this error is easy to miss on real data.
    assert naive == pytest.approx(0.64 / 0.84, abs=0.01)
    assert naive < rho


def test_pair_counts_match_what_the_index_implies():
    x = np.array([1.0, 2.0, 3.0, 4.0])
    index = np.array([0, 1, 5, 6])

    assert lag_autocorr(x, index, 1)[1] == 2   # (0,1) and (5,6)
    assert lag_autocorr(x, index, 4)[1] == 1   # (1,5) only -- there is no frame 2 to pair with 6
    assert lag_autocorr(x, index, 3)[1] == 0   # nothing is exactly 3 apart


def test_too_few_pairs_gives_nan_but_still_reports_the_count():
    x = np.array([1.0, 2.0, 3.0, 4.0])
    index = np.array([0, 1, 5, 6])

    rho, npairs = lag_autocorr(x, index, 1)

    assert np.isnan(rho)
    assert npairs == 2


DT = 3.342e-3  # the 299 Hz cadence, in seconds


def test_fit_recovers_a_known_time_constant():
    """rho at lag 1 is exp(-dt/tau), so a tau of 5 ms at 299 Hz gives rho = 0.513."""
    tau = 5.0e-3
    rng = np.random.default_rng(9)
    x = ar1(40000, np.exp(-DT / tau), rng)

    assert fit_tau(x, np.arange(40000), DT) == pytest.approx(tau, rel=0.05)


def test_fit_recovers_the_same_tau_from_a_punctured_series():
    """
    The test that proves the gaps are handled. Same underlying process, 20% of frames deleted --
    the answer must not move.
    """
    tau = 5.0e-3
    rng = np.random.default_rng(10)
    full = ar1(40000, np.exp(-DT / tau), rng)
    keep = rng.random(40000) > 0.2
    index = np.arange(40000)[keep]

    contiguous = fit_tau(full, np.arange(40000), DT)
    punctured = fit_tau(full[keep], index, DT)

    assert punctured == pytest.approx(tau, rel=0.06)
    assert punctured == pytest.approx(contiguous, rel=0.06)


def test_fit_is_nan_for_a_series_with_no_decay_to_fit():
    rng = np.random.default_rng(11)
    x = rng.normal(size=40000)

    assert np.isnan(fit_tau(x, np.arange(40000), DT))


def test_fit_is_nan_when_too_few_frames_survived():
    rng = np.random.default_rng(12)
    x = ar1(20, 0.8, rng)

    assert np.isnan(fit_tau(x, np.arange(20), DT))


def test_a_longer_time_constant_fits_larger():
    rng = np.random.default_rng(13)
    slow = ar1(40000, np.exp(-DT / 20.0e-3), rng)
    fast = ar1(40000, np.exp(-DT / 5.0e-3), rng)
    index = np.arange(40000)

    assert fit_tau(slow, index, DT) > fit_tau(fast, index, DT)


def test_median_dt_uses_the_measured_intervals_not_the_nominal_rate():
    """Cadence jitter is small at 299 Hz but the archive spans a factor of 30 in frame rate."""
    rng = np.random.default_rng(14)
    ticks = np.cumsum(rng.normal(loc=DT, scale=0.0002, size=5000))
    times = Time("2024-05-05T01:57:00", scale="utc") + ticks * u.s

    assert median_dt(times) == pytest.approx(DT, rel=0.01)


def test_median_dt_is_nan_when_the_timestamp_trailer_is_missing():
    """A truncated cube loses its timestamps entirely -- ser.py returns an empty Time array."""
    assert np.isnan(median_dt(Time([], format="isot", scale="utc")))
