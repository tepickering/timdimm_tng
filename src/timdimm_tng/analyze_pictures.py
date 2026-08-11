"""
Analyze the single exposures taken before each seeing measurement.

Each frame holds the two spots produced by the DIMM mask. This module measures the background,
does photometry and shape measurement on both spots, and writes one row per image to an ECSV
table, for batch use over the archive and daily use on the previous night.
"""

from astropy.stats import sigma_clipped_stats


def measure_background(data):
    """
    Sigma-clipped background level and noise.

    Exposures are 1 ms, so the frame is almost entirely background and the clipping alone is
    enough to reject the two spots without an explicit source mask.
    """
    mean, median, rms = sigma_clipped_stats(data, sigma=3.0, maxiters=5)
    return {"bkg_mean": float(mean), "bkg_median": float(median), "bkg_rms": float(rms)}
