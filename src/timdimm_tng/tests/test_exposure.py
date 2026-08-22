"""
Tests for the acquisition exposure ladder.

The numbers the ladder is calibrated against come from three nights on sky (2026-08-17 to 08-19)
plus a direct peak measurement on an archived cube; see the module docstring of
``timdimm_tng.exposure`` for where each one comes from.
"""

import pytest

from timdimm_tng.exposure import (
    CAMERA_GAIN,
    CAMERA_OFFSET,
    EXPOSURE_LADDER,
    FULL_SCALE_COUNTS,
    PROBE_EXPTIME,
    PROBE_THRESHOLD,
    gain_scale,
    select_exptime,
)


# faint-aperture peak in stored counts on the probe at PROBE_EXPTIME and CAMERA_GAIN, scaled from
# the measured peak/aperture-sum ratio of 0.0599 on 20260816_3.ser.gz. Sirius is clipped here: at
# 5 ms its faint spot passes full scale, so it reads the ceiling rather than a true peak.
MEASURED_PROBE_PEAKS = {
    "Shaula": 4380,
    "Mimosa": 5850,
    "Fomalhaut": 6260,
    "Achernar": 12980,
    "Canopus": 37830,
    "Sirius": FULL_SCALE_COUNTS,
}


@pytest.mark.parametrize(
    "target, expected",
    [
        ("Shaula", 0.001),
        ("Mimosa", 0.001),
        ("Fomalhaut", 0.001),
        ("Achernar", 0.001),
        ("Canopus", 0.0005),
        ("Sirius", 0.00025),
    ],
)
def test_real_targets_land_on_their_intended_tier(target, expected):
    """The whole point of the ladder: these six targets, these six exposures."""
    assert select_exptime(MEASURED_PROBE_PEAKS[target]) == expected


def test_a_clipped_faint_spot_takes_the_shortest_exposure():
    """
    The probe is expected to clip on bright targets, so the ladder has to fail in a safe direction.

    A faint aperture that has reached full scale carries no information about how much brighter the
    target really is, and anything that saturates it wants the shortest science exposure available.
    """
    assert select_exptime(FULL_SCALE_COUNTS) == min(exp for _, exp in EXPOSURE_LADDER)


def test_cloud_attenuation_still_falls_back_to_two_ms():
    """
    The original behaviour, preserved exactly.

    Before the ladder this was a bare ``if faint_peak < 1500: exptime = 0.002``, on a probe at this
    same 5 ms. Keeping the bound at its original value in its original units is what makes the
    proven cloud fallback survive the rewrite.
    """
    assert select_exptime(1000) == 0.002
    assert select_exptime(1499) == 0.002
    assert select_exptime(1500) == 0.001


def test_science_default_is_one_millisecond():
    """1 ms is the default the ladder moves around, not a rung reached only in special cases."""
    for peak in (1500, 5000, 12980, 19999):
        assert select_exptime(peak) == 0.001


def test_ladder_is_monotonic_in_peak():
    """Brighter must never mean longer. A mis-ordered ladder is the obvious way to break this."""
    peaks = [10, 1000, 1499, 1500, 10000, 19999, 20000, 49999, 50000, 65520]
    exposures = [select_exptime(p) for p in peaks]
    assert exposures == sorted(exposures, reverse=True)


def test_boundaries_are_inclusive_upward():
    """A peak exactly on a bound takes the shorter exposure, so the bounds read as '< bound'."""
    assert select_exptime(1499) == 0.002
    assert select_exptime(1500) == 0.001
    assert select_exptime(19999) == 0.001
    assert select_exptime(20000) == 0.0005
    assert select_exptime(49999) == 0.0005
    assert select_exptime(50000) == 0.00025


def test_thresholds_scale_with_gain():
    """
    The bounds are raw counts, so they are only meaningful at the gain they were calibrated at.

    At GAIN 140 every reading halves. A lightly attenuated Shaula reads 1250 there, which is below
    the unscaled 1500 bound and would drop into the 2 ms fallback for no reason other than the gain
    change.
    """
    assert select_exptime(1250, gain=CAMERA_GAIN) == 0.002
    assert select_exptime(1250, gain=140) == 0.001


def test_gain_scale_is_unity_at_the_configured_gain():
    assert gain_scale(CAMERA_GAIN) == pytest.approx(1.0)
    # ZWO gain is an index in units of 0.1 dB, so 200 -> 140 is 6 dB, a factor of two in counts
    assert gain_scale(140) == pytest.approx(0.5, rel=0.01)


def test_probe_stays_at_five_milliseconds():
    """
    Regression guard on the 2026-08 outage.

    The probe was shortened to 1 ms to stop bright targets clipping it. Clipping there is harmless
    -- a saturated star still centroids well enough to place the ROI -- but the length is not: it is
    what averages over scintillation and carries signal-to-noise through cloud, and PROBE_THRESHOLD
    is in units of sigma, so dividing the exposure by five divided the detection margin by five and
    the probe stopped finding apertures at all on the fainter half of the schedule.
    """
    assert PROBE_EXPTIME == 0.005
    assert PROBE_THRESHOLD == 35.0


def test_camera_settings_are_the_ones_in_use_on_sky():
    """Pinned deliberately: these have been in use for a long time and continuity is the point."""
    assert (CAMERA_GAIN, CAMERA_OFFSET) == (200, 1)


def test_ladder_bounds_are_sorted_and_terminated():
    bounds = [bound for bound, _ in EXPOSURE_LADDER]
    assert bounds[-1] is None, "the ladder must have an open-ended top rung"
    finite = bounds[:-1]
    assert finite == sorted(finite)
