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
    gain_scale,
    probe_peak_headroom,
    select_exptime,
)


# faint-aperture peak in stored counts on the 10-frame probe at PROBE_EXPTIME and CAMERA_GAIN,
# scaled from the measured peak/aperture-sum ratio of 0.0599 on 20260816_3.ser.gz
MEASURED_PROBE_PEAKS = {
    "Shaula": 876,
    "Mimosa": 1170,
    "Fomalhaut": 1252,
    "Achernar": 2596,
    "Canopus": 7566,
    "Sirius": 14672,
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


def test_cloud_attenuation_still_falls_back_to_two_ms():
    """The original behaviour, unchanged: a faint reading lengthens the exposure."""
    assert select_exptime(200) == 0.002


def test_ladder_is_monotonic_in_peak():
    """Brighter must never mean longer. A mis-ordered ladder is the obvious way to break this."""
    peaks = [10, 100, 299, 300, 1000, 3999, 4000, 9999, 10000, 50000]
    exposures = [select_exptime(p) for p in peaks]
    assert exposures == sorted(exposures, reverse=True)


def test_boundaries_are_inclusive_upward():
    """A peak exactly on a bound takes the shorter exposure, so the bounds read as '< bound'."""
    assert select_exptime(299) == 0.002
    assert select_exptime(300) == 0.001
    assert select_exptime(3999) == 0.001
    assert select_exptime(4000) == 0.0005
    assert select_exptime(9999) == 0.0005
    assert select_exptime(10000) == 0.00025


def test_thresholds_scale_with_gain():
    """
    The bounds are raw counts, so they are only meaningful at the gain they were calibrated at.

    At GAIN 140 every reading halves. A lightly attenuated Shaula reads 250 there, which is below the
    unscaled 300 bound and would drop into the 2 ms fallback for no reason other than the gain change.
    """
    assert select_exptime(250, gain=CAMERA_GAIN) == 0.002
    assert select_exptime(250, gain=140) == 0.001


def test_gain_scale_is_unity_at_the_configured_gain():
    assert gain_scale(CAMERA_GAIN) == pytest.approx(1.0)
    # ZWO gain is an index in units of 0.1 dB, so 200 -> 140 is 6 dB, a factor of two in counts
    assert gain_scale(140) == pytest.approx(0.5, rel=0.01)


def test_probe_does_not_saturate_on_the_brightest_target():
    """
    Regression guard on the bug this replaces.

    The old 5 ms probe put Canopus's *bright* spot at ~5140 ADU_12 against a 4095 full scale -- it
    clipped on every Canopus cube, and the threshold reads the faint spot so nothing noticed. The
    probe has to stay short enough that even Sirius comes back unclipped, because a flat-topped PSF
    corrupts the centroid the science ROI is then built around.
    """
    # bright spot is 1/0.46 times the faint one, from the same archived cube
    sirius_bright = MEASURED_PROBE_PEAKS["Sirius"] / 0.46
    assert sirius_bright < FULL_SCALE_COUNTS
    assert probe_peak_headroom(sirius_bright) > 1.5


def test_probe_exposure_is_shorter_than_the_old_five_ms():
    assert PROBE_EXPTIME < 0.005


def test_camera_settings_are_the_ones_in_use_on_sky():
    """Pinned deliberately: these have been in use for a long time and continuity is the point."""
    assert (CAMERA_GAIN, CAMERA_OFFSET) == (200, 1)


def test_ladder_bounds_are_sorted_and_terminated():
    bounds = [bound for bound, _ in EXPOSURE_LADDER]
    assert bounds[-1] is None, "the ladder must have an open-ended top rung"
    finite = bounds[:-1]
    assert finite == sorted(finite)
