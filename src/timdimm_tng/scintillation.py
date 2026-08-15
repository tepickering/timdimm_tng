"""
Scintillation and time-constant estimators for timDIMM seeing cubes.

The DIMM mask has one clear aperture and one carrying a wedge prism. The prism's throughput relative
to the clear aperture is a direct measure of the state of the optics -- it collects dust and
condensation and its anti-reflection coatings are poor -- so logging it gives a cross-check against
the humidity sensor.

Every function here is pure: the input is the dict ``analyze_dimm_cube`` returns and the output is
scalars. Nothing loads a cube or writes a file, which is what makes the estimators testable against
synthetic series with known answers.

See docs/superpowers/specs/2026-08-14-scintillation-logging-design.md.
"""

import numpy as np

#: Below this many surviving frames the statistics are reported as NaN rather than computed. A time
#: constant from a heavily decimated series is not a measurement.
MIN_KEPT = 50


def assign_apertures(fluxes):
    """
    Split a per-frame flux array into bright and faint series, assigned once for the whole cube.

    The prism aperture is always the fainter one, but ``find_apertures`` sorts by x centroid, so
    which column holds it depends on the camera orientation. Assigning per frame would take the
    minimum of two noisy numbers every time and bias the ratio low even for identical apertures.

    Parameters
    ----------
    fluxes : array-like, shape (nframes, 2)
        Per-frame flux in each aperture.

    Returns
    -------
    bright, faint : ~numpy.ndarray
        The two columns, ordered by their median over the whole cube.
    """
    fluxes = np.asarray(fluxes, dtype=float)
    bright_col = int(np.argmax(np.median(fluxes, axis=0)))
    return fluxes[:, bright_col], fluxes[:, 1 - bright_col]


def throughput(bright, faint):
    """
    Prism throughput: the ratio of the mean fluxes, faint over bright.

    Not the mean of the per-frame ratios. Noise in the denominator inflates the mean of a ratio, and
    1 ms frames scintillate hard enough that two identical apertures at 50% frame-to-frame scatter
    give a visibly inflated answer against the correct 1.00. The ratio of means is also the
    physically meaningful quantity: total light through the prism over total through the clear
    aperture.
    """
    bright = np.asarray(bright, dtype=float)
    faint = np.asarray(faint, dtype=float)
    if bright.sum() <= 0 or faint.sum() <= 0:
        return float("nan")
    return float(faint.sum() / bright.sum())
