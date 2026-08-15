"""
Tests for the DIMM cube analysis.

The returned series are compacted past frames where centroiding failed, but ``frame_times`` covers
the whole cube. Without ``frame_index`` there is no way to say when any given sample was taken, and
any lag-based estimator silently shifts the series against each other.
"""

import numpy as np

from timdimm_tng.analyze_cube import analyze_dimm_cube
from timdimm_tng.tests.ser_helpers import write_ser

SIZE = 60
SPOT_X = (15, 45)
SPOT_Y = 30


def dimm_frames(nframes, bad=(), rng=None):
    """A cube of two Gaussian spots. Frames listed in ``bad`` are flat, so centroiding fails."""
    rng = rng or np.random.default_rng(0)
    y, x = np.mgrid[:SIZE, :SIZE]
    frames = np.zeros((nframes, SIZE, SIZE))
    for i in range(nframes):
        if i in bad:
            frames[i] = 500.0  # a flat frame has no sources at all
            continue
        frame = np.full((SIZE, SIZE), 100.0)
        for cx in SPOT_X:
            jitter = rng.normal(scale=0.3, size=2)
            frame += 3000.0 * np.exp(
                -((x - cx - jitter[0]) ** 2 + (y - SPOT_Y - jitter[1]) ** 2) / (2 * 2.0**2)
            )
        frames[i] = frame + rng.normal(scale=5.0, size=(SIZE, SIZE))
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
