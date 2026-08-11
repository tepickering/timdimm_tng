import numpy as np
import pytest
from astropy.modeling.models import Gaussian2D

from timdimm_tng.analyze_pictures import measure_background, measure_stars


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


def measure_frame(**kwargs):
    """Build a synthetic frame and measure its stars, as every test below needs both."""
    frame = make_test_frame(**kwargs)
    bkg = measure_background(frame)
    return measure_stars(frame, bkg["bkg_rms"])


def test_finds_both_spots_and_sorts_them_by_x():
    stars = measure_frame(positions=[(170, 150), (120, 150)], fluxes=[4.0e4, 1.0e5])
    assert len(stars) == 2
    assert stars[0]["x"] < stars[1]["x"]
    assert stars[0]["x"] == pytest.approx(120.0, abs=0.5)
    assert stars[1]["x"] == pytest.approx(170.0, abs=0.5)


def test_recovers_total_flux_of_each_spot():
    stars = measure_frame(positions=[(120, 150), (170, 150)], fluxes=[1.0e5, 4.0e4])
    assert stars[0]["flux"] == pytest.approx(1.0e5, rel=0.03)
    assert stars[1]["flux"] == pytest.approx(4.0e4, rel=0.03)


def test_recovers_fwhm_as_the_geometric_mean_of_the_axes():
    # a round sigma=3 gaussian has fwhm 2.3548 * 3 = 7.064
    stars = measure_frame(positions=[(120, 150), (170, 150)], fluxes=[1.0e5, 4.0e4], sigma_x=3.0, sigma_y=3.0)
    assert stars[0]["fwhm"] == pytest.approx(7.064, rel=0.05)
    assert stars[0]["sigma_major"] == pytest.approx(3.0, rel=0.05)
    assert stars[0]["sigma_minor"] == pytest.approx(3.0, rel=0.05)


def test_a_round_spot_has_near_zero_ellipticity():
    stars = measure_frame(positions=[(120, 150), (170, 150)], fluxes=[1.0e5, 4.0e4], sigma_x=3.0, sigma_y=3.0)
    assert stars[0]["ellip"] == pytest.approx(0.0, abs=0.05)


def test_a_smeared_spot_reports_its_elongation_and_angle():
    # sigma 6x2 at 30 degrees: true ellipticity 1 - 2/6 = 0.667
    stars = measure_frame(positions=[(120, 150), (170, 150)], fluxes=[1.0e5, 4.0e4],
                          sigma_x=6.0, sigma_y=2.0, theta=30.0)
    assert stars[0]["ellip"] == pytest.approx(0.667, abs=0.08)
    assert stars[0]["pa"] == pytest.approx(30.0, abs=3.0)
    assert stars[0]["sigma_major"] == pytest.approx(6.0, rel=0.10)


def test_the_aperture_radius_grows_for_a_smeared_spot():
    round_stars = measure_frame(positions=[(120, 150), (170, 150)], fluxes=[1.0e5, 4.0e4],
                                sigma_x=3.0, sigma_y=3.0)
    smeared = measure_frame(positions=[(120, 150), (170, 150)], fluxes=[1.0e5, 4.0e4],
                            sigma_x=6.0, sigma_y=2.0, theta=30.0)
    assert smeared[0]["aper_radius"] > round_stars[0]["aper_radius"]


def test_concentration_falls_when_the_spot_is_smeared():
    # same total flux spread over a longer streak must concentrate less light in the peak
    round_stars = measure_frame(positions=[(120, 150), (170, 150)], fluxes=[1.0e5, 4.0e4],
                                sigma_x=3.0, sigma_y=3.0)
    smeared = measure_frame(positions=[(120, 150), (170, 150)], fluxes=[1.0e5, 4.0e4],
                            sigma_x=6.0, sigma_y=2.0, theta=30.0)
    assert smeared[0]["concentration"] < round_stars[0]["concentration"]


def test_gaussian_fit_agrees_with_the_moment_fwhm_on_a_clean_spot():
    stars = measure_frame(positions=[(120, 150), (170, 150)], fluxes=[1.0e5, 4.0e4], sigma_x=3.0, sigma_y=3.0)
    assert stars[0]["fit_ok"]
    assert stars[0]["fwhm_gauss"] == pytest.approx(stars[0]["fwhm"], rel=0.10)


def test_snr_is_background_limited_when_no_egain_is_given():
    frame = make_test_frame([(120, 150), (170, 150)], [1.0e5, 4.0e4])
    bkg = measure_background(frame)
    stars = measure_stars(frame, bkg["bkg_rms"])
    expected = stars[0]["flux"] / (bkg["bkg_rms"] * np.sqrt(stars[0]["n_pix"]))
    assert stars[0]["snr"] == pytest.approx(expected, rel=1e-6)


def test_snr_uses_the_ccd_equation_when_egain_is_known():
    frame = make_test_frame([(120, 150), (170, 150)], [1.0e5, 4.0e4])
    bkg = measure_background(frame)
    egain = 0.421 / 16
    stars = measure_stars(frame, bkg["bkg_rms"], egain=egain)
    flux_e = stars[0]["flux"] * egain
    noise_e = np.sqrt(flux_e + stars[0]["n_pix"] * (bkg["bkg_rms"] * egain) ** 2)
    assert stars[0]["snr"] == pytest.approx(flux_e / noise_e, rel=1e-6)
    # the ccd equation includes source shot noise, so it can never exceed the background-only value
    assert stars[0]["snr"] < stars[0]["flux"] / (bkg["bkg_rms"] * np.sqrt(stars[0]["n_pix"]))


def test_no_detections_on_a_blank_frame():
    frame = make_test_frame([], [])
    bkg = measure_background(frame)
    assert measure_stars(frame, bkg["bkg_rms"]) == []


def test_a_single_spot_returns_one_measurement():
    frame = make_test_frame([(120, 150)], [1.0e5])
    bkg = measure_background(frame)
    assert len(measure_stars(frame, bkg["bkg_rms"])) == 1
