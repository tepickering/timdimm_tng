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

from datetime import datetime

import numpy as np
from astropy import stats

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


def scint_index(ratio, return_rejected=False):
    """
    Normalised variance of the flux ratio, estimated in log space as ``exp(sigma**2) - 1``.

    Scintillation is multiplicative, so the flux ratio is lognormal, and for a lognormal the
    normalised variance ``var(r) / mean(r)**2`` is exactly ``exp(sigma**2) - 1`` with ``sigma`` the
    standard deviation of ``log(r)``. Estimating ``sigma`` with the median absolute deviation gives
    a statistic that is robust *and* unbiased: outlying frames cannot move a median-based scale, and
    nothing is thrown away to achieve that.

    Robustness is not optional here. Being a ratio, this statistic has the whole cube's noise in its
    denominator: on one archived cube the bright aperture fell to 7 ADU against a median of 17357 in
    a few frames, the per-frame ratio reached 3049, and the plain normalised variance came out 498 --
    where anything above 1 already means the scatter exceeds the mean.

    This replaced a 5-sigma clip of the linear ratio, which was robust but biased low, because a
    symmetric cut on a lognormal removes real tail as well as dropouts: 0.2195 against a true 0.25
    on 50% synthetic scatter, and 25-30% low on clean archived cubes while rejecting only 1-2% of
    their frames. The bias grew with the scintillation, which is the worst possible direction for a
    turbulence statistic.

    Uncorrected for noise, hence the ``_raw`` in the column name it is logged under. Shot noise and
    centroiding scatter are inside this number, and on real 299 Hz cubes they dominate it. The mean
    fluxes are logged alongside so a photon-noise floor can be estimated and removed downstream.

    Built on the ratio rather than on a single aperture, which makes it differential: cloud and
    transparency changes move both apertures together and cancel out.

    Parameters
    ----------
    ratio : array-like
        Per-frame flux ratio.
    return_rejected : bool (default: False)
        Also return the fraction of frames that could not be used.

    Returns
    -------
    index : float
        Normalised variance, or NaN if fewer than two frames are usable.
    frac_rejected : float
        Only when ``return_rejected``. Fraction of frames dropped for being zero, negative or not
        finite -- an aperture that measured no flux, which has no logarithm. Nothing is dropped for
        being an outlier. A large value means the cube had dropouts, which is worth knowing.
    """
    ratio = np.asarray(ratio, dtype=float)
    usable = ratio[np.isfinite(ratio) & (ratio > 0.0)]
    if ratio.size == 0:
        return (float("nan"), float("nan")) if return_rejected else float("nan")

    frac_rejected = 1.0 - usable.size / ratio.size
    if usable.size < 2:
        return (float("nan"), frac_rejected) if return_rejected else float("nan")

    sigma = stats.mad_std(np.log(usable))
    index = float(np.expm1(sigma**2))
    return (index, frac_rejected) if return_rejected else index


#: A lag with fewer contributing pairs than this is not trusted, and not used in a fit.
MIN_PAIRS = 30

#: How far from the median a log ratio may sit, in MAD-based sigma, and still enter a correlation.
ACF_CLIP_SIGMA = 5.0


def log_ratio_series(ratio, index, clip_sigma=ACF_CLIP_SIGMA):
    """
    The log flux ratio and its frame indices, with dropout frames removed.

    The series the correlations are built on, and deliberately not the one ``scint_index`` uses.
    Pearson correlation is not robust: a single frame whose bright aperture nearly vanished has a
    ratio in the thousands but is still finite and still positive, so nothing else rejects it, and
    being isolated it appears in one lag-1 pair as a huge excursion with an ordinary neighbour. That
    one pair can pull rho(1) on a genuinely correlated cube from 0.75 to near zero, which is logged
    as ``tau_scint_censored = 1`` beside a ``frac_rejected`` of 0.0 -- a false measurement wearing
    the badge of a clean cube.

    Clipping here does not repeat the mistake that clipping made in ``scint_index``. There the cut
    biased the answer because the statistic *is* the scale of the distribution, and cutting its tail
    shrinks it. A correlation is a shape statistic on a fixed set of pairs; dropping 1% of frames at
    5 robust sigma removes dropouts and leaves the decay it measures alone.

    Working in the log is the other half of it, and is the natural space anyway: scintillation is
    multiplicative, so the log ratio is the additive quantity whose autocorrelation has a meaning.

    Parameters
    ----------
    ratio : array-like
        Per-frame flux ratio, one entry per surviving frame.
    index : array-like of int
        Cube frame index of each entry.
    clip_sigma : float
        Robust cut, in units of ``mad_std`` of the log ratio. A non-positive value disables it.

    Returns
    -------
    log_ratio, index : ~numpy.ndarray
        The surviving values and *their* frame indices, still paired. Empty arrays if fewer than
        two frames are usable.
    """
    ratio = np.asarray(ratio, dtype=float)
    index = np.asarray(index, dtype=int)

    usable = np.isfinite(ratio) & (ratio > 0.0)
    if usable.sum() < 2:
        return np.empty(0), np.empty(0, dtype=int)

    log_ratio, index = np.log(ratio[usable]), index[usable]
    sigma = stats.mad_std(log_ratio)
    if clip_sigma > 0 and np.isfinite(sigma) and sigma > 0:
        keep = np.abs(log_ratio - np.median(log_ratio)) <= clip_sigma * sigma
        log_ratio, index = log_ratio[keep], index[keep]

    return log_ratio, index


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


#: Lags used for the time-constant fit. Four is the most the measured decay supports before the
#: correlation reaches the noise floor: 0.63 / 0.28 / 0.13 on a real 299 Hz cube.
FIT_LAGS = (1, 2, 3, 4)


def fit_tau(x, index, dt, lags=FIT_LAGS):
    """
    Time constant from a log-linear fit to the lag autocorrelation, in seconds.

    A fit rather than a 1/e crossing read off the curve, because at 299 Hz the measured image-motion
    tau of 4-6 ms is only 1.2-1.7 samples long and the crossing lands between two samples.

    Lags are used in order and the loop stops at the first unusable one -- once the correlation has
    reached the noise floor, higher lags only flatten the fit.

    Returns NaN if fewer than two lags are usable or the fitted slope is not negative, which is what
    a series with no resolvable decay looks like.
    """
    times, logs = [], []
    for lag in lags:
        rho, npairs = lag_autocorr(x, index, lag)
        if npairs < MIN_PAIRS or not np.isfinite(rho) or rho <= 0:
            break
        times.append(lag * dt)
        logs.append(np.log(rho))

    if len(times) < 2:
        return float("nan")

    slope = np.polyfit(times, logs, 1)[0]
    if slope >= 0:
        return float("nan")
    return float(-1.0 / slope)


def median_dt(frame_times):
    """
    Median interval between frames, in seconds.

    Measured from the timestamps rather than assumed from the nominal frame rate. Cadence jitter is
    only 0.15-0.21 ms at 299 Hz, but the archive spans 10.5, 43.7, 120 and 299 Hz configurations, so
    a time constant logged without its real cadence is not interpretable.
    """
    if len(frame_times) < 2:
        return float("nan")
    intervals = np.diff(frame_times.unix)
    intervals = intervals[np.isfinite(intervals) & (intervals > 0)]
    if intervals.size == 0:
        return float("nan")
    return float(np.median(intervals))


#: A lag-1 autocorrelation below this means the series decorrelates within one frame, so its time
#: constant is an upper limit rather than a measurement. Real 299 Hz cubes give 0.10 and 0.01.
#:
#: The value is 1/e and not a tuning knob: rho(1) is exp(-dt/tau), so tau >= dt is exactly
#: rho(1) >= 1/e. The gate stood at 0.2 through 2026-08-16, which is tau = 0.62 frames, and the
#: whole 0.2 to 0.368 band it admitted was sub-frame. On the night of 2026-08-16 that band held
#: 32 of the 162 rows the gate passed, every one of them a failed fit.
ACF1_CENSOR_THRESHOLD = float(np.exp(-1.0))

#: Values of the ``tau_scint_censored`` column. Zero always means ``tau_scint_ms`` is a fitted
#: measurement, so a consumer never has to infer from the value what happened.
TAU_FITTED = 0        #: fitted; tau_scint_ms is finite and is the answer
TAU_CENSORED = 1      #: decorrelated within a frame; tau_scint_ms is dt, an upper limit
TAU_FIT_FAILED = 2    #: no fit was obtained; tau_scint_ms is NaN

_NAN_KEYS = (
    "throughput", "scint_index_raw", "tau_motion_ms", "tau_scint_ms", "acf1_ratio", "acf2_ratio",
    "mean_flux_bright", "mean_flux_faint", "frac_rejected",
)


def scintillation_stats(results):
    """
    Turn an ``analyze_dimm_cube`` result dict into the columns of one scintillation.csv row.

    Never raises on degenerate input: a row with NaN values and a populated ``n_kept`` says what
    happened, whereas a missing row says nothing. The caller writes the row regardless.

    Parameters
    ----------
    results : dict
        As returned by ``analyze_dimm_cube``, including the ``frame_index`` key.

    Returns
    -------
    dict
        Scalars only. Time constants are in milliseconds; everything else is dimensionless or Hz.
    """
    fluxes = np.asarray(results["aperture_fluxes"], dtype=float)
    index = np.asarray(results["frame_index"], dtype=int)
    n_kept = len(index)
    dt = median_dt(results["frame_times"])

    stats = {
        "n_kept": int(n_kept),
        "n_frames": int(n_kept + results["N_bad"]),
        "cadence_hz": float(1.0 / dt) if np.isfinite(dt) and dt > 0 else float("nan"),
        # every early return below leaves tau_scint_ms NaN, so failure is the default and the
        # flag is cleared only once a finite fit is in hand
        "tau_scint_censored": TAU_FIT_FAILED,
    }
    stats.update({key: float("nan") for key in _NAN_KEYS})

    if n_kept < MIN_KEPT:
        return stats

    bright, faint = assign_apertures(fluxes)
    stats["mean_flux_bright"] = float(bright.mean())
    stats["mean_flux_faint"] = float(faint.mean())
    stats["throughput"] = throughput(bright, faint)

    ratio = flux_ratio(bright, faint)
    stats["scint_index_raw"], stats["frac_rejected"] = scint_index(ratio, return_rejected=True)

    # the correlations run on the log ratio with dropouts removed; scint_index above keeps every
    # usable frame because a robust *scale* does not need them removed, but Pearson correlation does
    log_ratio, ratio_index = log_ratio_series(ratio, index)
    acf1, npairs = lag_autocorr(log_ratio, ratio_index, 1)
    stats["acf1_ratio"] = acf1 if npairs >= MIN_PAIRS else float("nan")

    # lag 2 is logged for the difference rho1 - rho2, which is how the atmospheric wind moment comes
    # out of a fixed-exposure cube: white photon noise adds to the variance but to no non-zero lag,
    # so differencing two lags cancels it where a single lag carries it at full weight. See the
    # Kornilov 2011 section of docs/scintillation_logging_notes.md.
    acf2, npairs2 = lag_autocorr(log_ratio, ratio_index, 2)
    stats["acf2_ratio"] = acf2 if npairs2 >= MIN_PAIRS else float("nan")

    # Everything above is dimensionless and needs only the frame *order*. Everything below is a time
    # constant in milliseconds, so it needs a frame interval -- and older SER writers left the
    # per-frame timestamps constant. Withhold the time constants rather than the whole row.
    if not np.isfinite(dt):
        return stats

    # the differential motion -- the same series the seeing is computed from -- not the
    # common-mode aperture_positions, which is telescope shake and has its own time constant
    baseline = np.asarray(results["baseline_lengths"], dtype=float)[0]
    tau_motion = fit_tau(baseline, index, dt)
    stats["tau_motion_ms"] = tau_motion * 1000.0 if np.isfinite(tau_motion) else float("nan")

    if np.isfinite(acf1) and acf1 >= ACF1_CENSOR_THRESHOLD:
        tau_scint = fit_tau(log_ratio, ratio_index, dt)
        # passing the gate does not guarantee a fit -- fit_tau needs two lags with positive
        # correlation and a negative slope, and a cube can clear rho(1) without supplying them
        if np.isfinite(tau_scint):
            stats["tau_scint_ms"] = tau_scint * 1000.0
            stats["tau_scint_censored"] = TAU_FITTED
    elif np.isfinite(acf1):
        # decorrelated within one frame: the time constant is below the sampling interval
        stats["tau_scint_ms"] = dt * 1000.0
        stats["tau_scint_censored"] = TAU_CENSORED

    return stats


#: Column order of ~/scintillation.csv. Kept in one place so the header and the rows cannot drift.
CSV_COLUMNS = (
    "time", "target", "throughput", "scint_index_raw", "tau_motion_ms", "tau_scint_ms",
    "tau_scint_censored", "acf1_ratio", "acf2_ratio", "cadence_hz", "n_frames", "n_kept",
    "mean_flux_bright", "mean_flux_faint", "frac_rejected", "airmass", "exptime", "gain", "offset",
)

CSV_HEADER = ",".join(CSV_COLUMNS) + "\n"

#: Fixed precision keeps the file diffable and readable. Anything absent here is written with str().
_PRECISION = {
    "throughput": 4, "scint_index_raw": 4, "acf1_ratio": 3, "acf2_ratio": 3,
    "tau_motion_ms": 2, "tau_scint_ms": 2, "cadence_hz": 2,
    "mean_flux_bright": 1, "mean_flux_faint": 1, "frac_rejected": 4, "airmass": 3,
}


def ensure_header(path):
    """
    Make ``path`` a CSV whose header is the current ``CSV_COLUMNS``, preserving any older file.

    The production writer only writes a header when the file does not exist, so adding a column
    would append wider rows under the narrower old header and leave a file that no longer parses.
    A file whose header does not match is therefore moved aside rather than appended to or
    truncated -- the old rows are real measurements and are still worth having.

    Parameters
    ----------
    path : ~pathlib.Path
        The CSV to check. Created with a header if absent.
    """
    if path.exists():
        with open(path) as fp:
            if fp.readline() == CSV_HEADER:
                return
        stamp = datetime.fromtimestamp(path.stat().st_mtime).strftime("%Y%m%dT%H%M%S")
        rotated = path.with_name(f"{path.name}.{stamp}")
        # a second column change within the same second must not destroy the first rotation
        suffix = 0
        while rotated.exists():
            suffix += 1
            rotated = path.with_name(f"{path.name}.{stamp}.{suffix}")
        path.rename(rotated)

    with open(path, "w") as fp:
        fp.write(CSV_HEADER)


def format_row(stats, time, target, exptime, airmass, *, gain, offset):
    """
    Format one scintillation.csv row, newline included.

    ``time`` must be the *same string* written to the matching seeing.csv row -- that identity is
    what lets the two files be joined without fuzzy time matching.

    ``airmass`` is logged even though seeing.csv already carries it, because the two files do not
    have the same rows: the scintillation row is written outside the seeing quality gate, so it
    exists for cubes that never reach seeing.csv. It is needed to interpret the index at all --
    scintillation goes roughly as sec(z)**3, while the seeing analyze_dimm_cube reports has already
    been divided by airmass**0.6. Written at the same precision seeing.csv uses.

    ``gain`` and ``offset`` are keyword-only and have no defaults on purpose. They cannot be
    recovered from the cube -- the SER header's ``Observer``, ``Instrument`` and ``Telescope``
    fields are all literally "Unknown" -- so the only record of them is what the acquisition script
    set, and a silently assumed default would be worse than no column at all. ``exptime`` is what
    now varies per target (see ``timdimm_tng.exposure``); these two are pinned, and are logged so
    that a later change to them stays legible in the archive.
    """
    values = dict(stats, time=time, target=target, exptime=exptime, airmass=airmass,
                  gain=gain, offset=offset)
    fields = []
    for column in CSV_COLUMNS:
        value = values[column]
        digits = _PRECISION.get(column)
        fields.append(f"{value:.{digits}f}" if digits is not None else str(value))
    return ",".join(fields) + "\n"
