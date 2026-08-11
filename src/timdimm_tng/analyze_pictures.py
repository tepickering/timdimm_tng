"""
Analyze the single exposures taken before each seeing measurement.

Each frame holds the two spots produced by the DIMM mask. This module measures the background,
does photometry and shape measurement on both spots, and writes one row per image to an ECSV
table, for batch use over the archive and daily use on the previous night.
"""

import warnings

import numpy as np
from astropy.modeling import fitting, models
from astropy.stats import sigma_clipped_stats
from photutils.aperture import ApertureStats, CircularAnnulus, CircularAperture
from photutils.detection import DAOStarFinder
from photutils.utils.exceptions import NoDetectionsWarning

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
