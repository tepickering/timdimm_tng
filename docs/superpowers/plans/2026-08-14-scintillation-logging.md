# Scintillation Logging Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Log prism throughput, a scintillation index, and two time constants to a new
`~/scintillation.csv` for every seeing measurement.

**Architecture:** A new pure module `src/timdimm_tng/scintillation.py` turns the dict that
`analyze_dimm_cube` already returns into a row of scalars. It does no file I/O and loads no cubes, so
every estimator is testable against synthetic series with analytically known answers.
`scripts/ekos_timdimm/postcapture.py` calls it and appends the row. One additive change to
`analyze_dimm_cube` is a prerequisite: it must report which cube frames survived centroiding.

**Tech Stack:** Python 3.13+, numpy, astropy (`Time`, units), pytest.

**Spec:** `docs/superpowers/specs/2026-08-14-scintillation-logging-design.md`. Background,
prior measurements and the estimator pitfalls are in `docs/scintillation_logging_notes.md`.

## Global Constraints

- **`seeing.csv` is frozen.** No columns may be added to it. Nothing in this plan touches how
  `~/seeing.csv` is written.
- **HDIMM is out of scope.** `scripts/ekos_hdimm/postcapture.py` is not modified.
- **No acquisition changes.** No edits to ROI, exposure time or frame rate.
- Line length 132 characters. `flake8 src/timdimm_tng --count --max-line-length=132` must pass.
- Python 3.13+.
- Work on the `flux-ratio-logging` branch. Do not push it — it is deliberately held local.
- Degenerate inputs return `float("nan")`. They never raise and never suppress a row.

## File Structure

| File | Responsibility |
|---|---|
| `src/timdimm_tng/scintillation.py` | **New.** All estimators, plus the CSV header and row formatting. Pure functions, no I/O. |
| `src/timdimm_tng/tests/test_scintillation.py` | **New.** Tests for the above, all on synthetic data. |
| `src/timdimm_tng/tests/ser_helpers.py` | **New.** `write_ser`, moved out of `test_ser.py` and generalised so cubes of any shape can be built. |
| `src/timdimm_tng/tests/test_ser.py` | **Modify.** Import `write_ser` from the helper instead of defining it. |
| `src/timdimm_tng/analyze_cube.py` | **Modify.** `analyze_dimm_cube` returns `frame_index`. |
| `src/timdimm_tng/tests/test_analyze_cube.py` | **New.** First tests for `analyze_dimm_cube`, covering `frame_index`. |
| `scripts/ekos_timdimm/postcapture.py` | **Modify.** Call the stats function, append the row, fix an unrelated `NameError`. |

## Module API

Every later task depends on these exact names. `scintillation.py` defines:

```python
MIN_KEPT = 50                  # below this, the stats are NaN
MIN_PAIRS = 30                 # a lag with fewer contributing pairs is not used
ACF1_CENSOR_THRESHOLD = 0.2    # rho(1) below this means the time constant is unresolved
FIT_LAGS = (1, 2, 3, 4)

CSV_HEADER: str

def assign_apertures(fluxes) -> tuple[np.ndarray, np.ndarray]        # -> (bright, faint)
def throughput(bright, faint) -> float
def flux_ratio(bright, faint) -> np.ndarray
def scint_index(ratio) -> float
def lag_autocorr(x, index, lag) -> tuple[float, int]                 # -> (rho, npairs)
def fit_tau(x, index, dt, lags=FIT_LAGS) -> float                    # seconds
def median_dt(frame_times) -> float                                  # seconds
def scintillation_stats(results) -> dict
def format_row(stats, time, target, exptime) -> str
```

`dt` and `fit_tau` are in **seconds** throughout the module. Only the output columns are in
milliseconds, and the conversion happens once, inside `scintillation_stats`.

## Shapes returned by `analyze_dimm_cube`

The implementer will not guess these correctly from the source. For a 2-aperture DIMM cube with
`n_kept` surviving frames:

| key | shape / type |
|---|---|
| `aperture_fluxes` | `list` of `n_kept` arrays of length 2 — index is x-sorted aperture order |
| `baseline_lengths` | `np.ndarray`, shape `(1, n_kept)` — **already transposed**, so the series is `results["baseline_lengths"][0]` |
| `aperture_positions` | `np.ndarray`, shape `(2, n_kept)` — common-mode motion. **Not used by this feature.** |
| `frame_times` | `astropy.time.Time` array, length `nframes` — the **whole** cube, not just kept frames |
| `N_bad` | `int` |
| `frame_index` | added in Task 1: `np.ndarray` of `int`, length `n_kept` |

---

### Task 1: `analyze_dimm_cube` reports which frames survived

`analyze_dimm_cube` appends to its result lists only when `dimm_calc` succeeds, but returns
`frame_times` for the whole cube. When `N_bad > 0` the series have different lengths and nothing
records which frames were dropped, so no estimator can place a sample in time. Everything else in
this plan depends on fixing that.

`write_ser` is moved to a helper module first because Task 1's test needs cubes with a different
shape than `test_ser.py` uses, and the current helper hard-codes 8x6 from module globals.

**Files:**
- Create: `src/timdimm_tng/tests/ser_helpers.py`
- Modify: `src/timdimm_tng/tests/test_ser.py:9-40` (remove `write_ser`, import it instead)
- Modify: `src/timdimm_tng/analyze_cube.py:327-373`
- Test: `src/timdimm_tng/tests/test_analyze_cube.py`

**Interfaces:**
- Consumes: nothing.
- Produces: `write_ser(path, frames=None, nframe_header=None, timestamps=None, depth=16)` in
  `timdimm_tng.tests.ser_helpers`, taking cube shape from `frames`. `analyze_dimm_cube` returns a
  dict that now includes `frame_index: np.ndarray[int]` with `len(frame_index) == len(aperture_fluxes)`.

- [ ] **Step 1: Move `write_ser` into a helper module, taking the shape from the frames**

Create `src/timdimm_tng/tests/ser_helpers.py`:

```python
"""Builders for synthetic SER cubes, shared by the reader tests and the cube-analysis tests."""

import struct

import numpy as np

WIDTH, HEIGHT, NFRAMES = 8, 6, 5
#: 100 ns ticks since 0001-01-01, i.e. the SER timestamp epoch. This is 2024-05-05T01:57 UTC.
START_TICKS = 638504710570000128
TICKS_PER_FRAME = 33000  # 3.3 ms


def write_ser(path, frames=None, nframe_header=None, timestamps=None, depth=16):
    """Write a minimal but spec-conforming SER file, with knobs for corrupting it.

    The cube dimensions come from ``frames``, so callers can build whatever shape they need.
    """
    if frames is None:
        frames = np.arange(NFRAMES * HEIGHT * WIDTH, dtype=np.uint16).reshape(NFRAMES, HEIGHT, WIDTH)
    frames = np.asarray(frames)
    nframes, height, width = frames.shape
    if nframe_header is None:
        nframe_header = nframes
    if timestamps is None:
        timestamps = START_TICKS + TICKS_PER_FRAME * np.arange(nframes, dtype=np.uint64)

    with open(path, "wb") as fp:
        fp.write(b"LUCAM-RECORDER")
        for value in (0, 0, 1, width, height, depth, nframe_header):
            fp.write(struct.pack("<I", value))
        for text in ("observer", "instrument", "telescope"):
            fp.write(text.encode().ljust(40, b"\0"))
        fp.write(struct.pack("<Q", START_TICKS))
        fp.write(struct.pack("<Q", START_TICKS))
        fp.write(np.asarray(frames, dtype=np.uint16 if depth > 8 else np.uint8).tobytes())
        fp.write(np.asarray(timestamps, dtype=np.uint64).tobytes())
    return path
```

In `src/timdimm_tng/tests/test_ser.py`, delete the `import struct` line, the `WIDTH`/`HEIGHT`/
`NFRAMES`/`START_TICKS`/`TICKS_PER_FRAME` constants and the whole `write_ser` function, and replace
them with:

```python
from timdimm_tng.tests.ser_helpers import HEIGHT, NFRAMES, START_TICKS, TICKS_PER_FRAME, WIDTH, write_ser
```

Note `write_ser`'s parameter order changed (`frames` is now second). Every existing call in
`test_ser.py` uses keywords, so none of them need editing.

- [ ] **Step 2: Verify the SER tests still pass unchanged**

Run: `pytest src/timdimm_tng/tests/test_ser.py -v`
Expected: all 5 PASS. This is a pure move — if anything fails, the move was wrong.

- [ ] **Step 3: Write the failing tests for `frame_index`**

Create `src/timdimm_tng/tests/test_analyze_cube.py`:

```python
"""
Tests for the DIMM cube analysis.

The returned series are compacted past frames where centroiding failed, but ``frame_times`` covers
the whole cube. Without ``frame_index`` there is no way to say when any given sample was taken, and
any lag-based estimator silently shifts the series against each other.
"""

import numpy as np
import pytest

from timdimm_tng.analyze_cube import analyze_dimm_cube
from timdimm_tng.tests.ser_helpers import write_ser

SIZE = 60
SPOT_X = (15, 45)
SPOT_Y = 30


def dimm_frames(nframes, bad=(), rng=None):
    """A cube of two Gaussian spots. Frames listed in ``bad`` are flat, so centroiding fails."""
    rng = rng or np.random.default_rng(0)
    y, x = np.mgrid[:SIZE, :SIZE]
    frames = np.zeros((nframes, SIZE, SIZE))
    for i in range(nframes):
        if i in bad:
            frames[i] = 500.0  # a flat frame has no sources at all
            continue
        frame = np.full((SIZE, SIZE), 100.0)
        for cx in SPOT_X:
            jitter = rng.normal(scale=0.3, size=2)
            frame += 3000.0 * np.exp(
                -((x - cx - jitter[0]) ** 2 + (y - SPOT_Y - jitter[1]) ** 2) / (2 * 2.0**2)
            )
        frames[i] = frame + rng.normal(scale=5.0, size=(SIZE, SIZE))
    return np.clip(frames, 0, 65535).astype(np.uint16)


def test_frame_index_matches_the_kept_series_on_a_clean_cube(tmp_path):
    path = write_ser(tmp_path / "clean.ser", frames=dimm_frames(20))

    results = analyze_dimm_cube(path)

    assert results["N_bad"] == 0
    assert len(results["frame_index"]) == len(results["aperture_fluxes"])
    np.testing.assert_array_equal(results["frame_index"], np.arange(20))


def test_frame_index_omits_exactly_the_frames_that_failed(tmp_path):
    bad = (4, 5, 11)
    path = write_ser(tmp_path / "gappy.ser", frames=dimm_frames(20, bad=bad))

    results = analyze_dimm_cube(path)

    assert results["N_bad"] == len(bad)
    assert len(results["frame_index"]) == len(results["aperture_fluxes"])
    np.testing.assert_array_equal(
        results["frame_index"], [i for i in range(20) if i not in bad]
    )


def test_frame_index_is_integer_typed(tmp_path):
    """It indexes into the cube, so it has to be usable as an index without casting."""
    path = write_ser(tmp_path / "clean.ser", frames=dimm_frames(20))

    results = analyze_dimm_cube(path)

    assert np.issubdtype(results["frame_index"].dtype, np.integer)
    assert results["frame_times"][results["frame_index"]].isot[0].startswith("2024-05-05")
```

- [ ] **Step 4: Run the tests to verify they fail**

Run: `pytest src/timdimm_tng/tests/test_analyze_cube.py -v`
Expected: all 3 FAIL with `KeyError: 'frame_index'`.

If instead they fail earlier — inside `find_apertures` or with "Hit 100 bad frame limit" — the
synthetic cube is not being detected as two spots. Raise the spot amplitude and re-check; do not
proceed until the clean-cube test fails only on the missing key.

- [ ] **Step 5: Record the surviving frame indices**

In `src/timdimm_tng/analyze_cube.py`, in `analyze_dimm_cube`, add `kept = []` beside the existing
`baselines = []` / `positions = []` / `fluxes = []` / `nbad = 0` initialisation (around line 327).

Inside the frame loop, in the `if dimm_meas is not None:` branch, after `fluxes.append(ap_fluxes)`,
add:

```python
            kept.append(i)
```

After the loop, beside the existing `baselines = np.array(...)` conversions, add:

```python
    kept = np.array(kept, dtype=int)
```

Add one entry to the returned dict, next to `"N_bad": nbad,`:

```python
        "frame_index": kept,
```

- [ ] **Step 6: Run the tests to verify they pass**

Run: `pytest src/timdimm_tng/tests/test_analyze_cube.py src/timdimm_tng/tests/test_ser.py -v`
Expected: all 8 PASS, no warnings from the new tests.

- [ ] **Step 7: Commit**

```bash
git add src/timdimm_tng/analyze_cube.py src/timdimm_tng/tests/test_analyze_cube.py \
        src/timdimm_tng/tests/ser_helpers.py src/timdimm_tng/tests/test_ser.py
git commit -m "report which cube frames survived centroiding"
```

---

### Task 2: Aperture assignment and throughput

The prism aperture is always the fainter one, but its array index depends on the camera orientation,
which has changed three times. Assign faint and bright **once per cube** from the median flux;
choosing the fainter aperture frame by frame takes the minimum of two noisy numbers every time and
biases the ratio low even for two identical apertures.

Throughput is the **ratio of the mean fluxes**, not the mean of the per-frame ratios. Noise in the
denominator inflates the mean of a ratio badly at 1 ms cadence.

**Files:**
- Create: `src/timdimm_tng/scintillation.py`
- Test: `src/timdimm_tng/tests/test_scintillation.py`

**Interfaces:**
- Consumes: nothing.
- Produces: `assign_apertures(fluxes) -> (bright, faint)` both `np.ndarray` of length `n_kept`;
  `throughput(bright, faint) -> float`.

- [ ] **Step 1: Write the failing tests**

Create `src/timdimm_tng/tests/test_scintillation.py`:

```python
"""
Tests for the scintillation and time-constant estimators.

Everything here runs on synthetic series with analytically known answers. The two estimator traps
these guard against are both recorded in docs/scintillation_logging_notes.md: taking the mean of
per-frame ratios instead of the ratio of means, and correlating by position in the compacted array
instead of by cube frame index.
"""

import numpy as np
import pytest

from timdimm_tng.scintillation import assign_apertures, throughput


def two_identical_apertures(scatter, n=200000, seed=0):
    """
    Two apertures with the same true flux, differing only by independent noise.

    The noise is lognormal, not Gaussian. Scintillation is multiplicative and a measured flux is
    never negative, but more to the point a Gaussian denominator can approach zero, which makes the
    mean of the per-frame ratios a heavy-tailed statistic with no stable value -- it would move with
    the seed and the sample size, and the test would be measuring nothing.

    With lognormal noise of fractional scatter s, the naive estimator has the exact expectation
    ``1 + s**2``, which is what makes the bias assertable rather than merely observable.
    """
    rng = np.random.default_rng(seed)
    true = 1000.0
    sigma = np.sqrt(np.log(1.0 + scatter**2))
    a = true * rng.lognormal(mean=-0.5 * sigma**2, sigma=sigma, size=n)
    b = true * rng.lognormal(mean=-0.5 * sigma**2, sigma=sigma, size=n)
    return np.column_stack([a, b])


@pytest.mark.parametrize("scatter", [0.1, 0.3, 0.5])
def test_throughput_of_two_identical_apertures_is_one(scatter):
    bright, faint = assign_apertures(two_identical_apertures(scatter))

    assert throughput(bright, faint) == pytest.approx(1.0, abs=0.02)


@pytest.mark.parametrize("scatter", [0.1, 0.3, 0.5])
def test_the_naive_estimator_really_is_biased(scatter):
    """
    Not a test of our code -- a test that the bias we are avoiding is real, and that it grows as
    the square of the frame-to-frame scatter. Two *identical* apertures, so the correct answer is
    1.0 and every part of the excess is estimator bias.
    """
    fluxes = two_identical_apertures(scatter)
    mean_of_ratios = np.mean(fluxes[:, 1] / fluxes[:, 0])

    assert mean_of_ratios == pytest.approx(1.0 + scatter**2, rel=0.02)
    assert mean_of_ratios > 1.0 + 0.5 * scatter**2


def test_the_faint_aperture_is_found_when_it_is_at_index_zero():
    fluxes = np.column_stack([np.full(500, 300.0), np.full(500, 1000.0)])

    bright, faint = assign_apertures(fluxes)

    assert bright[0] == 1000.0
    assert faint[0] == 300.0


def test_the_faint_aperture_is_found_when_it_is_at_index_one():
    """find_apertures sorts by x centroid, so the prism's index follows the camera orientation."""
    fluxes = np.column_stack([np.full(500, 1000.0), np.full(500, 300.0)])

    bright, faint = assign_apertures(fluxes)

    assert bright[0] == 1000.0
    assert faint[0] == 300.0


def test_assignment_survives_frames_that_individually_invert_the_ordering():
    rng = np.random.default_rng(1)
    n = 4000
    a = 1000.0 + 400.0 * rng.normal(size=n)   # bright on average, but noisy enough to cross over
    b = 700.0 + 400.0 * rng.normal(size=n)
    fluxes = np.column_stack([a, b])
    assert np.mean(b > a) > 0.2, "the test data must actually contain inversions"

    bright, faint = assign_apertures(fluxes)

    assert np.median(bright) > np.median(faint)
    assert throughput(bright, faint) == pytest.approx(0.7, abs=0.03)


def test_throughput_is_nan_when_a_mean_flux_is_not_positive():
    bright = np.full(500, 1000.0)
    faint = np.zeros(500)

    assert np.isnan(throughput(bright, faint))
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `pytest src/timdimm_tng/tests/test_scintillation.py -v`
Expected: collection error, `ModuleNotFoundError: No module named 'timdimm_tng.scintillation'`.

- [ ] **Step 3: Write the module**

Create `src/timdimm_tng/scintillation.py`:

```python
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
    give 2.39 by the naive estimator against the correct 1.00. The ratio of means is also the
    physically meaningful quantity: total light through the prism over total through the clear
    aperture.
    """
    bright = np.asarray(bright, dtype=float)
    faint = np.asarray(faint, dtype=float)
    if bright.sum() <= 0 or faint.sum() <= 0:
        return float("nan")
    return float(faint.sum() / bright.sum())
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `pytest src/timdimm_tng/tests/test_scintillation.py -v`
Expected: 10 PASS.

- [ ] **Step 5: Commit**

```bash
git add src/timdimm_tng/scintillation.py src/timdimm_tng/tests/test_scintillation.py
git commit -m "measure prism throughput as the ratio of mean fluxes"
```

---

### Task 3: The scintillation index

Built on the **ratio** of the two apertures rather than on one aperture's flux, which makes it
differential: transparency changes and cloud move both apertures together and cancel, leaving what
differs between two apertures a few centimetres apart.

No noise subtraction. The measured values of 0.323 and 1.259 on real cubes are too large to be
atmospheric scintillation alone — an index above 1 means the ratio's standard deviation exceeds its
mean — so shot noise and centroiding scatter are inside this number. The column is named
`scint_index_raw` to say so, and the mean fluxes are logged beside it so a photon-noise floor can be
subtracted downstream by whoever needs it.

**Files:**
- Modify: `src/timdimm_tng/scintillation.py`
- Test: `src/timdimm_tng/tests/test_scintillation.py`

**Interfaces:**
- Consumes: nothing from Task 2 beyond the module existing.
- Produces: `flux_ratio(bright, faint) -> np.ndarray`; `scint_index(ratio) -> float`.

- [ ] **Step 1: Write the failing tests**

Append to `src/timdimm_tng/tests/test_scintillation.py`, and add `flux_ratio, scint_index` to the
existing import from `timdimm_tng.scintillation`:

```python
def test_a_constant_ratio_has_no_scintillation():
    assert scint_index(np.full(1000, 0.75)) == pytest.approx(0.0, abs=1e-12)


def test_the_index_recovers_a_known_normalised_variance():
    """A ratio with 20% fractional scatter has a normalised variance of 0.04."""
    rng = np.random.default_rng(3)
    ratio = 0.75 * (1.0 + 0.2 * rng.normal(size=200000))

    assert scint_index(ratio) == pytest.approx(0.04, rel=0.02)


def test_the_index_is_scale_free():
    """Normalising by the squared mean makes it independent of the absolute flux level."""
    rng = np.random.default_rng(4)
    ratio = 0.75 * (1.0 + 0.2 * rng.normal(size=50000))

    assert scint_index(ratio) == pytest.approx(scint_index(1000.0 * ratio), rel=1e-9)


def test_flux_ratio_is_faint_over_bright_per_frame():
    bright = np.array([100.0, 200.0, 400.0])
    faint = np.array([50.0, 50.0, 100.0])

    np.testing.assert_allclose(flux_ratio(bright, faint), [0.5, 0.25, 0.25])


def test_the_index_is_nan_when_the_mean_ratio_is_not_positive():
    assert np.isnan(scint_index(np.zeros(500)))
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `pytest src/timdimm_tng/tests/test_scintillation.py -v`
Expected: collection error, `ImportError: cannot import name 'flux_ratio'`.

- [ ] **Step 3: Implement**

Append to `src/timdimm_tng/scintillation.py`:

```python
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
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `pytest src/timdimm_tng/tests/test_scintillation.py -v`
Expected: 15 PASS.

- [ ] **Step 5: Commit**

```bash
git add src/timdimm_tng/scintillation.py src/timdimm_tng/tests/test_scintillation.py
git commit -m "add the uncorrected scintillation index of the flux ratio"
```

---

### Task 4: Autocorrelation by frame lag

**This is the task that makes the time constants trustworthy.** Frames where centroiding failed are
dropped from the returned series, so consecutive entries of the compacted array are not necessarily
consecutive in time. Correlating by array position instead of by cube index is exactly the error
that produced a nonsense answer on `indi_2023-12-08@20-48-35`, a cube that kept 435 of 4420 frames
and contradicted a good cube at less than half the frame rate.

The fix is to scatter the samples back into a full-length array with NaN in the gaps, then correlate
only the pairs that are genuinely `lag` frames apart.

**Files:**
- Modify: `src/timdimm_tng/scintillation.py`
- Test: `src/timdimm_tng/tests/test_scintillation.py`

**Interfaces:**
- Consumes: nothing.
- Produces: `lag_autocorr(x, index, lag) -> (rho: float, npairs: int)`. `MIN_PAIRS = 30`.

- [ ] **Step 1: Write the failing tests**

Append to `src/timdimm_tng/tests/test_scintillation.py`, and add `lag_autocorr` to the import:

```python
def ar1(n, rho, rng):
    """A first-order autoregressive series: corr at lag k is rho**k, unit variance."""
    x = np.zeros(n)
    noise = rng.normal(size=n)
    scale = np.sqrt(1.0 - rho**2)
    for i in range(1, n):
        x[i] = rho * x[i - 1] + scale * noise[i]
    return x


def test_white_noise_is_uncorrelated_at_lag_one():
    rng = np.random.default_rng(5)
    x = rng.normal(size=20000)

    rho, npairs = lag_autocorr(x, np.arange(20000), 1)

    assert abs(rho) < 0.03
    assert npairs == 19999


def test_a_slow_series_is_strongly_correlated_at_lag_one():
    rng = np.random.default_rng(6)
    x = ar1(20000, 0.95, rng)

    rho, _ = lag_autocorr(x, np.arange(20000), 1)

    assert rho == pytest.approx(0.95, abs=0.02)


def test_correlation_decays_as_rho_to_the_lag():
    rng = np.random.default_rng(7)
    x = ar1(50000, 0.8, rng)
    index = np.arange(50000)

    for lag in (1, 2, 3, 4):
        rho, _ = lag_autocorr(x, index, lag)
        assert rho == pytest.approx(0.8**lag, abs=0.02)


def test_gaps_are_left_as_gaps_rather_than_closed_up():
    """
    The whole point. Delete 20% of the frames: correlating by array position would treat samples
    two or three frames apart as adjacent and drag the lag-1 correlation down.
    """
    rng = np.random.default_rng(8)
    full = ar1(50000, 0.8, rng)
    keep = rng.random(50000) > 0.2
    index = np.arange(50000)[keep]
    x = full[keep]

    rho, npairs = lag_autocorr(x, index, 1)
    naive = np.corrcoef(x[:-1], x[1:])[0, 1]

    assert rho == pytest.approx(0.8, abs=0.02)
    assert naive < 0.75, "the naive estimator should be visibly biased by the gaps"
    assert npairs == pytest.approx(0.64 * 50000, rel=0.05)


def test_pair_counts_match_what_the_index_implies():
    x = np.array([1.0, 2.0, 3.0, 4.0])
    index = np.array([0, 1, 5, 6])

    assert lag_autocorr(x, index, 1)[1] == 2   # (0,1) and (5,6)
    assert lag_autocorr(x, index, 4)[1] == 2   # (1,5) and (2,6)
    assert lag_autocorr(x, index, 3)[1] == 0   # nothing is exactly 3 apart


def test_too_few_pairs_gives_nan_but_still_reports_the_count():
    x = np.array([1.0, 2.0, 3.0, 4.0])
    index = np.array([0, 1, 5, 6])

    rho, npairs = lag_autocorr(x, index, 1)

    assert np.isnan(rho)
    assert npairs == 2
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `pytest src/timdimm_tng/tests/test_scintillation.py -v`
Expected: collection error, `ImportError: cannot import name 'lag_autocorr'`.

- [ ] **Step 3: Implement**

Append to `src/timdimm_tng/scintillation.py`:

```python
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
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `pytest src/timdimm_tng/tests/test_scintillation.py -v`
Expected: 21 PASS.

- [ ] **Step 5: Commit**

```bash
git add src/timdimm_tng/scintillation.py src/timdimm_tng/tests/test_scintillation.py
git commit -m "correlate by frame lag so dropouts stay gaps"
```

---

### Task 5: Fitting a time constant, and the sampling interval

At 299 Hz the image-motion time constant is 4–6 ms, only 1.2–1.7 samples long. The 1/e crossing
falls between two samples, so interpolating it is interpolating noise. Fit a straight line to
`log(rho)` against lag×dt over lags 1–4 instead and take `tau = -1/slope`.

Lags are consumed in order and the loop **stops** at the first one that is unusable — once `rho`
reaches the noise floor, higher lags carry no information and including them flattens the fit.

**Files:**
- Modify: `src/timdimm_tng/scintillation.py`
- Test: `src/timdimm_tng/tests/test_scintillation.py`

**Interfaces:**
- Consumes: `lag_autocorr`, `MIN_PAIRS` from Task 4.
- Produces: `fit_tau(x, index, dt, lags=FIT_LAGS) -> float` in **seconds**;
  `median_dt(frame_times) -> float` in **seconds**; `FIT_LAGS = (1, 2, 3, 4)`.

- [ ] **Step 1: Write the failing tests**

Append to `src/timdimm_tng/tests/test_scintillation.py`, and add `fit_tau, median_dt` to the import.
Also add `from astropy.time import Time` to the top of the file.

```python
DT = 3.342e-3  # the 299 Hz cadence, in seconds


def test_fit_recovers_a_known_time_constant():
    """rho at lag 1 is exp(-dt/tau), so a tau of 5 ms at 299 Hz gives rho = 0.513."""
    tau = 5.0e-3
    rng = np.random.default_rng(9)
    x = ar1(40000, np.exp(-DT / tau), rng)

    assert fit_tau(x, np.arange(40000), DT) == pytest.approx(tau, rel=0.05)


def test_fit_recovers_the_same_tau_from_a_punctured_series():
    """
    The test that proves the gaps are handled. Same underlying process, 20% of frames deleted --
    the answer must not move.
    """
    tau = 5.0e-3
    rng = np.random.default_rng(10)
    full = ar1(40000, np.exp(-DT / tau), rng)
    keep = rng.random(40000) > 0.2
    index = np.arange(40000)[keep]

    contiguous = fit_tau(full, np.arange(40000), DT)
    punctured = fit_tau(full[keep], index, DT)

    assert punctured == pytest.approx(tau, rel=0.06)
    assert punctured == pytest.approx(contiguous, rel=0.06)


def test_fit_is_nan_for_a_series_with_no_decay_to_fit():
    rng = np.random.default_rng(11)
    x = rng.normal(size=40000)

    assert np.isnan(fit_tau(x, np.arange(40000), DT))


def test_fit_is_nan_when_too_few_frames_survived():
    rng = np.random.default_rng(12)
    x = ar1(20, 0.8, rng)

    assert np.isnan(fit_tau(x, np.arange(20), DT))


def test_a_longer_time_constant_fits_larger():
    rng = np.random.default_rng(13)
    slow = ar1(40000, np.exp(-DT / 20.0e-3), rng)
    fast = ar1(40000, np.exp(-DT / 5.0e-3), rng)
    index = np.arange(40000)

    assert fit_tau(slow, index, DT) > fit_tau(fast, index, DT)


def test_median_dt_uses_the_measured_intervals_not_the_nominal_rate():
    """Cadence jitter is small at 299 Hz but the archive spans a factor of 30 in frame rate."""
    rng = np.random.default_rng(14)
    ticks = np.cumsum(rng.normal(loc=DT, scale=0.0002, size=5000))
    times = Time("2024-05-05T01:57:00", scale="utc") + ticks * u.s

    assert median_dt(times) == pytest.approx(DT, rel=0.01)


def test_median_dt_is_nan_when_the_timestamp_trailer_is_missing():
    """A truncated cube loses its timestamps entirely -- ser.py returns an empty Time array."""
    assert np.isnan(median_dt(Time([], format="isot", scale="utc")))
```

Add `import astropy.units as u` to the test file's imports.

- [ ] **Step 2: Run the tests to verify they fail**

Run: `pytest src/timdimm_tng/tests/test_scintillation.py -v`
Expected: collection error, `ImportError: cannot import name 'fit_tau'`.

- [ ] **Step 3: Implement**

Append to `src/timdimm_tng/scintillation.py`, and add `import astropy.units as u` to its imports:

```python
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
```

Note `u` is imported for consistency with the rest of the package but `median_dt` works in plain
seconds via `Time.unix`; if flake8 flags the import as unused, remove it.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `pytest src/timdimm_tng/tests/test_scintillation.py -v`
Expected: 28 PASS.

- [ ] **Step 5: Commit**

```bash
git add src/timdimm_tng/scintillation.py src/timdimm_tng/tests/test_scintillation.py
git commit -m "fit time constants over the first four lags"
```

---

### Task 6: Assemble the row, with censoring

At 299 Hz the flux ratio is decorrelated after a single frame — measured `rho(1)` is 0.10 and 0.01
on the two clean cubes. The scintillation time constant is therefore shorter than the sampling can
resolve, and is reported as a **censored upper limit**: `tau_scint_ms` is the sample interval and
`tau_scint_censored` is 1. `acf1_ratio` is logged unconditionally as the evidence. If the frame rate
ever rises to where `rho(1)` stays above the threshold, the same code starts returning a fitted
number and clears the flag with no code change.

The image-motion constant is computed on `baseline_lengths` — the **differential** motion, the same
series the seeing comes from — not on `aperture_positions`, which is common-mode telescope shake and
has a different time constant.

**Files:**
- Modify: `src/timdimm_tng/scintillation.py`
- Test: `src/timdimm_tng/tests/test_scintillation.py`

**Interfaces:**
- Consumes: everything from Tasks 2–5.
- Produces: `scintillation_stats(results) -> dict` with exactly these keys: `throughput`,
  `scint_index_raw`, `tau_motion_ms`, `tau_scint_ms`, `tau_scint_censored`, `acf1_ratio`,
  `cadence_hz`, `n_frames`, `n_kept`, `mean_flux_bright`, `mean_flux_faint`.
  `ACF1_CENSOR_THRESHOLD = 0.2`.

- [ ] **Step 1: Write the failing tests**

Append to `src/timdimm_tng/tests/test_scintillation.py`, adding `scintillation_stats, MIN_KEPT` to
the import:

```python
def fake_results(n=4000, nbad=0, tau_motion=5.0e-3, ratio_rho=0.0, seed=20):
    """A stand-in for the analyze_dimm_cube results dict, with known time constants."""
    rng = np.random.default_rng(seed)
    total = n + nbad
    index = rng.choice(total, size=n, replace=False)
    index.sort()

    baseline = 50.0 + 0.5 * ar1(total, np.exp(-DT / tau_motion), rng)[index]
    ratio_series = 0.75 * (1.0 + 0.2 * ar1(total, ratio_rho, rng)[index])
    bright = 1000.0 * (1.0 + 0.05 * rng.normal(size=n))
    fluxes = [np.array([b, b * r]) for b, r in zip(bright, ratio_series)]

    times = Time("2024-05-05T01:57:00", scale="utc") + DT * np.arange(total) * u.s
    return {
        "baseline_lengths": np.array([baseline]),
        "aperture_fluxes": fluxes,
        "frame_times": times,
        "frame_index": index,
        "N_bad": nbad,
    }


def test_stats_has_exactly_the_expected_keys():
    stats = scintillation_stats(fake_results())

    assert set(stats) == {
        "throughput", "scint_index_raw", "tau_motion_ms", "tau_scint_ms", "tau_scint_censored",
        "acf1_ratio", "cadence_hz", "n_frames", "n_kept", "mean_flux_bright", "mean_flux_faint",
    }


def test_stats_recovers_throughput_and_cadence():
    stats = scintillation_stats(fake_results())

    assert stats["throughput"] == pytest.approx(0.75, abs=0.02)
    assert stats["cadence_hz"] == pytest.approx(1.0 / DT, rel=0.01)
    assert stats["n_kept"] == 4000
    assert stats["n_frames"] == 4000


def test_stats_counts_bad_frames_into_n_frames():
    stats = scintillation_stats(fake_results(n=4000, nbad=250))

    assert stats["n_kept"] == 4000
    assert stats["n_frames"] == 4250


def test_stats_recovers_the_image_motion_time_constant():
    stats = scintillation_stats(fake_results(tau_motion=5.0e-3))

    assert stats["tau_motion_ms"] == pytest.approx(5.0, rel=0.15)


def test_stats_recovers_image_motion_through_dropouts():
    """A cube with 20% of frames lost must give the same answer as a clean one."""
    clean = scintillation_stats(fake_results(n=4000, nbad=0, seed=21))
    gappy = scintillation_stats(fake_results(n=4000, nbad=1000, seed=21))

    assert gappy["tau_motion_ms"] == pytest.approx(clean["tau_motion_ms"], rel=0.2)


def test_an_unresolved_scintillation_time_constant_is_censored():
    """What a real 299 Hz cube does: the flux ratio decorrelates in one frame."""
    stats = scintillation_stats(fake_results(ratio_rho=0.0))

    assert stats["tau_scint_censored"] == 1
    assert stats["tau_scint_ms"] == pytest.approx(DT * 1000.0, rel=0.01)
    assert abs(stats["acf1_ratio"]) < ACF1_CENSOR_THRESHOLD


def test_a_resolved_scintillation_time_constant_is_fitted_and_not_censored():
    """The behaviour the code must already have for the day the frame rate goes up."""
    stats = scintillation_stats(fake_results(ratio_rho=np.exp(-DT / 12.0e-3)))

    assert stats["tau_scint_censored"] == 0
    assert stats["acf1_ratio"] > ACF1_CENSOR_THRESHOLD
    assert stats["tau_scint_ms"] == pytest.approx(12.0, rel=0.2)


def test_too_few_kept_frames_gives_nan_stats_but_still_reports_the_counts():
    stats = scintillation_stats(fake_results(n=MIN_KEPT - 1, nbad=4000))

    assert stats["n_kept"] == MIN_KEPT - 1
    assert stats["n_frames"] == MIN_KEPT - 1 + 4000
    assert np.isfinite(stats["cadence_hz"]), "cadence comes from the cube, not the estimators"
    for key in ("throughput", "scint_index_raw", "tau_motion_ms", "tau_scint_ms", "acf1_ratio"):
        assert np.isnan(stats[key]), key


def test_a_zero_flux_aperture_gives_nan_throughput_without_raising():
    results = fake_results()
    results["aperture_fluxes"] = [np.array([f[0], 0.0]) for f in results["aperture_fluxes"]]

    stats = scintillation_stats(results)

    assert np.isnan(stats["throughput"])
    assert np.isnan(stats["scint_index_raw"])
    assert stats["n_kept"] == 4000
```

Add `ACF1_CENSOR_THRESHOLD` to the import as well.

- [ ] **Step 2: Run the tests to verify they fail**

Run: `pytest src/timdimm_tng/tests/test_scintillation.py -v`
Expected: collection error, `ImportError: cannot import name 'scintillation_stats'`.

- [ ] **Step 3: Implement**

Append to `src/timdimm_tng/scintillation.py`:

```python
#: A lag-1 autocorrelation below this means the series decorrelates within one frame, so its time
#: constant is an upper limit rather than a measurement. Real 299 Hz cubes give 0.10 and 0.01.
ACF1_CENSOR_THRESHOLD = 0.2

_NAN_KEYS = (
    "throughput", "scint_index_raw", "tau_motion_ms", "tau_scint_ms", "acf1_ratio",
    "mean_flux_bright", "mean_flux_faint",
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
        "tau_scint_censored": 0,
    }
    stats.update({key: float("nan") for key in _NAN_KEYS})

    if n_kept < MIN_KEPT or not np.isfinite(dt):
        return stats

    bright, faint = assign_apertures(fluxes)
    stats["mean_flux_bright"] = float(bright.mean())
    stats["mean_flux_faint"] = float(faint.mean())
    stats["throughput"] = throughput(bright, faint)

    ratio = flux_ratio(bright, faint)
    stats["scint_index_raw"] = scint_index(ratio)

    # the differential motion -- the same series the seeing is computed from -- not the
    # common-mode aperture_positions, which is telescope shake and has its own time constant
    baseline = np.asarray(results["baseline_lengths"], dtype=float)[0]
    tau_motion = fit_tau(baseline, index, dt)
    stats["tau_motion_ms"] = tau_motion * 1000.0 if np.isfinite(tau_motion) else float("nan")

    acf1, npairs = lag_autocorr(ratio, index, 1)
    stats["acf1_ratio"] = acf1 if npairs >= MIN_PAIRS else float("nan")

    if np.isfinite(acf1) and acf1 >= ACF1_CENSOR_THRESHOLD:
        tau_scint = fit_tau(ratio, index, dt)
        stats["tau_scint_ms"] = tau_scint * 1000.0 if np.isfinite(tau_scint) else float("nan")
    elif np.isfinite(acf1):
        # decorrelated within one frame: the time constant is below the sampling interval
        stats["tau_scint_ms"] = dt * 1000.0
        stats["tau_scint_censored"] = 1

    return stats
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `pytest src/timdimm_tng/tests/test_scintillation.py -v`
Expected: 37 PASS.

- [ ] **Step 5: Commit**

```bash
git add src/timdimm_tng/scintillation.py src/timdimm_tng/tests/test_scintillation.py
git commit -m "assemble the scintillation row and censor the unresolved time constant"
```

---

### Task 7: Format the row and write it from postcapture

The row is written **outside and before** the `seeing < 10.0 and N_bad < 50` quality block. A dewed
prism is exactly what this feature exists to catch and exactly when the seeing analysis is likeliest
to fail its gate; gating the scintillation row on the seeing row would silence the instrument when it
matters most.

`time` is byte-identical to the value written to `seeing.csv`, which is what lets the two files join
without fuzzy time matching. That means `Time.now().isot` must be computed **once** and reused, not
called twice.

This task also fixes an unrelated latent bug it would otherwise inherit: when `analyze_dimm_cube`
raises, `postcapture.py` logs it, moves the cube aside, then falls through to
`if np.isfinite(seeing_data['seeing'].value)` with `seeing_data` never bound, dying with `NameError`.

**Files:**
- Modify: `src/timdimm_tng/scintillation.py`
- Modify: `scripts/ekos_timdimm/postcapture.py:83-104`
- Test: `src/timdimm_tng/tests/test_scintillation.py`

**Interfaces:**
- Consumes: `scintillation_stats` from Task 6.
- Produces: `CSV_HEADER: str` and `format_row(stats, time, target, exptime) -> str`, both ending in
  a newline.

- [ ] **Step 1: Write the failing tests**

Append to `src/timdimm_tng/tests/test_scintillation.py`, adding `CSV_HEADER, format_row` to the
import:

```python
def test_the_row_has_one_field_per_header_column():
    stats = scintillation_stats(fake_results())
    row = format_row(stats, "2024-05-05T01:57:00.000", "Achernar", 0.001)

    assert row.endswith("\n")
    assert CSV_HEADER.endswith("\n")
    assert len(row.strip().split(",")) == len(CSV_HEADER.strip().split(","))


def test_the_row_starts_with_the_join_key():
    stats = scintillation_stats(fake_results())
    row = format_row(stats, "2024-05-05T01:57:00.000", "Achernar", 0.001)
    fields = row.strip().split(",")

    assert CSV_HEADER.strip().split(",")[:2] == ["time", "target"]
    assert fields[0] == "2024-05-05T01:57:00.000"
    assert fields[1] == "Achernar"


def test_the_row_round_trips_through_csv():
    import csv
    import io

    stats = scintillation_stats(fake_results())
    row = format_row(stats, "2024-05-05T01:57:00.000", "Achernar", 0.001)

    parsed = list(csv.DictReader(io.StringIO(CSV_HEADER + row)))[0]

    assert float(parsed["throughput"]) == pytest.approx(stats["throughput"], abs=1e-4)
    assert int(parsed["n_kept"]) == stats["n_kept"]
    assert int(parsed["tau_scint_censored"]) == stats["tau_scint_censored"]


def test_nan_values_are_written_as_nan_and_parse_back_as_nan():
    stats = scintillation_stats(fake_results(n=MIN_KEPT - 1, nbad=100))
    row = format_row(stats, "2024-05-05T01:57:00.000", "Achernar", 0.001)

    fields = dict(zip(CSV_HEADER.strip().split(","), row.strip().split(",")))

    assert fields["throughput"] == "nan"
    assert np.isnan(float(fields["throughput"]))
    assert int(fields["n_kept"]) == MIN_KEPT - 1
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `pytest src/timdimm_tng/tests/test_scintillation.py -v`
Expected: collection error, `ImportError: cannot import name 'CSV_HEADER'`.

- [ ] **Step 3: Implement the formatting**

Append to `src/timdimm_tng/scintillation.py`:

```python
#: Column order of ~/scintillation.csv. Kept in one place so the header and the rows cannot drift.
CSV_COLUMNS = (
    "time", "target", "throughput", "scint_index_raw", "tau_motion_ms", "tau_scint_ms",
    "tau_scint_censored", "acf1_ratio", "cadence_hz", "n_frames", "n_kept",
    "mean_flux_bright", "mean_flux_faint", "exptime",
)

CSV_HEADER = ",".join(CSV_COLUMNS) + "\n"

#: Fixed precision keeps the file diffable and readable. Anything absent here is written with repr.
_PRECISION = {
    "throughput": 4, "scint_index_raw": 4, "acf1_ratio": 3,
    "tau_motion_ms": 2, "tau_scint_ms": 2, "cadence_hz": 2,
    "mean_flux_bright": 1, "mean_flux_faint": 1,
}


def format_row(stats, time, target, exptime):
    """
    Format one scintillation.csv row, newline included.

    ``time`` must be the *same string* written to the matching seeing.csv row -- that identity is
    what lets the two files be joined without fuzzy time matching.
    """
    values = dict(stats, time=time, target=target, exptime=exptime)
    fields = []
    for column in CSV_COLUMNS:
        value = values[column]
        digits = _PRECISION.get(column)
        fields.append(f"{value:.{digits}f}" if digits is not None else str(value))
    return ",".join(fields) + "\n"
```

`float("nan")` formats as `nan` under `:.4f`, which `float()` reads back as NaN and pandas reads as
`NaN` by default. That is the intended representation.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `pytest src/timdimm_tng/tests/test_scintillation.py -v`
Expected: 41 PASS.

- [ ] **Step 5: Wire it into postcapture**

In `scripts/ekos_timdimm/postcapture.py`, add to the imports beside the existing
`from timdimm_tng.analyze_cube import ...`:

```python
from timdimm_tng.scintillation import CSV_HEADER, format_row, scintillation_stats
```

Replace lines 83-104 — from `try:` down to the end of the `seeing.csv` write — with:

```python
try:
    seeing_data = analyze_dimm_cube("/home/timdimm/seeing.ser", airmass=pointing_status['airmass'])
except Exception as e:
    log.error(f"Seeing analysis failed: {e}")
    os.system("mv ~/seeing.ser ~/last_bad_seeing.ser")
    sys.exit(0)

# one timestamp, shared by both files, so scintillation.csv joins seeing.csv on it exactly
now = Time.now().isot
target = pointing_status['target']

# written outside the seeing quality gate below: a dewing prism is what this measures, and it is
# also what makes the seeing analysis fail, so gating on the seeing row would lose exactly the
# measurements we want
try:
    scint = scintillation_stats(seeing_data)
    scint_file = Path.home() / "scintillation.csv"
    if not scint_file.exists():
        with open(scint_file, 'w') as fp:
            fp.write(CSV_HEADER)
    with open(scint_file, 'a') as fp:
        fp.write(format_row(scint, now, target, exptime))
    log.info(
        f"Throughput: {scint['throughput']:.3f}; scint index: {scint['scint_index_raw']:.3f}; "
        f"tau_motion: {scint['tau_motion_ms']:.2f} ms; kept {scint['n_kept']}/{scint['n_frames']}"
    )
except Exception as e:
    log.error(f"Scintillation analysis failed: {e}")

if np.isfinite(seeing_data['seeing'].value) and seeing_data['seeing'].value < 10.0:
    log.info(f"Seeing: {seeing_data['seeing']:.2f}; N bad: {seeing_data['N_bad']}")
    if seeing_data['N_bad'] < 50:
        csv_file = Path.home() / "seeing.csv"
        if not csv_file.exists():
            with open(csv_file, 'w') as fp:
                fp.write("time,target,seeing,airmass,azimuth,exptime\n")

        with open(csv_file, 'a') as fp:
            z = pointing_status['airmass']
            azimuth = pointing_status['az']
            seeing = seeing_data['seeing'].value
            fp.write(
                f"{now},{target},{seeing:.3f},{z:.3f},{azimuth:.1f},{exptime}\n"
            )
```

Three things to check while editing:
- The `seeing.csv` line now uses `now` and `target` instead of `Time.now().isot` and
  `pointing_status['target']`. **The column format is unchanged** — `seeing.csv` is frozen. Only the
  source of two already-present values moved.
- The `target = ...` assignment that used to be inside the `with open(csv_file, 'a')` block is gone;
  it is set once above.
- The scintillation write is wrapped in its own `try` so a bug in the new code can never cost a
  seeing measurement.

- [ ] **Step 6: Verify the whole suite and the lint**

Run: `pytest src/timdimm_tng/tests -q`
Expected: all pass, including the 118 that existed before this branch.

Run: `flake8 src/timdimm_tng --count --max-line-length=132`
Expected: `0`.

`postcapture.py` talks to a camera over INDI and has no automated test. Verify the edit compiles and
that the seeing.csv line is untouched in format:

Run: `python -m py_compile scripts/ekos_timdimm/postcapture.py`
Expected: no output.

Run: `git diff scripts/ekos_timdimm/postcapture.py | grep -E '^[-+].*seeing.csv|^[-+].*time,target'`
Expected: the header string `time,target,seeing,airmass,azimuth,exptime` appears on a `-` line and an
identical `+` line, or not at all — never changed.

- [ ] **Step 7: Commit**

```bash
git add src/timdimm_tng/scintillation.py src/timdimm_tng/tests/test_scintillation.py \
        scripts/ekos_timdimm/postcapture.py
git commit -m "log scintillation stats to ~/scintillation.csv from postcapture"
```

---

## Done when

- `pytest src/timdimm_tng/tests -q` passes, with 41 new tests in `test_scintillation.py` and 3 in
  `test_analyze_cube.py`.
- `flake8 src/timdimm_tng --count --max-line-length=132` reports 0.
- `~/seeing.csv`'s header and column formats are byte-identical to before.
- `scripts/ekos_hdimm/postcapture.py` is unmodified.
- The branch is **not pushed**.

## Deliberately not in this plan

- Batch reanalysis of the archived cubes to backfill `scintillation.csv`.
- Any change to frame rate, ROI or exposure time.
- HDIMM.
- Shot-noise correction of the scintillation index.
- Joining `scintillation.csv` to the Adafruit humidity log.
