import numpy as np
import pytest
from astropy.io import fits
from astropy.modeling.models import Gaussian2D

from timdimm_tng.analyze_pictures import analyze_image, measure_background, measure_stars


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


def write_frame(tmp_path, frame, name="Achernar_Light_001.fits", **header_kwargs):
    """Write a synthetic frame to a FITS file with a realistic header."""
    header = fits.Header()
    header["INSTRUME"] = "ZWO CCD ASI432MM"
    header["EXPTIME"] = 0.001
    header["CCD-TEMP"] = 22.0
    header["AIRMASS"] = 1.4
    header["OBJCTAZ"] = 140.6
    header["OBJCTALT"] = 45.3
    header["RA"] = 24.42
    header["DEC"] = -57.23
    header["PIERSIDE"] = "WEST"
    header["EQUINOX"] = 2000
    header["DATE-OBS"] = "2025-10-09T19:19:29.279"
    header["GAIN"] = 350
    header["OFFSET"] = 10
    header["OBJECT"] = "Achernar"
    header["SCALE"] = 0.74268
    header["SITELONG"] = 20.94556
    for key, value in header_kwargs.items():
        header[key] = value
    path = tmp_path / "Achernar" / "Light"
    path.mkdir(parents=True, exist_ok=True)
    # store as 12-bit data left-shifted into uint16, as the driver does
    counts = (np.clip(frame, 0, None) / 16).astype(np.uint16) * 16
    fits.PrimaryHDU(counts, header=header).writeto(path / name)
    return path / name


def test_row_carries_the_header_subset(tmp_path):
    path = write_frame(tmp_path, make_test_frame([(120, 150), (170, 150)], [1.0e5, 4.0e4]))
    row = analyze_image(path, root=tmp_path)
    assert row["object"] == "Achernar"
    assert row["pierside"] == "WEST"
    assert row["exptime"] == pytest.approx(0.001)
    assert row["gain"] == 350
    assert row["date_obs"] == "2025-10-09T19:19:29.279"
    assert row["airmass"] == pytest.approx(1.4)


def test_row_records_provenance_relative_to_the_root(tmp_path):
    path = write_frame(tmp_path, make_test_frame([(120, 150), (170, 150)], [1.0e5, 4.0e4]))
    row = analyze_image(path, root=tmp_path)
    assert row["filename"] == "Achernar/Light/Achernar_Light_001.fits"
    assert row["target"] == "Achernar"


def test_row_reports_separation_in_pixels_and_arcsec(tmp_path):
    path = write_frame(tmp_path, make_test_frame([(120, 150), (170, 150)], [1.0e5, 4.0e4]))
    row = analyze_image(path, root=tmp_path)
    assert row["n_stars"] == 2
    assert row["sep_pix"] == pytest.approx(50.0, abs=0.5)
    assert row["sep_arcsec"] == pytest.approx(50.0 * 0.74268, abs=0.5)
    assert row["sep_pa"] == pytest.approx(0.0, abs=2.0)


def test_row_reports_the_flux_ratio_for_later_aperture_identification(tmp_path):
    path = write_frame(tmp_path, make_test_frame([(120, 150), (170, 150)], [1.0e5, 4.0e4]))
    row = analyze_image(path, root=tmp_path)
    assert row["flux_ratio"] == pytest.approx(2.5, rel=0.05)


def test_row_uses_the_ccd_equation_for_a_recognized_camera(tmp_path):
    path = write_frame(tmp_path, make_test_frame([(120, 150), (170, 150)], [1.0e5, 4.0e4]))
    row = analyze_image(path, root=tmp_path)
    assert row["snr_method"] == "ccd"
    assert row["bitshift"] == 16
    assert row["egain"] == pytest.approx(0.421 / 16, abs=1e-4)


def test_row_falls_back_for_an_unrecognized_camera(tmp_path):
    path = write_frame(tmp_path, make_test_frame([(120, 150), (170, 150)], [1.0e5, 4.0e4]),
                       INSTRUME="Some Other Camera")
    row = analyze_image(path, root=tmp_path)
    assert row["snr_method"] == "background"
    assert np.isnan(row["egain"])


def test_a_blank_frame_still_produces_a_row(tmp_path):
    path = write_frame(tmp_path, make_test_frame([], []))
    row = analyze_image(path, root=tmp_path)
    assert row["n_stars"] == 0
    assert row["status"] == "no stars detected"
    assert np.isnan(row["sep_pix"])
    assert np.isnan(row["star0_flux"])
    # the header and background must survive even when nothing is detected
    assert row["object"] == "Achernar"
    # write_frame truncates onto the 16-count grid the driver writes, so the median can only land
    # on a multiple of 16 and 1550 is not representable. One quantization step is the real tolerance;
    # the unquantized accuracy is pinned to 0.5 counts by the measure_background tests above.
    assert row["bkg_median"] == pytest.approx(1550.0, abs=16.0)


def test_a_single_star_frame_produces_a_row_with_no_separation(tmp_path):
    path = write_frame(tmp_path, make_test_frame([(120, 150)], [1.0e5]))
    row = analyze_image(path, root=tmp_path)
    assert row["n_stars"] == 1
    assert row["status"] == "1 star detected"
    assert np.isfinite(row["star0_flux"])
    assert np.isnan(row["star1_flux"])
    assert np.isnan(row["sep_pix"])


def test_an_unreadable_file_produces_a_row_rather_than_raising(tmp_path):
    bad = tmp_path / "Achernar" / "Light"
    bad.mkdir(parents=True, exist_ok=True)
    path = bad / "broken.fits"
    path.write_text("this is not a fits file")
    row = analyze_image(path, root=tmp_path)
    assert row["n_stars"] == 0
    assert row["status"].startswith("read error")


def test_every_row_has_identical_keys_whatever_the_outcome(tmp_path):
    # a table is built from these rows, so the schema must not depend on the detections
    good = analyze_image(write_frame(tmp_path, make_test_frame([(120, 150), (170, 150)], [1.0e5, 4.0e4]),
                                     name="good.fits"), root=tmp_path)
    blank = analyze_image(write_frame(tmp_path, make_test_frame([], []), name="blank.fits"), root=tmp_path)
    assert set(good) == set(blank)
