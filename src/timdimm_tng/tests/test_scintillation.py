"""
Tests for the scintillation and time-constant estimators.

Everything here runs on synthetic series with analytically known answers. The two estimator traps
these guard against are both recorded in docs/scintillation_logging_notes.md: taking the mean of
per-frame ratios instead of the ratio of means, and correlating by position in the compacted array
instead of by cube frame index.
"""

import numpy as np
import pytest

from timdimm_tng.scintillation import assign_apertures, throughput


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
