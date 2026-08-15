# analyze_pictures Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Analyze the single pre-seeing exposures under `~/Pictures/<target>/Light/` — background, two-spot photometry, size, elongation and smearing — and write one row per image to an ECSV table, runnable both in batch over the archive and daily on the previous night.

**Architecture:** Two new modules. `detector.py` converts the ZWO gain index to e-/ADU and detects the 12-bit-into-16-bit left shift; it has no dependency on the rest of the package. `analyze_pictures.py` holds image discovery, background measurement, per-star measurement, row assembly and the CLI. Every measurement is derived from `photutils.aperture.ApertureStats` on an aperture whose radius is iterated to fit the spot, with an `astropy.modeling` Gaussian fit as an independent cross-check.

**Tech Stack:** numpy 2.5, astropy 8.0 (`io.fits`, `stats`, `modeling`, `table`, `units`), photutils 3.0 (`detection.DAOStarFinder`, `aperture.ApertureStats`), pytest.

## Global Constraints

- Line length 132 (`flake8 src/timdimm_tng --count --max-line-length=132`)
- Python 3.12+
- astropy units for physical quantities, per existing modules
- Spec: `docs/superpowers/specs/2026-08-10-analyze-pictures-design.md`
- `star0`/`star1` are **x-sorted positional labels, not aperture identities** — the camera orientation changed during the archive. Never infer aperture identity.
- `analyze_image()` must never raise. Bad frames produce a row with a `status` string.
- Tests use `pytest`, live in `src/timdimm_tng/tests/`, and follow the existing files' plain-function style (no classes, no fixtures beyond `tmp_path`).

---

### Task 1: Detector gain conversion

**Files:**
- Create: `src/timdimm_tng/detector.py`
- Test: `src/timdimm_tng/tests/test_detector.py`

**Interfaces:**
- Consumes: nothing
- Produces:
  - `detect_bitshift(data) -> int`
  - `asi432_egain(gain_index) -> float` (e-/ADU at 12-bit)
  - `egain_from_header(header, data) -> tuple[float, int, str]` returning `(egain, bitshift, snr_method)`; `egain` is e- per **stored count** and is `float("nan")` when the camera is unrecognized; `snr_method` is `"ccd"` or `"background"`

Background: the IMX432 ADC is 12-bit and the driver left-shifts by 4 into uint16, so every stored value is a multiple of 16. EGAIN is referenced to 12-bit ADU, so the shift must be divided back out. The curve is anchored at its gain-0 intercept `97000 / 2**12 = 23.68` e-/ADU, where ZWO's EGAIN and full-well panels agree. This puts unity gain at index 274.9 rather than the published 272 — a deliberate 1% trade to match the plotted curve across its whole range.

- [ ] **Step 1: Write the failing tests**

```python
# src/timdimm_tng/tests/test_detector.py
import numpy as np
import pytest

from timdimm_tng.detector import ASI432_EGAIN_0, asi432_egain, detect_bitshift, egain_from_header


def test_egain_at_gain_zero_is_the_full_well_intercept():
    # 97000 e- full well over a 12-bit ADC
    assert asi432_egain(0) == pytest.approx(97000 / 2**12, rel=1e-6)
    assert ASI432_EGAIN_0 == pytest.approx(23.68, abs=0.01)


def test_egain_crosses_unity_near_index_275():
    # 0.1 dB per index step, so egain falls by 10x every 200 index counts
    assert asi432_egain(274.9) == pytest.approx(1.0, rel=0.01)
    assert asi432_egain(200) / asi432_egain(400) == pytest.approx(10.0, rel=1e-6)


def test_egain_at_operational_gain_350():
    assert asi432_egain(350) == pytest.approx(0.421, abs=0.002)


def test_detect_bitshift_finds_the_four_bit_left_shift():
    rng = np.random.default_rng(0)
    twelve_bit = rng.integers(0, 4096, size=(64, 64))
    assert detect_bitshift(twelve_bit * 16) == 16


def test_detect_bitshift_returns_one_for_unshifted_data():
    rng = np.random.default_rng(0)
    # random 16-bit data is not uniformly divisible by 2
    assert detect_bitshift(rng.integers(0, 65536, size=(64, 64))) == 1


def test_detect_bitshift_caps_at_sixteen():
    # data that happens to be divisible by 64 must still report at most 16
    rng = np.random.default_rng(0)
    assert detect_bitshift(rng.integers(0, 1024, size=(64, 64)) * 64) == 16


def test_egain_from_header_uses_the_ccd_equation_for_the_asi432():
    rng = np.random.default_rng(0)
    data = rng.integers(0, 4096, size=(64, 64)) * 16
    header = {"INSTRUME": "ZWO CCD ASI432MM", "GAIN": 350}
    egain, bitshift, method = egain_from_header(header, data)
    assert bitshift == 16
    assert method == "ccd"
    # e- per stored count is the 12-bit egain divided by the shift
    assert egain == pytest.approx(0.421 / 16, abs=1e-4)


def test_egain_from_header_falls_back_for_an_unknown_camera():
    rng = np.random.default_rng(0)
    data = rng.integers(0, 4096, size=(64, 64)) * 16
    header = {"INSTRUME": "Some Other Camera", "GAIN": 350}
    egain, bitshift, method = egain_from_header(header, data)
    assert np.isnan(egain)
    assert method == "background"


def test_egain_from_header_falls_back_when_gain_is_missing():
    rng = np.random.default_rng(0)
    data = rng.integers(0, 4096, size=(64, 64)) * 16
    egain, _, method = egain_from_header({"INSTRUME": "ZWO CCD ASI432MM"}, data)
    assert np.isnan(egain)
    assert method == "background"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest src/timdimm_tng/tests/test_detector.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'timdimm_tng.detector'`

- [ ] **Step 3: Write the implementation**

```python
# src/timdimm_tng/detector.py
"""
Convert ZWO camera gain indices into e-/ADU.

ZWO report gain as an index in units of 0.1 dB, not as a conversion factor, so eGain falls
by a factor of 10 every 200 index counts. For the ASI432MM (IMX432) the curve is anchored at
its gain-0 intercept, 97000 e- of full well over a 12-bit ADC, which is where ZWO's own EGAIN
and full-well panels agree with each other. That puts unity gain at index 274.9 rather than
the 272 they publish; the 1% offset buys agreement with the plotted curve at every other gain.
"""

import numpy as np

#: full well of the IMX432 in electrons, from ZWO's published curves
ASI432_FULL_WELL = 97000.0

#: ADC bit depth of the IMX432
ASI432_ADC_BITS = 12

#: e-/ADU at gain index 0, referenced to 12-bit ADU
ASI432_EGAIN_0 = ASI432_FULL_WELL / 2**ASI432_ADC_BITS

#: the driver left-shifts 12-bit samples into uint16, so counts are multiples of 16
MAX_BITSHIFT = 16


def asi432_egain(gain_index):
    """
    eGain of an ASI432MM in e-/ADU at 12-bit, for a ZWO gain index in units of 0.1 dB.
    """
    return ASI432_EGAIN_0 * 10.0 ** (-gain_index / 200.0)


def detect_bitshift(data):
    """
    Return the power-of-two factor the data has been left-shifted by, capped at MAX_BITSHIFT.

    The IMX432 is a 12-bit sensor whose samples are left-shifted into uint16, so every count is
    a multiple of 16. This is detected rather than assumed: if a driver update ever stops
    shifting, assuming a shift would inflate every derived electron count by 16x.
    """
    values = np.asarray(data).astype(np.int64).ravel()
    nonzero = values[values != 0]
    if nonzero.size == 0:
        return 1
    shift = 1
    while shift < MAX_BITSHIFT and np.all(nonzero % (shift * 2) == 0):
        shift *= 2
    return shift


def egain_from_header(header, data):
    """
    Work out e- per stored count from a FITS header and its data.

    Returns (egain, bitshift, snr_method). The ASI432MM calibration above is the only one we
    have, so any other camera returns NaN and signals that the caller should fall back to a
    background-limited SNR rather than a CCD-equation one.
    """
    bitshift = detect_bitshift(data)
    instrument = str(header.get("INSTRUME", "")).upper()
    gain = header.get("GAIN")
    if "ASI432" not in instrument or gain is None:
        return float("nan"), bitshift, "background"
    return asi432_egain(float(gain)) / bitshift, bitshift, "ccd"
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest src/timdimm_tng/tests/test_detector.py -v`
Expected: PASS, 9 tests, no warnings

- [ ] **Step 5: Check style**

Run: `flake8 src/timdimm_tng/detector.py src/timdimm_tng/tests/test_detector.py --count --max-line-length=132`
Expected: `0`

- [ ] **Step 6: Commit**

```bash
git add src/timdimm_tng/detector.py src/timdimm_tng/tests/test_detector.py
git commit -m "convert the zwo gain index to e-/adu for the asi432mm"
```

---

### Task 2: Synthetic frame helper and background measurement

**Files:**
- Create: `src/timdimm_tng/analyze_pictures.py`
- Test: `src/timdimm_tng/tests/test_analyze_pictures.py`

**Interfaces:**
- Consumes: nothing from Task 1 yet
- Produces:
  - `make_test_frame(positions, fluxes, sigma_x=3.0, sigma_y=3.0, theta=0.0, bkg=1550.0, rms=20.0, shape=(300, 300), seed=42) -> np.ndarray` — lives in the test module, used by Tasks 2-4
  - `measure_background(data) -> dict` with keys `bkg_mean`, `bkg_median`, `bkg_rms`

The synthetic frame is the backbone of every later test, so it is built first and its own recovery is verified before anything depends on it. Defaults mimic the real frames: background 1550 counts, RMS matched to the ~100 counts measured in the archive, spots ~50 px apart.

- [ ] **Step 1: Write the failing test**

```python
# src/timdimm_tng/tests/test_analyze_pictures.py
import numpy as np
import pytest
from astropy.modeling.models import Gaussian2D

from timdimm_tng.analyze_pictures import measure_background


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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest src/timdimm_tng/tests/test_analyze_pictures.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'timdimm_tng.analyze_pictures'`

- [ ] **Step 3: Write the implementation**

```python
# src/timdimm_tng/analyze_pictures.py
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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest src/timdimm_tng/tests/test_analyze_pictures.py -v`
Expected: PASS, 3 tests

- [ ] **Step 5: Commit**

```bash
git add src/timdimm_tng/analyze_pictures.py src/timdimm_tng/tests/test_analyze_pictures.py
git commit -m "measure background level and noise in the pre-seeing exposures"
```

---

### Task 3: Per-star measurement

**Files:**
- Modify: `src/timdimm_tng/analyze_pictures.py`
- Modify: `src/timdimm_tng/tests/test_analyze_pictures.py`

**Interfaces:**
- Consumes: `measure_background()` from Task 2; `egain_from_header()` from Task 1 is used in Task 4, not here
- Produces: `measure_stars(data, bkg_rms, egain=float("nan"), pixel_scale=0.7427, aperture_diameter=50.0, wavelength=0.64, threshold=10.0, max_stars=2) -> list[dict]`, each dict holding `x`, `y`, `peak`, `flux`, `snr`, `fwhm`, `fwhm_gauss`, `sigma_major`, `sigma_minor`, `ellip`, `pa`, `sharpness`, `concentration`, `fit_ok`, `aper_radius`, `n_pix`. The list is sorted by `x` ascending and may be shorter than `max_stars`, including empty.

Three things here were established by measurement on synthetic frames and must not be simplified away:

1. **The aperture radius is iterated on the semi-major axis.** A fixed radius truncates a smeared spot along its long axis and biases the ellipticity low — a spot with true ellipticity 0.667 measured 0.60 at fixed `r=12`, and 0.71 once the radius was iterated to `3 * sigma_major`. Since smearing is the point of the whole exercise, that bias is unacceptable.
2. **`fwhm` is the geometric mean `2.3548 * sqrt(a * b)`, not photutils' `ApertureStats.fwhm`,** which is the quadrature mean `2.3548 * sqrt((a**2 + b**2)/2)`. They differ by 12% at ellipticity 0.5. The geometric mean is area-preserving, which is what is wanted for a seeing-like number. Do not substitute `stats.fwhm`.
3. **The background annulus scales with the aperture.** A fixed annulus sits on the wings of a large spot, oversubtracts, and shrinks the measured minor axis.

- [ ] **Step 1: Write the failing tests**

Append to `src/timdimm_tng/tests/test_analyze_pictures.py`:

```python
from timdimm_tng.analyze_pictures import measure_stars


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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest src/timdimm_tng/tests/test_analyze_pictures.py -v`
Expected: FAIL — `ImportError: cannot import name 'measure_stars'`

- [ ] **Step 3: Write the implementation**

Add to `src/timdimm_tng/analyze_pictures.py` (extend the imports at the top):

```python
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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest src/timdimm_tng/tests/test_analyze_pictures.py -v`
Expected: PASS, 15 tests

If `test_a_smeared_spot_reports_its_elongation_and_angle` fails marginally, do **not** loosen the tolerance without first printing the measured `sigma_major`, `sigma_minor` and `aper_radius`. Prototyping measured `ellip = 0.71` and `pa = 29.6` for this case; a result far from that means the radius iteration is not converging, not that the tolerance is wrong.

- [ ] **Step 5: Check style**

Run: `flake8 src/timdimm_tng/analyze_pictures.py src/timdimm_tng/tests/test_analyze_pictures.py --count --max-line-length=132`
Expected: `0`

- [ ] **Step 6: Commit**

```bash
git add src/timdimm_tng/analyze_pictures.py src/timdimm_tng/tests/test_analyze_pictures.py
git commit -m "photometry, size and elongation for the two dimm spots"
```

---

### Task 4: Row assembly from a FITS file

**Files:**
- Modify: `src/timdimm_tng/analyze_pictures.py`
- Modify: `src/timdimm_tng/tests/test_analyze_pictures.py`

**Interfaces:**
- Consumes: `egain_from_header()` (Task 1), `measure_background()` (Task 2), `measure_stars()` (Task 3)
- Produces:
  - `HEADER_KEYS` — the 13 keywords from `header.txt`
  - `analyze_image(path, root=None) -> dict` — one flat row, never raises

The header subset is exactly the 13 keywords in `~/SAAO/timdimm_data/header.txt`, lower-cased with `-` replaced by `_`: `exptime`, `ccd_temp`, `airmass`, `objctaz`, `objctalt`, `ra`, `dec`, `pierside`, `equinox`, `date_obs`, `gain`, `offset`, `object`.

- [ ] **Step 1: Write the failing tests**

Append to `src/timdimm_tng/tests/test_analyze_pictures.py`:

```python
from astropy.io import fits

from timdimm_tng.analyze_pictures import analyze_image


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
    assert row["bkg_median"] == pytest.approx(1550.0, abs=2.0)


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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest src/timdimm_tng/tests/test_analyze_pictures.py -v`
Expected: FAIL — `ImportError: cannot import name 'analyze_image'`

- [ ] **Step 3: Write the implementation**

Add to `src/timdimm_tng/analyze_pictures.py` (extend the imports):

```python
from pathlib import Path

from astropy.io import fits

from timdimm_tng.detector import egain_from_header

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
```

`analyze_image()` calls `night_of()`, whose own tests come in Task 5. Add its full implementation
here so this task's tests can run — Task 5 adds tests for it, not code:

```python
def night_of(date_obs, sitelong=None):
    """
    Label for the observing night: the local-solar-time date at the start of the night.

    Nights run local noon to local noon, so subtracting 12 hours from the local time and taking
    the date gives every frame in one night the same label.
    """
    if not date_obs:
        return ""
    from astropy.time import Time, TimeDelta
    longitude = SAAO_LONGITUDE if sitelong is None else float(sitelong)
    local = Time(date_obs, format="isot", scale="utc") + TimeDelta(longitude / 15.0 * 3600.0, format="sec")
    return (local - TimeDelta(12.0 * 3600.0, format="sec")).isot[:10]
```

and the constant, near the other module constants:

```python
#: SAAO longitude in degrees east, used when a frame has no SITELONG
SAAO_LONGITUDE = 20.8107
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest src/timdimm_tng/tests/test_analyze_pictures.py -v`
Expected: PASS, 25 tests

- [ ] **Step 5: Check style**

Run: `flake8 src/timdimm_tng --count --max-line-length=132`
Expected: `0`

- [ ] **Step 6: Commit**

```bash
git add src/timdimm_tng/analyze_pictures.py src/timdimm_tng/tests/test_analyze_pictures.py
git commit -m "assemble one output row per analyzed frame"
```

---

### Task 5: Image discovery and night selection

**Files:**
- Modify: `src/timdimm_tng/analyze_pictures.py`
- Modify: `src/timdimm_tng/tests/test_analyze_pictures.py`

**Interfaces:**
- Consumes: `night_of()` from Task 4
- Produces: `find_images(root, night=None) -> list[Path]` — sorted, matching `*.fits` and `*.fits.gz`; `last_night(now=None) -> str`

`Pictures/` is flat — `<target>/<imagetype>/<file>` with no per-night directories — so nights are selected by reading `DATE-OBS` from each header, not from the path. Headers only are read here; pixel data is not touched.

- [ ] **Step 1: Write the failing tests**

Append to `src/timdimm_tng/tests/test_analyze_pictures.py`:

```python
from timdimm_tng.analyze_pictures import find_images, last_night, night_of


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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest src/timdimm_tng/tests/test_analyze_pictures.py -v`
Expected: FAIL — `ImportError: cannot import name 'find_images'`

- [ ] **Step 3: Write the implementation**

Move the local `Time`/`TimeDelta` import in `night_of()` to the module imports, and add:

```python
from astropy.time import Time, TimeDelta


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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest src/timdimm_tng/tests/test_analyze_pictures.py -v`
Expected: PASS, 32 tests

- [ ] **Step 5: Commit**

```bash
git add src/timdimm_tng/analyze_pictures.py src/timdimm_tng/tests/test_analyze_pictures.py
git commit -m "find frames by night from date-obs rather than by directory"
```

---

### Task 6: Table output, append/dedup, and the CLI

**Files:**
- Modify: `src/timdimm_tng/analyze_pictures.py`
- Modify: `src/timdimm_tng/tests/test_analyze_pictures.py`
- Modify: `pyproject.toml` (add to `[project.scripts]`)

**Interfaces:**
- Consumes: everything above
- Produces: `build_table(rows) -> astropy.table.Table`, `merge_tables(existing, new) -> Table`, `main(argv=None) -> int`

`--append` must be idempotent: re-running a night replaces that night's rows rather than duplicating them, keyed on `filename`.

- [ ] **Step 1: Write the failing tests**

Append to `src/timdimm_tng/tests/test_analyze_pictures.py`:

```python
from astropy.table import Table

from timdimm_tng.analyze_pictures import build_table, main, merge_tables


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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest src/timdimm_tng/tests/test_analyze_pictures.py -v`
Expected: FAIL — `ImportError: cannot import name 'build_table'`

- [ ] **Step 3: Write the implementation**

Add to `src/timdimm_tng/analyze_pictures.py`:

```python
import argparse

from astropy.table import Table, vstack

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


def _describe(table):
    """Attach units and descriptions, matching star0_/star1_ prefixed columns by suffix."""
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


def main(argv=None):
    parser = argparse.ArgumentParser(description="Analyze the single exposures taken before each seeing measurement")
    parser.add_argument("--root", default=str(Path.home() / "Pictures"), help="directory holding <target>/<imagetype>/")
    selection = parser.add_mutually_exclusive_group()
    selection.add_argument("--all", action="store_true", help="process every frame under --root")
    selection.add_argument("--night", help="process one night, as YYYY-MM-DD")
    selection.add_argument("--last-night", action="store_true", help="process the previous night")
    parser.add_argument("-o", "--output", required=True, help="output table")
    parser.add_argument("--format", choices=["ecsv", "csv"], default="ecsv", help="output format")
    parser.add_argument("--append", action="store_true", help="merge into an existing table, replacing matching rows")
    args = parser.parse_args(argv)

    night = last_night() if args.last_night else args.night
    paths = find_images(args.root, night=night)
    if not paths:
        print(f"no images found under {args.root}" + (f" for night {night}" if night else ""))
        return 1

    table = build_table([analyze_image(path, root=args.root) for path in paths])

    output = Path(args.output)
    if args.append and output.exists():
        existing = Table.read(output, format="ascii.ecsv" if args.format == "ecsv" else "ascii.csv")
        table = _describe(merge_tables(existing, table))

    table.write(output, format="ascii.ecsv" if args.format == "ecsv" else "ascii.csv", overwrite=True)
    print(f"wrote {len(table)} rows to {output}")
    return 0
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest src/timdimm_tng/tests/test_analyze_pictures.py -v`
Expected: PASS, 40 tests

- [ ] **Step 5: Add the console entry point**

In `pyproject.toml`, under `[project.scripts]`, after the `hdimm_analyze` line:

```toml
analyze_pictures = "timdimm_tng.analyze_pictures:main"
```

- [ ] **Step 6: Verify the entry point resolves**

Run: `pip install -e . --no-deps -q && analyze_pictures --help`
Expected: the argparse help text, listing `--root`, `--all`, `--night`, `--last-night`, `-o`, `--format`, `--append`

- [ ] **Step 7: Check style**

Run: `flake8 src/timdimm_tng --count --max-line-length=132`
Expected: `0`

- [ ] **Step 8: Commit**

```bash
git add src/timdimm_tng/analyze_pictures.py src/timdimm_tng/tests/test_analyze_pictures.py pyproject.toml
git commit -m "write measurements to ecsv and add the analyze_pictures entry point"
```

---

### Task 7: End-to-end check against the real archive

**Files:**
- Modify: `src/timdimm_tng/tests/test_analyze_pictures.py`

**Interfaces:**
- Consumes: everything above
- Produces: nothing new

The five archived Achernar frames at `~/SAAO/timdimm_data/Pictures` are a smoke test only. Their true values are unknown, so this asserts that the pipeline runs on real compressed data and produces physically sane numbers — never exact ones. The test skips when the data is absent, so it does not break CI or a fresh checkout.

Reference values measured from these frames during design, for orientation only: background median 1552 counts, background RMS ~100 counts, two spots per frame about 50 px apart, peak counts 6700-16500.

- [ ] **Step 1: Write the test**

Append to `src/timdimm_tng/tests/test_analyze_pictures.py`:

```python
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
```

- [ ] **Step 2: Run the full suite**

Run: `pytest src/timdimm_tng/tests/test_analyze_pictures.py src/timdimm_tng/tests/test_detector.py -v`
Expected: PASS, 50 tests, none skipped on this machine

If any archive assertion fails, report the measured values rather than adjusting the bound — a real frame disagreeing with the synthetic tests is a finding, not a tolerance problem.

- [ ] **Step 3: Run the CLI over the archive by hand**

Run: `analyze_pictures --root ~/SAAO/timdimm_data/Pictures --all -o /tmp/archive.ecsv && head -60 /tmp/archive.ecsv`
Expected: `wrote 5 rows`, and an ECSV header carrying the units and descriptions

- [ ] **Step 4: Run the whole test suite for regressions**

Run: `pytest src/timdimm_tng/tests -q`
Expected: all pass, no new failures in the pre-existing tests

- [ ] **Step 5: Commit**

```bash
git add src/timdimm_tng/tests/test_analyze_pictures.py
git commit -m "smoke test analyze_pictures against the archived achernar frames"
```

---

## Notes for the implementer

- **Do not swap the geometric-mean FWHM for `ApertureStats.fwhm`.** photutils uses the quadrature mean; on a smeared spot the two differ by 12%. Task 3 explains why.
- **Do not replace the aperture-radius iteration with a fixed radius.** It was added because a fixed radius biased a true 0.667 ellipticity down to 0.60, and elongation is the measurement this whole script exists to make.
- **`star0`/`star1` are positional.** The camera orientation changed partway through the archive, so they do not identify mask apertures. `flux_ratio` and `sep_pa` are recorded so that can be sorted out downstream.
- The `night` label uses local *solar* time from `SITELONG`, deliberately avoiding a timezone database.
