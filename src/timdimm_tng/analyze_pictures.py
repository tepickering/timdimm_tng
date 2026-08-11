"""
Analyze the single exposures taken before each seeing measurement.

Each frame holds the two spots produced by the DIMM mask. This module measures the background,
does photometry and shape measurement on both spots, and writes one row per image to an ECSV
table, for batch use over the archive and daily use on the previous night.
"""

import warnings
from pathlib import Path

import numpy as np
from astropy.io import fits
from astropy.modeling import fitting, models
from astropy.stats import sigma_clipped_stats
from astropy.time import Time, TimeDelta
from photutils.aperture import ApertureStats, CircularAnnulus, CircularAperture
from photutils.detection import DAOStarFinder
from photutils.utils.exceptions import NoDetectionsWarning

from timdimm_tng.detector import egain_from_header

#: arcsec/pixel for 9 um pixels at 2500 mm, matching the SCALE keyword
DEFAULT_PIXEL_SCALE = 0.7427

#: diameter of a single DIMM mask sub-aperture in mm, as used by timdimm_seeing()
DEFAULT_APERTURE_DIAMETER = 50.0

#: effective wavelength of the ASI432MM in um, as used by analyze_cube.seeing()
DEFAULT_WAVELENGTH = 0.64

#: bounds on the iterated photometry aperture radius, in pixels
MIN_APER_RADIUS = 6.0
MAX_APER_RADIUS = 40.0

#: FWHM in pixels handed to DAOStarFinder for detection only
DETECTION_FWHM = 5.0

#: SAAO longitude in degrees east, used when a frame has no SITELONG
SAAO_LONGITUDE = 20.8107

#: the header subset requested for the output table, from header.txt
HEADER_KEYS = [
    "EXPTIME", "CCD-TEMP", "AIRMASS", "OBJCTAZ", "OBJCTALT", "RA", "DEC",
    "PIERSIDE", "EQUINOX", "DATE-OBS", "GAIN", "OFFSET", "OBJECT",
]

#: per-star measurements copied into star0_*/star1_* columns
STAR_KEYS = [
    "x", "y", "peak", "flux", "snr", "fwhm", "fwhm_gauss", "sigma_major", "sigma_minor",
    "ellip", "pa", "sharpness", "concentration", "fit_ok", "aper_radius", "n_pix",
]

#: header keywords whose values are strings, so empty rows can be typed correctly
HEADER_STRING_KEYS = {"PIERSIDE", "DATE-OBS", "OBJECT"}

NAN = float("nan")


def measure_background(data):
    """
    Sigma-clipped background level and noise.

    Exposures are 1 ms, so the frame is almost entirely background and the clipping alone is
    enough to reject the two spots without an explicit source mask.
    """
    mean, median, rms = sigma_clipped_stats(data, sigma=3.0, maxiters=5)
    return {"bkg_mean": float(mean), "bkg_median": float(median), "bkg_rms": float(rms)}


def _aperture_stats(data, position, radius):
    """
    ApertureStats for one spot, with the local background taken from an annulus scaled to the
    aperture. A fixed annulus would sit on the wings of a smeared spot, oversubtract, and shrink
    the measured minor axis.
    """
    aperture = CircularAperture([position], r=radius)
    annulus = CircularAnnulus([position], r_in=1.5 * radius, r_out=2.5 * radius)
    local_bkg = ApertureStats(data, annulus).median
    return ApertureStats(data, aperture, local_bkg=local_bkg)


def _fit_gaussian(data, position, radius):
    """
    Fit an elliptical gaussian to a cutout around the spot, as an independent check on the
    moment-based size. Returns (fwhm_gauss, fit_ok).
    """
    half = int(np.ceil(radius))
    x0, y0 = position
    ix, iy = int(round(x0)), int(round(y0))
    ylo, yhi = max(iy - half, 0), min(iy + half + 1, data.shape[0])
    xlo, xhi = max(ix - half, 0), min(ix + half + 1, data.shape[1])
    cutout = data[ylo:yhi, xlo:xhi]
    if cutout.size < 25:
        return float("nan"), False
    yy, xx = np.mgrid[ylo:yhi, xlo:xhi]
    initial = models.Gaussian2D(
        amplitude=cutout.max() - np.median(cutout),
        x_mean=x0, y_mean=y0, x_stddev=radius / 3.0, y_stddev=radius / 3.0,
    )
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            model = fitting.TRFLSQFitter()(initial, xx, yy, cutout - np.median(cutout))
    except Exception:
        return float("nan"), False
    sigma_x, sigma_y = abs(float(model.x_stddev.value)), abs(float(model.y_stddev.value))
    if not np.isfinite([sigma_x, sigma_y]).all() or sigma_x <= 0 or sigma_y <= 0:
        return float("nan"), False
    return 2.3548 * np.sqrt(sigma_x * sigma_y), True


def measure_stars(data, bkg_rms, egain=float("nan"), pixel_scale=DEFAULT_PIXEL_SCALE,
                  aperture_diameter=DEFAULT_APERTURE_DIAMETER, wavelength=DEFAULT_WAVELENGTH,
                  threshold=10.0, max_stars=2):
    """
    Detect, centroid and measure the brightest spots in a frame.

    Returns a list of dicts sorted by x centroid, at most `max_stars` long and possibly empty.
    The x ordering is a positional label only: the camera orientation changed during the life of
    the archive, so it does not identify which mask aperture produced which spot.
    """
    _, median, _ = sigma_clipped_stats(data, sigma=3.0, maxiters=5)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", NoDetectionsWarning)
        sources = DAOStarFinder(fwhm=DETECTION_FWHM, threshold=threshold * bkg_rms)(data - median)
    if sources is None or len(sources) == 0:
        return []

    sources.sort("flux")
    sources.reverse()
    sources = sources[:max_stars]
    sources.sort("x_centroid")

    # scale of a diffraction limited image, for the concentration normalization
    diffraction = (wavelength * 1.0e-3 / aperture_diameter) / np.deg2rad(pixel_scale / 3600.0)

    stars = []
    for source in sources:
        position = (float(source["x_centroid"]), float(source["y_centroid"]))
        radius = 3.0 * DETECTION_FWHM
        stats = None
        # iterate the radius onto the semi-major axis: a fixed aperture truncates a smeared spot
        # along its long axis and biases the ellipticity low, which is exactly the signal we want
        for _ in range(4):
            stats = _aperture_stats(data, position, radius)
            semimajor = float(np.atleast_1d(stats.semimajor_axis.value)[0])
            if not np.isfinite(semimajor) or semimajor <= 0:
                break
            new_radius = float(np.clip(3.0 * semimajor, MIN_APER_RADIUS, MAX_APER_RADIUS))
            if abs(new_radius - radius) < 0.5:
                break
            radius = new_radius

        semimajor = float(np.atleast_1d(stats.semimajor_axis.value)[0])
        semiminor = float(np.atleast_1d(stats.semiminor_axis.value)[0])
        flux = float(np.atleast_1d(stats.sum)[0])
        peak = float(np.atleast_1d(stats.max)[0])
        n_pix = float(np.atleast_1d(stats.sum_aper_area.value)[0])
        centroid = np.atleast_2d(stats.centroid)[0]

        # geometric mean, not photutils' quadrature mean: this one preserves area, and the two
        # differ by 12% at ellipticity 0.5
        fwhm = 2.3548 * np.sqrt(semimajor * semiminor) if semimajor > 0 and semiminor > 0 else float("nan")

        if np.isfinite(egain):
            flux_e = flux * egain
            noise_e = np.sqrt(abs(flux_e) + n_pix * (bkg_rms * egain) ** 2)
            snr = flux_e / noise_e if noise_e > 0 else float("nan")
        else:
            snr = flux / (bkg_rms * np.sqrt(n_pix)) if bkg_rms > 0 else float("nan")

        concentration = (peak / flux) * (4.0 / np.pi) / diffraction**2 if flux > 0 else float("nan")
        fwhm_gauss, fit_ok = _fit_gaussian(data, position, radius)

        stars.append({
            "x": float(centroid[0]),
            "y": float(centroid[1]),
            "peak": peak,
            "flux": flux,
            "snr": float(snr),
            "fwhm": float(fwhm),
            "fwhm_gauss": float(fwhm_gauss),
            "sigma_major": semimajor,
            "sigma_minor": semiminor,
            "ellip": float(np.atleast_1d(stats.ellipticity)[0]),
            "pa": float(np.atleast_1d(stats.orientation.value)[0]),
            "sharpness": float(source["sharpness"]),
            "concentration": float(concentration),
            "fit_ok": bool(fit_ok),
            "aper_radius": float(radius),
            "n_pix": n_pix,
        })
    return stars


def night_of(date_obs, sitelong=None):
    """
    Label for the observing night: the local-solar-time date at the start of the night.

    Nights run local noon to local noon, so subtracting 12 hours from the local time and taking
    the date gives every frame in one night the same label.
    """
    if not date_obs:
        return ""
    longitude = SAAO_LONGITUDE if sitelong is None else float(sitelong)
    local = Time(date_obs, format="isot", scale="utc") + TimeDelta(longitude / 15.0 * 3600.0, format="sec")
    return (local - TimeDelta(12.0 * 3600.0, format="sec")).isot[:10]


def last_night(now=None):
    """Night label for the previous day, for the daily cron run."""
    current = Time.now() if now is None else Time(now, format="isot", scale="utc")
    return (current - TimeDelta(1.0, format="jd")).isot[:10]


def find_images(root, night=None):
    """
    Find frames under <root>/<target>/<imagetype>/, optionally restricted to one night.

    Pictures/ has no per-night directories, so night selection reads DATE-OBS from each header.
    Only headers are read; pixel data is left on disk.
    """
    root = Path(root)
    paths = sorted(list(root.glob("*/*/*.fits")) + list(root.glob("*/*/*.fits.gz")))
    if night is None:
        return paths

    selected = []
    for path in paths:
        try:
            header = fits.getheader(path)
        except Exception:
            continue
        if night_of(header.get("DATE-OBS"), header.get("SITELONG")) == night:
            selected.append(path)
    return selected


def _column_name(key):
    """FITS keyword to column name: lower case, dashes to underscores."""
    return key.lower().replace("-", "_")


def _empty_row():
    """
    A row with every column present and empty, so the table schema never varies.

    Empty values are typed by column: "" for string keywords and NaN for numeric ones. Using None
    would give an object-dtype column, which vstacks badly against a properly typed column from
    another run and makes --append fragile.
    """
    row = {"filename": "", "target": "", "night": "", "status": "ok", "n_stars": 0}
    row.update({_column_name(key): ("" if key in HEADER_STRING_KEYS else NAN) for key in HEADER_KEYS})
    row.update({"bkg_mean": NAN, "bkg_median": NAN, "bkg_rms": NAN})
    row.update({"egain": NAN, "bitshift": 0, "snr_method": ""})
    for index in (0, 1):
        row.update({f"star{index}_{key}": (False if key == "fit_ok" else NAN) for key in STAR_KEYS})
    row.update({"sep_pix": NAN, "sep_arcsec": NAN, "sep_pa": NAN, "flux_ratio": NAN})
    return row


def analyze_image(path, root=None):
    """
    Measure one FITS frame and return a flat row.

    Never raises: an unreadable file or a frame with too few detections still returns a row, with
    `status` saying what happened, so a night that produced nothing stays distinguishable from a
    night that was never processed.
    """
    path = Path(path)
    row = _empty_row()
    root = Path(root) if root is not None else path.parent
    try:
        row["filename"] = str(path.relative_to(root))
    except ValueError:
        row["filename"] = path.name
    # <root>/<target>/<imagetype>/<file>
    row["target"] = path.parent.parent.name

    try:
        with fits.open(path) as hdulist:
            header = hdulist[0].header
            data = hdulist[0].data.astype(float)
    except Exception as error:
        row["status"] = f"read error: {error}"
        return row

    for key in HEADER_KEYS:
        value = header.get(key)
        row[_column_name(key)] = value.strip() if isinstance(value, str) else value
    row["night"] = night_of(header.get("DATE-OBS"), header.get("SITELONG"))

    row.update(measure_background(data))
    egain, bitshift, snr_method = egain_from_header(header, data)
    row.update({"egain": egain, "bitshift": bitshift, "snr_method": snr_method})

    pixel_scale = float(header.get("SCALE", DEFAULT_PIXEL_SCALE))
    stars = measure_stars(data, row["bkg_rms"], egain=egain, pixel_scale=pixel_scale)
    row["n_stars"] = len(stars)

    for index, star in enumerate(stars):
        for key in STAR_KEYS:
            row[f"star{index}_{key}"] = star[key]

    if len(stars) == 2:
        dx = stars[1]["x"] - stars[0]["x"]
        dy = stars[1]["y"] - stars[0]["y"]
        row["sep_pix"] = float(np.hypot(dx, dy))
        row["sep_arcsec"] = row["sep_pix"] * pixel_scale
        row["sep_pa"] = float(np.degrees(np.arctan2(dy, dx)))
        if stars[1]["flux"] != 0:
            row["flux_ratio"] = stars[0]["flux"] / stars[1]["flux"]
    elif len(stars) == 1:
        row["status"] = "1 star detected"
    else:
        row["status"] = "no stars detected"

    return row
