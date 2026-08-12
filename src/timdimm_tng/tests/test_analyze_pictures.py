from pathlib import Path

import numpy as np
import pytest
from astropy.io import fits
from astropy.modeling.models import Gaussian2D
from astropy.table import Table

from timdimm_tng.analyze_pictures import (_empty_row, analyze_image, build_table, cache_path, find_images, last_night, main,
                                          measure_background, measure_stars, merge_tables, night_of, read_cached_rows,
                                          sort_by_time, write_cached_row)


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


def test_night_label_is_the_same_either_side_of_midnight():
    # SAAO is ~1.4h ahead of UTC in solar time; both of these are the same observing night
    evening = night_of("2025-10-09T19:19:29.279", 20.94556)
    morning = night_of("2025-10-10T01:30:00.000", 20.94556)
    assert evening == morning == "2025-10-09"


def test_night_label_rolls_over_at_local_noon():
    before_noon = night_of("2025-10-10T09:00:00.000", 20.94556)
    after_noon = night_of("2025-10-10T11:00:00.000", 20.94556)
    assert before_noon == "2025-10-09"
    assert after_noon == "2025-10-10"


def test_night_label_is_empty_without_a_timestamp():
    assert night_of(None) == ""


def test_last_night_is_the_day_before_today():
    assert last_night(now="2025-10-10T09:00:00") == "2025-10-09"


def test_find_images_walks_target_and_image_type_directories(tmp_path):
    frame = make_test_frame([(120, 150), (170, 150)], [1.0e5, 4.0e4])
    write_frame(tmp_path, frame, name="Achernar_Light_001.fits")
    write_frame(tmp_path, frame, name="Achernar_Light_002.fits")
    found = find_images(tmp_path)
    assert [p.name for p in found] == ["Achernar_Light_001.fits", "Achernar_Light_002.fits"]


def test_find_images_picks_up_compressed_archive_frames(tmp_path):
    import gzip
    write_frame(tmp_path, make_test_frame([(120, 150)], [1.0e5]), name="Achernar_Light_001.fits")
    raw = tmp_path / "Achernar" / "Light" / "Achernar_Light_001.fits"
    with open(raw, "rb") as handle:
        data = handle.read()
    with gzip.open(tmp_path / "Achernar" / "Light" / "Achernar_Light_009.fits.gz", "wb") as handle:
        handle.write(data)
    assert len(find_images(tmp_path)) == 2


def test_find_images_filters_by_night(tmp_path):
    frame = make_test_frame([(120, 150), (170, 150)], [1.0e5, 4.0e4])
    write_frame(tmp_path, frame, name="a.fits", **{"DATE-OBS": "2025-10-09T19:19:29.279"})
    write_frame(tmp_path, frame, name="b.fits", **{"DATE-OBS": "2025-10-10T01:30:00.000"})
    write_frame(tmp_path, frame, name="c.fits", **{"DATE-OBS": "2025-10-12T20:00:00.000"})
    # a and b are the same night either side of midnight; c is a different one
    assert sorted(p.name for p in find_images(tmp_path, night="2025-10-09")) == ["a.fits", "b.fits"]
    assert [p.name for p in find_images(tmp_path, night="2025-10-12")] == ["c.fits"]


def test_table_carries_units_and_descriptions(tmp_path):
    path = write_frame(tmp_path, make_test_frame([(120, 150), (170, 150)], [1.0e5, 4.0e4]))
    table = build_table([analyze_image(path, root=tmp_path)])
    assert table["sep_arcsec"].unit == "arcsec"
    assert table["star0_fwhm"].unit == "pix"
    assert "geometric mean" in table["star0_fwhm"].description
    # the snr description must record that it is background limited without a known egain
    assert table["star0_snr"].description


def test_merge_replaces_rows_for_the_same_file(tmp_path):
    path = write_frame(tmp_path, make_test_frame([(120, 150), (170, 150)], [1.0e5, 4.0e4]))
    first = build_table([analyze_image(path, root=tmp_path)])
    second = build_table([analyze_image(path, root=tmp_path)])
    merged = merge_tables(first, second)
    assert len(merged) == 1


def test_merge_keeps_rows_for_different_files(tmp_path):
    frame = make_test_frame([(120, 150), (170, 150)], [1.0e5, 4.0e4])
    a = build_table([analyze_image(write_frame(tmp_path, frame, name="a.fits"), root=tmp_path)])
    b = build_table([analyze_image(write_frame(tmp_path, frame, name="b.fits"), root=tmp_path)])
    assert len(merge_tables(a, b)) == 2


def test_cli_writes_an_ecsv_for_every_frame(tmp_path):
    frame = make_test_frame([(120, 150), (170, 150)], [1.0e5, 4.0e4])
    write_frame(tmp_path, frame, name="a.fits")
    write_frame(tmp_path, frame, name="b.fits")
    out = tmp_path / "out.ecsv"
    assert main(["--root", str(tmp_path), "--all", "-o", str(out)]) == 0
    table = Table.read(out)
    assert len(table) == 2
    assert set(table["target"]) == {"Achernar"}


def test_cli_append_is_idempotent(tmp_path):
    write_frame(tmp_path, make_test_frame([(120, 150), (170, 150)], [1.0e5, 4.0e4]), name="a.fits")
    out = tmp_path / "out.ecsv"
    main(["--root", str(tmp_path), "--all", "-o", str(out)])
    main(["--root", str(tmp_path), "--all", "-o", str(out), "--append"])
    assert len(Table.read(out)) == 1


def test_cli_can_write_plain_csv(tmp_path):
    write_frame(tmp_path, make_test_frame([(120, 150), (170, 150)], [1.0e5, 4.0e4]), name="a.fits")
    out = tmp_path / "out.csv"
    assert main(["--root", str(tmp_path), "--all", "-o", str(out), "--format", "csv"]) == 0
    assert len(Table.read(out, format="ascii.csv")) == 1


def test_a_read_error_row_still_builds_and_writes_a_table(tmp_path):
    # empty header values must be typed, not None, or the column comes out object dtype
    bad = tmp_path / "Achernar" / "Light"
    bad.mkdir(parents=True, exist_ok=True)
    (bad / "broken.fits").write_text("this is not a fits file")
    write_frame(tmp_path, make_test_frame([(120, 150), (170, 150)], [1.0e5, 4.0e4]), name="a.fits")
    out = tmp_path / "out.ecsv"
    assert main(["--root", str(tmp_path), "--all", "-o", str(out)]) == 0
    table = Table.read(out)
    assert len(table) == 2
    assert table["object"].dtype.kind == "U"
    assert any(status.startswith("read error") for status in table["status"])


def test_cli_reports_when_no_images_match(tmp_path, capsys):
    assert main(["--root", str(tmp_path), "--night", "1999-01-01", "-o", str(tmp_path / "x.ecsv")]) == 1
    assert "no images" in capsys.readouterr().out.lower()


def test_cache_path_is_unique_per_source_file(tmp_path):
    a = cache_path(tmp_path, "Achernar/Light/a.fits")
    b = cache_path(tmp_path, "Canopus/Light/a.fits")
    assert a != b
    assert a.parent == tmp_path
    assert a.suffix == ".ecsv"


def test_a_cached_row_round_trips(tmp_path):
    path = write_frame(tmp_path, make_test_frame([(120, 150), (170, 150)], [1.0e5, 4.0e4]))
    row = analyze_image(path, root=tmp_path)
    cache = tmp_path / "cache"
    write_cached_row(cache, row)
    table = read_cached_rows(cache)
    assert len(table) == 1
    assert table["filename"][0] == "Achernar/Light/Achernar_Light_001.fits"
    assert table["star0_flux"][0] == pytest.approx(row["star0_flux"])


def test_reading_a_cache_keeps_the_widest_string_in_each_column(tmp_path, monkeypatch):
    # rows are cached one per file, so each entry's string columns are only as wide as that row,
    # and a collect folds them into a table a chunk at a time. Sizing the columns to the widest
    # value has to survive both, so put the two rows in separate chunks.
    monkeypatch.setattr("timdimm_tng.analyze_pictures.COLLECT_CHUNK", 1)
    row = _empty_row()
    for name, target in (("a.fits", "Ari"), ("Alpha_Pavonis/Light/a_very_long_frame_name.fits", "Alpha Pavonis")):
        row["filename"] = name
        row["target"] = target
        write_cached_row(tmp_path, row)
    table = read_cached_rows(tmp_path)
    assert sorted(table["filename"]) == ["Alpha_Pavonis/Light/a_very_long_frame_name.fits", "a.fits"]
    assert sorted(table["target"]) == ["Alpha Pavonis", "Ari"]


def test_a_missing_header_keyword_stays_typed(tmp_path):
    # header.get() returns None for a keyword that is not there, and a None lands in an
    # object-dtype column that will not stack against the same column from a frame that had the
    # keyword. The typed empty from _empty_row has to survive.
    path = write_frame(tmp_path, make_test_frame([(120, 150), (170, 150)], [1.0e5, 4.0e4]))
    with fits.open(path, mode="update") as hdul:
        del hdul[0].header["OBJECT"]
        del hdul[0].header["AIRMASS"]
    row = analyze_image(path, root=tmp_path)
    assert row["object"] == ""
    assert np.isnan(row["airmass"])
    table = build_table([row])
    assert table["object"].dtype.kind == "U"
    assert table["airmass"].dtype.kind == "f"


def test_reading_a_cache_repairs_untyped_entries(tmp_path):
    # entries written before missing keywords were typed hold a bare None, and collecting has to
    # cope with them rather than require the whole archive be measured again
    row = _empty_row()
    row["filename"], row["object"] = "a.fits", "Achernar"
    write_cached_row(tmp_path, row)
    row["filename"], row["object"] = "b.fits", None
    write_cached_row(tmp_path, row)
    table = read_cached_rows(tmp_path)
    assert len(table) == 2
    assert table["object"].dtype.kind == "U"
    assert sorted(table["object"]) == ["", "Achernar"]


def test_reading_a_cache_retypes_a_column_that_drifted(tmp_path):
    # a keyword astropy reads as an int in one frame and a float in another, or as text, has to
    # end up one type in the table rather than stop the collect
    row = _empty_row()
    row["filename"], row["exptime"], row["equinox"] = "a.fits", 0.001, 2000
    write_cached_row(tmp_path, row)
    row["filename"], row["exptime"], row["equinox"] = "b.fits", "0.002", 2000.0
    write_cached_row(tmp_path, row)
    table = read_cached_rows(tmp_path)
    assert table["exptime"].dtype.kind == "f"
    assert sorted(table["exptime"]) == [0.001, 0.002]


def test_reading_a_cache_stacks_chunks_that_differ_in_emptiness(tmp_path, monkeypatch):
    # an empty string round trips through ECSV as a masked value, so a chunk whose rows are all
    # empty in some column carries no usable dtype for it. Collecting has to stack that against a
    # chunk where the column has values, which is the common case across the archive: most frames
    # record a filter and an occasional one does not.
    monkeypatch.setattr("timdimm_tng.analyze_pictures.COLLECT_CHUNK", 1)
    row = _empty_row()
    row["filename"], row["target"] = "a.fits", "Achernar"
    write_cached_row(tmp_path, row)
    row["filename"], row["target"] = "b.fits", ""
    write_cached_row(tmp_path, row)
    table = read_cached_rows(tmp_path)
    assert len(table) == 2
    assert sorted(table["filename"]) == ["a.fits", "b.fits"]
    assert "Achernar" in list(table["target"])


def test_reading_an_empty_cache_returns_nothing(tmp_path):
    assert read_cached_rows(tmp_path / "missing") is None
    (tmp_path / "empty").mkdir()
    assert read_cached_rows(tmp_path / "empty") is None


def test_sort_by_time_orders_rows_by_date_obs(tmp_path):
    frame = make_test_frame([(120, 150), (170, 150)], [1.0e5, 4.0e4])
    late = write_frame(tmp_path, frame, name="a.fits", **{"DATE-OBS": "2025-10-09T22:00:00.000"})
    early = write_frame(tmp_path, frame, name="b.fits", **{"DATE-OBS": "2025-10-09T20:00:00.000"})
    table = sort_by_time(build_table([analyze_image(late, root=tmp_path), analyze_image(early, root=tmp_path)]))
    assert list(table["filename"]) == ["Achernar/Light/b.fits", "Achernar/Light/a.fits"]


def test_cli_caches_each_frame_as_its_own_table(tmp_path):
    frame = make_test_frame([(120, 150), (170, 150)], [1.0e5, 4.0e4])
    write_frame(tmp_path, frame, name="a.fits")
    write_frame(tmp_path, frame, name="b.fits")
    out = tmp_path / "out.ecsv"
    cache = tmp_path / "cache"
    assert main(["--root", str(tmp_path), "--all", "-o", str(out), "--cache-dir", str(cache)]) == 0
    assert len(list(cache.glob("*.ecsv"))) == 2


def test_cli_reuses_cached_rows_and_reprocess_overrides_them(tmp_path):
    write_frame(tmp_path, make_test_frame([(120, 150), (170, 150)], [1.0e5, 4.0e4]), name="a.fits")
    out = tmp_path / "out.ecsv"
    cache = tmp_path / "cache"
    args = ["--root", str(tmp_path), "--all", "-o", str(out), "--cache-dir", str(cache)]
    main(args)

    # mark the cached row so it is obvious whether it was reused or recomputed
    cached = list(cache.glob("*.ecsv"))[0]
    table = Table.read(cached)
    # replace rather than assign: the column is only as wide as "ok" and would truncate the marker
    table.replace_column("status", ["stale"])
    table.write(cached, overwrite=True)

    main(args)
    assert Table.read(out)["status"][0] == "stale"

    main(args + ["--reprocess"])
    assert Table.read(out)["status"][0] == "ok"


def test_cli_output_is_sorted_by_time_not_by_filename(tmp_path):
    frame = make_test_frame([(120, 150), (170, 150)], [1.0e5, 4.0e4])
    write_frame(tmp_path, frame, name="a.fits", **{"DATE-OBS": "2025-10-09T22:00:00.000"})
    write_frame(tmp_path, frame, name="b.fits", **{"DATE-OBS": "2025-10-09T20:00:00.000"})
    out = tmp_path / "out.ecsv"
    main(["--root", str(tmp_path), "--all", "-o", str(out)])
    assert list(Table.read(out)["filename"]) == ["Achernar/Light/b.fits", "Achernar/Light/a.fits"]


def test_cli_output_accumulates_frames_across_runs(tmp_path):
    frame = make_test_frame([(120, 150), (170, 150)], [1.0e5, 4.0e4])
    write_frame(tmp_path, frame, name="a.fits")
    out = tmp_path / "out.ecsv"
    args = ["--root", str(tmp_path), "--all", "-o", str(out)]
    main(args)

    # a later night adds frames; the earlier rows must survive without reanalyzing them
    write_frame(tmp_path, frame, name="b.fits", **{"DATE-OBS": "2025-10-12T20:00:00.000"})
    main(args)
    assert len(Table.read(out)) == 2


def test_cli_reports_progress_for_each_frame(tmp_path, capsys):
    frame = make_test_frame([(120, 150), (170, 150)], [1.0e5, 4.0e4])
    write_frame(tmp_path, frame, name="a.fits")
    write_frame(tmp_path, frame, name="b.fits")
    main(["--root", str(tmp_path), "--all", "-o", str(tmp_path / "out.ecsv")])
    output = capsys.readouterr().out
    assert "[1/2]" in output
    assert "[2/2]" in output
    assert "a.fits" in output


def test_cli_quiet_suppresses_progress(tmp_path, capsys):
    write_frame(tmp_path, make_test_frame([(120, 150), (170, 150)], [1.0e5, 4.0e4]), name="a.fits")
    main(["--root", str(tmp_path), "--all", "-o", str(tmp_path / "out.ecsv"), "--quiet"])
    output = capsys.readouterr().out
    assert "[1/1]" not in output
    assert "wrote 1 rows" in output


def test_read_cached_rows_can_be_limited_to_named_frames(tmp_path):
    row = _empty_row()
    for name in ("a.fits", "b.fits"):
        row["filename"] = name
        write_cached_row(tmp_path, row)
    assert list(read_cached_rows(tmp_path, names=["a.fits"])["filename"]) == ["a.fits"]


def test_read_cached_rows_ignores_names_that_are_not_cached(tmp_path):
    row = _empty_row()
    row["filename"] = "a.fits"
    write_cached_row(tmp_path, row)
    assert list(read_cached_rows(tmp_path, names=["a.fits", "missing.fits"])["filename"]) == ["a.fits"]


def test_cli_collects_only_the_frames_in_this_run(tmp_path):
    write_frame(tmp_path, make_test_frame([(120, 150), (170, 150)], [1.0e5, 4.0e4]), name="a.fits")
    cache = tmp_path / "cache"
    # a row left behind by an earlier run, for a frame that is no longer on disk
    stale = _empty_row()
    stale["filename"] = "Achernar/Light/deleted.fits"
    write_cached_row(cache, stale)

    out = tmp_path / "out.ecsv"
    main(["--root", str(tmp_path), "--all", "-o", str(out), "--cache-dir", str(cache)])
    assert list(Table.read(out)["filename"]) == ["Achernar/Light/a.fits"]


def test_cli_collect_cache_rebuilds_from_the_whole_cache(tmp_path):
    write_frame(tmp_path, make_test_frame([(120, 150), (170, 150)], [1.0e5, 4.0e4]), name="a.fits")
    cache = tmp_path / "cache"
    stale = _empty_row()
    stale["filename"] = "Achernar/Light/deleted.fits"
    write_cached_row(cache, stale)

    out = tmp_path / "out.ecsv"
    main(["--root", str(tmp_path), "--all", "-o", str(out), "--cache-dir", str(cache), "--collect-cache"])
    assert len(Table.read(out)) == 2


def test_cli_jobs_measures_every_frame(tmp_path):
    frame = make_test_frame([(120, 150), (170, 150)], [1.0e5, 4.0e4])
    for index, name in enumerate(("a.fits", "b.fits", "c.fits")):
        write_frame(tmp_path, frame, name=name, **{"DATE-OBS": f"2025-10-09T19:1{index}:00.000"})
    out = tmp_path / "out.ecsv"
    main(["--root", str(tmp_path), "--all", "-o", str(out), "--jobs", "2"])
    table = Table.read(out)
    assert len(table) == 3
    assert set(table["status"]) == {"ok"}


def test_cli_jobs_still_skips_cached_frames(tmp_path):
    write_frame(tmp_path, make_test_frame([(120, 150), (170, 150)], [1.0e5, 4.0e4]), name="a.fits")
    out = tmp_path / "out.ecsv"
    cache = tmp_path / "cache"
    args = ["--root", str(tmp_path), "--all", "-o", str(out), "--cache-dir", str(cache), "--jobs", "2"]
    main(args)

    cached = list(cache.glob("*.ecsv"))[0]
    table = Table.read(cached)
    table.replace_column("status", ["stale"])
    table.write(cached, overwrite=True)

    main(args)
    assert Table.read(out)["status"][0] == "stale"


ARCHIVE = Path.home() / "SAAO" / "timdimm_data" / "Pictures"


@pytest.mark.skipif(not ARCHIVE.exists(), reason="archived example data not present")
def test_runs_end_to_end_on_the_archived_frames():
    paths = find_images(ARCHIVE)
    assert len(paths) == 5
    rows = [analyze_image(path, root=ARCHIVE) for path in paths]
    table = build_table(rows)

    assert set(table["target"]) == {"Achernar"}
    assert set(table["object"]) == {"Achernar"}
    assert all(status == "ok" for status in table["status"])
    assert all(table["n_stars"] == 2)

    # the frames are 12-bit left-shifted ASI432MM data at gain 350
    assert all(table["bitshift"] == 16)
    assert all(table["snr_method"] == "ccd")

    # background and separation should be stable across the five frames
    assert np.all(np.abs(table["bkg_median"] - 1552.0) < 50.0)
    assert np.all(table["bkg_rms"] < 200.0)
    assert np.all(np.abs(table["sep_pix"] - 50.0) < 10.0)

    # sanity, not accuracy: everything measured must be finite and physical
    for prefix in ("star0", "star1"):
        assert np.all(np.isfinite(table[f"{prefix}_flux"]))
        assert np.all(table[f"{prefix}_flux"] > 0)
        assert np.all(table[f"{prefix}_snr"] > 5.0)
        assert np.all(table[f"{prefix}_fwhm"] > 0)
        assert np.all(table[f"{prefix}_fwhm"] < 60.0)
        assert np.all((table[f"{prefix}_ellip"] >= 0.0) & (table[f"{prefix}_ellip"] <= 1.0))
