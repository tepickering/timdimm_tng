import numpy as np
import pytest
from astropy.modeling.models import Gaussian2D

from timdimm_tng.analyze_pictures import measure_background


def make_test_frame(positions, fluxes, sigma_x=3.0, sigma_y=3.0, theta=0.0,
                    bkg=1550.0, rms=20.0, shape=(300, 300), seed=42):
    """
    Build a synthetic frame of elliptical gaussian spots on a noisy background.

    `theta` is in degrees, counterclockwise from the x axis. `fluxes` are total integrated
    counts, so the assertions downstream can be written against exact known values.
    """
    rng = np.random.default_rng(seed)
    y, x = np.mgrid[0:shape[0], 0:shape[1]]
    image = np.full(shape, float(bkg))
    for (x0, y0), flux in zip(positions, fluxes):
        amplitude = flux / (2.0 * np.pi * sigma_x * sigma_y)
        image += Gaussian2D(amplitude, x0, y0, sigma_x, sigma_y, theta=np.deg2rad(theta))(x, y)
    return image + rng.normal(0.0, rms, shape)


def test_background_recovers_level_and_noise_on_a_blank_frame():
    frame = make_test_frame([], [], bkg=1550.0, rms=20.0)
    bkg = measure_background(frame)
    assert bkg["bkg_median"] == pytest.approx(1550.0, abs=0.5)
    assert bkg["bkg_rms"] == pytest.approx(20.0, rel=0.05)


def test_background_is_not_dragged_up_by_bright_spots():
    # the spots must not bias the background estimate; same level as the blank frame
    frame = make_test_frame([(120, 150), (170, 150)], [1.0e5, 4.0e4], bkg=1550.0, rms=20.0)
    bkg = measure_background(frame)
    assert bkg["bkg_median"] == pytest.approx(1550.0, abs=0.5)
    assert bkg["bkg_rms"] == pytest.approx(20.0, rel=0.05)


def test_background_reports_mean_median_and_rms():
    bkg = measure_background(make_test_frame([], [], bkg=1550.0, rms=20.0))
    assert set(bkg) == {"bkg_mean", "bkg_median", "bkg_rms"}
