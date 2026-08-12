"""
Analyze the single exposures taken before each seeing measurement.

Each frame holds the two spots produced by the DIMM mask. This module measures the background,
does photometry and shape measurement on both spots, and writes one row per image to an ECSV
table, for batch use over the archive and daily use on the previous night.
"""

import argparse
import multiprocessing
import os
import warnings
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

import numpy as np
from astropy.io import fits
from astropy.modeling import fitting, models
from astropy.stats import sigma_clipped_stats
from astropy.table import Table, vstack
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

#: units for the output columns, by suffix or exact name
COLUMN_UNITS = {
    "sep_pix": "pix", "sep_arcsec": "arcsec", "sep_pa": "deg",
    "x": "pix", "y": "pix", "fwhm": "pix", "fwhm_gauss": "pix",
    "sigma_major": "pix", "sigma_minor": "pix", "pa": "deg", "aper_radius": "pix",
    "peak": "adu", "flux": "adu", "n_pix": "pix2",
    "bkg_mean": "adu", "bkg_median": "adu", "bkg_rms": "adu",
    "exptime": "s", "ccd_temp": "deg_C", "objctaz": "deg", "objctalt": "deg",
    "ra": "deg", "dec": "deg",
}

COLUMN_DESCRIPTIONS = {
    "fwhm": "2.3548 * sqrt(sigma_major * sigma_minor), the geometric mean of the moment axes",
    "fwhm_gauss": "FWHM from an independent elliptical gaussian fit, as a cross-check on fwhm",
    "ellip": "1 - sigma_minor/sigma_major from windowed second moments",
    "pa": "position angle of the major axis, degrees CCW from +x",
    "concentration": "peak/flux normalized to the diffraction limited value; falls as light spreads out",
    "snr": "CCD equation when egain is known, otherwise flux / (bkg_rms * sqrt(n_pix))",
    "sep_pa": "position angle from star0 to star1, degrees CCW from +x",
    "flux_ratio": "star0_flux / star1_flux; use this to identify which mask aperture is which",
    "egain": "electrons per stored count; NaN when the camera is not recognized",
    "bitshift": "power of two the 12-bit samples were left-shifted by before storage",
    "snr_method": "'ccd' or 'background', recording how snr was computed",
    "status": "'ok', or why a frame yielded no measurements",
}


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


def relative_name(path, root=None):
    """The name a frame is recorded under: its path relative to the root, or just its basename."""
    path = Path(path)
    root = Path(root) if root is not None else path.parent
    try:
        return str(path.relative_to(root))
    except ValueError:
        return path.name


def analyze_image(path, root=None):
    """
    Measure one FITS frame and return a flat row.

    Never raises: an unreadable file or a frame with too few detections still returns a row, with
    `status` saying what happened, so a night that produced nothing stays distinguishable from a
    night that was never processed.
    """
    path = Path(path)
    row = _empty_row()
    row["filename"] = relative_name(path, root)
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
        if isinstance(value, str):
            row[_column_name(key)] = value.strip()
        elif isinstance(value, (int, float, bool)):
            row[_column_name(key)] = value
        # a keyword that is absent, or present with no value, keeps the typed empty from
        # _empty_row. Writing the None that header.get returns would make the column object dtype,
        # and one such frame is enough to stop the whole archive from stacking.
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


def _describe(table):
    """
    Attach units and descriptions, matching star0_/star1_ prefixed columns by suffix, and put the
    float columns in float32.

    Nothing measured here justifies float64: a float32 carries ~7 significant digits, against
    fluxes good to three and positions to a hundredth of a pixel. It halves the table and the
    cache. Every path that produces a table for writing goes through here, so entries cached as
    float64 before this are narrowed when they are collected.
    """
    for name in table.colnames:
        if table[name].dtype == np.float64:
            table[name] = table[name].astype(np.float32)
    for name in table.colnames:
        suffix = name.split("_", 1)[1] if name.startswith(("star0_", "star1_")) else name
        if suffix in COLUMN_UNITS:
            table[name].unit = COLUMN_UNITS[suffix]
        if suffix in COLUMN_DESCRIPTIONS:
            table[name].description = COLUMN_DESCRIPTIONS[suffix]
    return table


def build_table(rows):
    """Build an annotated table from analyze_image() rows."""
    return _describe(Table(rows=rows))


def merge_tables(existing, new):
    """Stack two tables and keep the last row for each filename, so re-runs are idempotent."""
    merged = vstack([existing, new], metadata_conflicts="silent")
    merged["_order"] = range(len(merged))
    merged.sort(["filename", "_order"])
    keep = [i for i, name in enumerate(merged["filename"])
            if i + 1 == len(merged) or merged["filename"][i + 1] != name]
    merged = merged[keep]
    merged.remove_column("_order")
    merged.sort("filename")
    return merged


def sort_by_time(table):
    """Sort a table into time order, breaking ties on filename so the order is reproducible."""
    if len(table) == 0:
        return table
    table.sort(["date_obs", "filename"])
    return table


def cache_path(cache_dir, filename):
    """
    Where one frame's row is cached. Directory separators become double underscores, so the flat
    cache directory keeps one entry per source frame even when two targets share a file name.
    """
    return Path(cache_dir) / (str(filename).replace("/", "__") + ".ecsv")


def write_cached_row(cache_dir, row):
    """
    Cache one frame's row as a single-row ECSV, written as it is measured.

    A run over the whole archive takes hours; holding every row in memory until the end means an
    interrupted run leaves nothing behind. Writing each row as it arrives makes the run resumable.
    """
    cache_dir = Path(cache_dir)
    cache_dir.mkdir(parents=True, exist_ok=True)
    path = cache_path(cache_dir, row["filename"])
    build_table([row]).write(path, format="ascii.ecsv", overwrite=True)
    return path


def _retype(entry):
    """
    Force an entry's columns to the schema's types.

    Entries are stacked by the thousand, and vstack refuses to merge a column that is text in one
    entry and a number in another, so a single odd frame stops the whole archive from collecting.
    Types drift for real reasons: a keyword missing from one frame's header used to cache a bare
    None, which reads back as an object column, and a keyword astropy reads as an int in one frame
    and a float in another. The schema in _empty_row says what each column should be; anything
    that will not convert was not a usable value to begin with and becomes the typed empty.
    """
    empty = _empty_row()
    for name in entry.colnames:
        if name not in empty:
            continue
        # only the kind has to match: string widths are per entry and vstack reconciles them, and
        # narrowing float64 entries to float32 here rather than once at the end costs ~2 ms an
        # entry, which over the archive is minutes to save the few MB the chunks hold
        want = np.array(empty[name]).dtype
        if entry[name].dtype.kind == want.kind:
            continue
        try:
            if want.kind == "U":
                # str() of a missing value would spell it out as "None" or "--" rather than leave
                # it empty, so map anything unset to the empty string on the way
                entry[name] = ["" if value is None or value is np.ma.masked else str(value) for value in entry[name]]
            else:
                entry[name] = entry[name].astype(want)
        except (ValueError, TypeError):
            entry[name] = [empty[name]] * len(entry)
    return entry


def _stack(tables):
    """Stack tables, skipping the copy vstack would make of a lone one."""
    return tables[0] if len(tables) == 1 else vstack(tables, metadata_conflicts="silent")


#: cached rows read between progress lines, so a collect over the whole archive is not silent
PROGRESS_EVERY = 5000

#: entries stacked at a time. Each unstacked entry holds ~53 kB, so this sets the memory a collect
#: spends on entries waiting to be stacked, independent of how large the cache has grown
COLLECT_CHUNK = 2000


def read_cached_rows(cache_dir, names=None, progress=False):
    """
    Stack cached rows into one table, or return None if the cache holds nothing usable.

    Reading one row costs a few ms, so collecting a cache grown to the size of the archive takes
    tens of minutes. Pass `names` to read only the frames a run touched; leave it None to rebuild
    from everything, which is worth doing once to seed a table and rarely after that.

    Entries are stacked COLLECT_CHUNK at a time rather than held for one closing vstack. A
    single-row Table costs ~53 kB resident against ~0.8 kB once it is packed into a stacked table,
    so collecting the whole archive in one go needs ~13 GB and swaps; chunked it needs a few
    hundred MB, and the peak no longer grows with the size of the cache.

    The stacking has to go through vstack rather than pulling values out into rows: an empty
    string round trips through ECSV as a masked value, and a row carrying one cannot say what
    dtype its column should be.
    """
    cache_dir = Path(cache_dir)
    if not cache_dir.is_dir():
        return None
    if names is None:
        paths = sorted(cache_dir.glob("*.ecsv"))
    else:
        paths = [path for path in (cache_path(cache_dir, name) for name in names) if path.exists()]

    chunks, entries = [], []
    for index, path in enumerate(paths, start=1):
        try:
            entries.append(_retype(Table.read(path, format="ascii.ecsv")))
        except Exception as error:
            print(f"skipping unreadable cache entry {path.name}: {error}")
        if len(entries) >= COLLECT_CHUNK:
            chunks.append(_stack(entries))
            entries = []
        if progress and index % PROGRESS_EVERY == 0:
            print(f"collected {index}/{len(paths)} cached rows")
    if entries:
        chunks.append(_stack(entries))
    if not chunks:
        return None
    return _describe(_stack(chunks))


def measure_and_cache(job):
    """
    Measure one frame and cache its row, returning the row.

    Takes a single tuple and lives at module scope so it can be handed to a worker process. The
    caching happens in the worker, which keeps the ECSV writes off the parent's critical path.
    """
    path, root, cache_dir = job
    row = analyze_image(path, root=root)
    write_cached_row(cache_dir, row)
    return row


#: frames submitted to the pool at a time, to bound the memory held by pending work
BATCH_SIZE = 500


def measure_frames(jobs, workers=1):
    """Yield a row per job, in the order the jobs were given, using `workers` processes."""
    if workers <= 1:
        for job in jobs:
            yield measure_and_cache(job)
        return

    # one BLAS thread per worker. Left alone, each worker spawns its own thread pool and they
    # fight over the same cores; the arrays here are too small for the threading to pay anyway.
    for variable in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS", "NUMEXPR_NUM_THREADS"):
        os.environ.setdefault(variable, "1")

    # spawn rather than fork, so the workers import numpy fresh and honor the settings above; a
    # forked child would inherit this process's already-initialized, already-threaded copy
    context = multiprocessing.get_context("spawn")
    with ProcessPoolExecutor(max_workers=workers, mp_context=context) as pool:
        for start in range(0, len(jobs), BATCH_SIZE):
            batch = jobs[start:start + BATCH_SIZE]
            yield from pool.map(measure_and_cache, batch, chunksize=max(1, len(batch) // (workers * 4)))


def _progress(index, total, name, row=None):
    """One line per frame, so a long run over the archive shows where it has got to."""
    if row is None:
        note = "cached"
    elif row["status"] != "ok":
        note = row["status"]
    else:
        note = (f"{row['n_stars']} stars  fwhm {row['star0_fwhm']:.1f}/{row['star1_fwhm']:.1f} pix"
                f"  sep {row['sep_pix']:.1f} pix")
    print(f"[{index}/{total}] {name}  {note}", flush=True)


def main(argv=None):
    parser = argparse.ArgumentParser(description="Analyze the single exposures taken before each seeing measurement")
    parser.add_argument("--root", default=str(Path.home() / "Pictures"), help="directory holding <target>/<imagetype>/")
    selection = parser.add_mutually_exclusive_group()
    selection.add_argument("--all", action="store_true", help="process every frame under --root")
    selection.add_argument("--night", help="process one night, as YYYY-MM-DD")
    selection.add_argument("--last-night", action="store_true", help="process the previous night")
    parser.add_argument("-o", "--output", required=True, help="output table")
    parser.add_argument("--format", choices=["ecsv", "csv"], default="ecsv", help="output format")
    parser.add_argument("--cache-dir", help="per-frame result cache; defaults to <output>.parts")
    parser.add_argument("--reprocess", action="store_true", help="reanalyze frames that are already cached")
    parser.add_argument("--collect-cache", action="store_true",
                        help="build the output from every cache entry, not just the frames in this run")
    parser.add_argument("--append", action="store_true", help="merge into an existing table, replacing matching rows")
    parser.add_argument("-j", "--jobs", type=int, default=1, help="worker processes to measure frames with")
    parser.add_argument("-q", "--quiet", action="store_true", help="suppress per-frame progress")
    args = parser.parse_args(argv)

    output = Path(args.output)
    cache_dir = Path(args.cache_dir) if args.cache_dir else output.with_name(output.name + ".parts")
    table_format = "ascii.ecsv" if args.format == "ecsv" else "ascii.csv"

    night = last_night() if args.last_night else args.night
    paths = find_images(args.root, night=night)
    if not paths:
        print(f"no images found under {args.root}" + (f" for night {night}" if night else ""))
        return 1

    total = len(paths)
    names = [relative_name(path, args.root) for path in paths]

    pending = []
    for index, (path, name) in enumerate(zip(paths, names), start=1):
        if not args.reprocess and cache_path(cache_dir, name).exists():
            if not args.quiet:
                _progress(index, total, name)
            continue
        pending.append((index, name, (path, args.root, cache_dir)))

    for (index, name, _), row in zip(pending, measure_frames([job for _, _, job in pending], workers=args.jobs)):
        if not args.quiet:
            _progress(index, total, name, row)

    # every row now lives on disk; the output is just the cache collected and put in time order
    table = read_cached_rows(cache_dir, names=None if args.collect_cache else names, progress=not args.quiet)
    if table is None:
        print(f"no results cached in {cache_dir}")
        return 1

    if args.append and output.exists():
        table = _describe(merge_tables(Table.read(output, format=table_format), table))

    table = sort_by_time(table)
    table.write(output, format=table_format, overwrite=True)
    print(f"wrote {len(table)} rows to {output}")
    return 0
