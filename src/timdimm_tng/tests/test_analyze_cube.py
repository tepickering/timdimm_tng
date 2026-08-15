"""
Tests for the DIMM cube analysis.

The returned series are compacted past frames where centroiding failed, but ``frame_times`` covers
the whole cube. Without ``frame_index`` there is no way to say when any given sample was taken, and
any lag-based estimator silently shifts the series against each other.
"""

import numpy as np
import pytest

from timdimm_tng.analyze_cube import (
    DIMM_IMAGE_SHAPE,
    MIN_CADENCE_HZ,
    analyze_dimm_cube,
    seeing_is_valid,
)
from timdimm_tng.scintillation import scintillation_stats
from timdimm_tng.tests.ser_helpers import write_ser

SIZE = 60
SPOT_X = (15, 45)
SPOT_Y = 30


def dimm_frames(nframes, bad=(), rng=None, spot_x=SPOT_X, size=SIZE):
    """A cube of Gaussian spots. Frames listed in ``bad`` are flat, so centroiding fails."""
    rng = rng or np.random.default_rng(0)
    y, x = np.mgrid[:size, :size]
    frames = np.zeros((nframes, size, size))
    for i in range(nframes):
        if i in bad:
            frames[i] = 500.0  # a flat frame has no sources at all
            continue
        frame = np.full((size, size), 100.0)
        for cx in spot_x:
            jitter = rng.normal(scale=0.3, size=2)
            frame += 3000.0 * np.exp(
                -((x - cx - jitter[0]) ** 2 + (y - SPOT_Y - jitter[1]) ** 2) / (2 * 2.0**2)
            )
        frames[i] = frame + rng.normal(scale=5.0, size=(size, size))
    return np.clip(frames, 0, 65535).astype(np.uint16)


def test_frame_index_matches_the_kept_series_on_a_clean_cube(tmp_path):
    path = write_ser(tmp_path / "clean.ser", frames=dimm_frames(20))

    results = analyze_dimm_cube(path)

    assert results["N_bad"] == 0
    assert len(results["frame_index"]) == len(results["aperture_fluxes"])
    np.testing.assert_array_equal(results["frame_index"], np.arange(20))


def test_frame_index_omits_exactly_the_frames_that_failed(tmp_path):
    bad = (4, 5, 11)
    path = write_ser(tmp_path / "gappy.ser", frames=dimm_frames(20, bad=bad))

    results = analyze_dimm_cube(path)

    assert results["N_bad"] == len(bad)
    assert len(results["frame_index"]) == len(results["aperture_fluxes"])
    np.testing.assert_array_equal(
        results["frame_index"], [i for i in range(20) if i not in bad]
    )


def test_frame_index_is_integer_typed(tmp_path):
    """It indexes into the cube, so it has to be usable as an index without casting."""
    path = write_ser(tmp_path / "clean.ser", frames=dimm_frames(20))

    results = analyze_dimm_cube(path)

    assert np.issubdtype(results["frame_index"].dtype, np.integer)
    assert results["frame_times"][results["frame_index"]].isot[0].startswith("2024-05-05")


def test_a_one_star_cube_fails_instead_of_reporting_zero_seeing(tmp_path):
    """
    A DIMM measurement needs two apertures. When only one is found, dimm_calc used to fall back to
    per-frame detection, come back with two coincident centroids, and produce a baseline of exactly
    zero -- so the cube reported 0.00 arcsec as a normal result. seeing.csv holds 357 such rows,
    because postcapture's quality gate is `seeing < 10.0` and zero passes it.

    Note it is the *baseline* that has to be rejected, not merely the aperture count. A cube whose
    reference image shows one aperture can still be a real measurement, because dimm_calc re-detects
    per frame at a lower threshold and feeds the recovered positions forward -- two archived cubes
    keep 95% of their frames that way, with a 48 px baseline matching their healthy neighbours.
    """
    path = write_ser(tmp_path / "onestar.ser", frames=dimm_frames(20, spot_x=(30,)))

    with pytest.raises(ValueError, match="usable baseline"):
        analyze_dimm_cube(path)


def test_a_faint_cube_is_rescued_by_per_frame_redetection(tmp_path):
    """
    The other side of that: a cube too faint for the reference image must still be analysed when the
    individual frames can be centroided. Rejecting on aperture count alone would throw these away.
    """
    frames = dimm_frames(60)
    # analyze_dimm_cube builds its reference from the mean of the first five frames, so blanking the
    # second spot there leaves one aperture to start from while every frame still holds both
    frames[:5, :, SPOT_X[1] - 10:] = 100

    with pytest.warns(UserWarning, match="Relying on per-frame"):
        results = analyze_dimm_cube(write_ser(tmp_path / "faint.ser", frames=frames))

    assert len(results["frame_index"]) > 40
    assert np.median(results["baseline_lengths"][0]) == pytest.approx(30.0, abs=2.0)


def test_a_zero_length_baseline_is_a_bad_frame(tmp_path):
    """
    Defence in depth for the same bug, one layer down. Two apertures at the same place are not a
    measurement no matter how they were arrived at, so the frame must be rejected rather than
    contribute a zero to the baseline series the seeing is computed from.
    """
    from photutils.aperture import CircularAperture

    from timdimm_tng.analyze_cube import dimm_calc

    frame = dimm_frames(1)[0].astype(float)
    coincident = CircularAperture([(15.0, 30.0), (15.0, 30.0)], r=11)

    assert dimm_calc(frame, coincident) is None


def test_a_starless_cube_says_so_rather_than_leaking_a_photutils_error(tmp_path):
    """
    Six archived cubes fail with `TypeError: segmentation_image must be a SegmentationImage`, which
    is SourceFinder returning None for a faint target leaking through two call frames.
    """
    path = write_ser(tmp_path / "blank.ser", frames=dimm_frames(20, bad=range(20)))

    with pytest.raises(ValueError, match="[Nn]o sources"):
        analyze_dimm_cube(path)


def test_the_results_dict_feeds_scintillation_stats(tmp_path):
    """
    The one place the real analyze_dimm_cube output meets the estimators. Every other scintillation
    test builds the dict by hand, and postcapture.py -- where the two actually meet in production --
    talks to a camera and cannot be tested, so a shape mistake here would otherwise reach the
    telescope before anything caught it.
    """
    path = write_ser(tmp_path / "feeds.ser", frames=dimm_frames(120, bad=(7, 8, 60)))

    stats = scintillation_stats(analyze_dimm_cube(path))

    assert stats["n_kept"] == 117
    assert stats["n_frames"] == 120
    # two identical synthetic spots, so the throughput is 1 and there is nothing scintillating
    assert stats["throughput"] == pytest.approx(1.0, abs=0.02)
    assert stats["scint_index_raw"] == pytest.approx(0.0, abs=1e-3)
    assert stats["cadence_hz"] == pytest.approx(303.0, rel=0.02)


@pytest.mark.parametrize("cadence", [MIN_CADENCE_HZ, 253.2, 299.25, 381.0])
def test_any_rate_fast_enough_to_freeze_the_seeing_is_valid(cadence):
    """
    What matters is the exposure time, not one nominal rate. 2023-06-24 ran at 381 Hz and 2024-04-30
    at 253 Hz; both sit on the throughput decline curve with sensible seeing, so both are real data.
    """
    assert seeing_is_valid(DIMM_IMAGE_SHAPE, cadence)


@pytest.mark.parametrize("cadence", [10.5, 43.9, 120.2, 199.9])
def test_too_slow_an_exposure_is_not_valid_for_seeing(cadence):
    """
    A long exposure averages over the image motion, so the baseline scatter is no longer seeing. The
    archive's 10.5 Hz test cubes are where the surviving sub-arcsecond values come from -- 12 of
    them, between 0.13 and 0.50 arcsec, below anything the site has ever delivered.

    A production cube landing here is a hardware alert in its own right: it means the camera
    negotiated a USB 2.x bus and is not running at the rate it was configured for.
    """
    assert not seeing_is_valid(DIMM_IMAGE_SHAPE, cadence)


def test_a_different_roi_is_not_valid_for_seeing():
    """The commissioning cubes are 443x416; the plate scale the seeing depends on assumes 400x400."""
    assert not seeing_is_valid((443, 416), 299.25)


def test_an_unknown_cadence_is_not_valid_for_seeing():
    """Constant SER timestamps give a NaN cadence, which is not evidence that the rate was right."""
    assert not seeing_is_valid(DIMM_IMAGE_SHAPE, float("nan"))


def test_a_small_cube_is_flagged_invalid_but_still_measured(tmp_path):
    """
    The flag is advisory, not fatal: throughput and the flux statistics are fine on a cube that is
    the wrong shape for seeing, so the analysis must still run and return its numbers.
    """
    path = write_ser(tmp_path / "small.ser", frames=dimm_frames(20))

    results = analyze_dimm_cube(path)

    assert results["seeing_valid"] is False
    assert results["image_shape"] == (SIZE, SIZE)
    assert np.isfinite(results["seeing"].value)


def test_a_production_shaped_cube_is_flagged_valid(tmp_path):
    frames = dimm_frames(20, spot_x=(150, 250), size=400)
    path = write_ser(tmp_path / "production.ser", frames=frames)

    results = analyze_dimm_cube(path)

    assert results["image_shape"] == DIMM_IMAGE_SHAPE
    assert results["cadence_hz"] == pytest.approx(303.0, rel=0.02)
    assert results["seeing_valid"] is True
