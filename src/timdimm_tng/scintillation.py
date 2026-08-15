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


def flux_ratio(bright, faint):
    """Per-frame ratio of the faint (prism) aperture to the bright (clear) one."""
    bright = np.asarray(bright, dtype=float)
    faint = np.asarray(faint, dtype=float)
    with np.errstate(divide="ignore", invalid="ignore"):
        return faint / bright


def scint_index(ratio):
    """
    Normalised variance of the flux ratio, ``var(r) / mean(r)**2``.

    Uncorrected for noise, hence the ``_raw`` in the column name it is logged under. Shot noise and
    centroiding scatter are inside this number, and on real 299 Hz cubes they dominate it. The mean
    fluxes are logged alongside so a photon-noise floor can be estimated and removed downstream.

    Built on the ratio rather than on a single aperture, which makes it differential: cloud and
    transparency changes move both apertures together and cancel out.
    """
    ratio = np.asarray(ratio, dtype=float)
    ratio = ratio[np.isfinite(ratio)]
    if ratio.size < 2:
        return float("nan")
    mean = ratio.mean()
    if mean <= 0:
        return float("nan")
    return float(ratio.var() / mean**2)


#: A lag with fewer contributing pairs than this is not trusted, and not used in a fit.
MIN_PAIRS = 30


def lag_autocorr(x, index, lag):
    """
    Autocorrelation at an integer frame lag, using only genuinely adjacent-in-time pairs.

    Frames where centroiding failed are missing from ``x``, so consecutive entries are not
    necessarily consecutive frames. The samples are scattered back into a full-length array with
    NaN in the gaps and only pairs whose cube indices differ by exactly ``lag`` contribute.
    Correlating by position in the compacted array instead is what produced the nonsense time
    constant on the 435-of-4420-frame cube in docs/scintillation_logging_notes.md.

    Parameters
    ----------
    x : array-like
        The series, one entry per surviving frame.
    index : array-like of int
        Cube frame index of each entry, as returned by ``analyze_dimm_cube`` in ``frame_index``.
    lag : int
        Frame lag, 1 or more.

    Returns
    -------
    rho : float
        Pearson correlation, or NaN if fewer than ``MIN_PAIRS`` pairs contribute.
    npairs : int
        How many pairs contributed. Reported even when ``rho`` is NaN.
    """
    if lag < 1:
        raise ValueError("lag must be at least 1")

    x = np.asarray(x, dtype=float)
    index = np.asarray(index, dtype=int)
    if x.size == 0:
        return float("nan"), 0

    full = np.full(int(index.max()) + 1, np.nan)
    full[index] = x

    a, b = full[:-lag], full[lag:]
    ok = np.isfinite(a) & np.isfinite(b)
    npairs = int(ok.sum())
    if npairs < MIN_PAIRS:
        return float("nan"), npairs

    return float(np.corrcoef(a[ok], b[ok])[0, 1]), npairs
