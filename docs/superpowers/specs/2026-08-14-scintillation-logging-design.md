# Logging scintillation and time constants from `analyze_cube`

Four values, derived from the SER cube that every seeing measurement already records, written to a
new `~/scintillation.csv`. The motivation, the prior measurements and the estimator pitfalls are in
`docs/scintillation_logging_notes.md`; this document specifies what gets built.

## Purpose

The DIMM mask has one clear aperture and one carrying a wedge prism. The prism has poor
anti-reflection coatings and collects dust and condensation, so its throughput relative to the clear
aperture is a direct measure of the state of the optics. Nightly throughput tracks condensation
clearly in the archive.

The intended use is a cross-check against the Adafruit humidity sensor: does the prism dew before
the 90% RH operating limit is reached? A dew heater is ruled out — the heat would generate
turbulence — so knowing when the prism is fogging is the available remedy.

The two time constants come free from the same series and are logged because the data supports them,
not because anything downstream asks for them yet.

## Constraints

- **`seeing.csv` is frozen.** Things outside this repository depend on its column format. No columns
  may be added to it. All new values go in `~/scintillation.csv`.
- **HDIMM is out of scope.** The three-aperture mask has no clear/prism pair, so throughput as
  defined here does not describe it. `scripts/ekos_hdimm/postcapture.py` is not modified and writes
  no scintillation data.
- **No acquisition changes.** The frame rate stays as it is. Raising it toward 1 kHz is separate
  work with its own SNR and bandwidth questions.
- Python 3.13+, astropy units where quantities are physical, 132-character lines.

## Prerequisite: the returned series cannot currently be placed in time

`analyze_dimm_cube` (`src/timdimm_tng/analyze_cube.py:283`) appends to `baselines`, `positions` and
`fluxes` only for frames where `dimm_calc` returns non-`None`, but returns `frame_times` as
`cube["frame_times"]` — the *full* cube, length `nframes`. When `N_bad > 0` these have different
lengths, and nothing records which frames were dropped. Zipping times to fluxes silently shifts the
series against each other.

**Fix:** `analyze_dimm_cube` gains a `frame_index` entry in its returned dict — an integer array of
the cube indices whose frames survived, in order, `len(frame_index) == len(aperture_fluxes)`. This is
purely additive; no existing key changes meaning, and no existing caller is affected.

Every estimator below depends on it. Correlating by position in the compacted array instead of by
cube index is the error that produced the nonsense result on `indi_2023-12-08@20-48-35` recorded in
the notes.

## Architecture

```
analyze_dimm_cube(...)  ->  results dict  ->  scintillation_stats(results)  ->  dict of scalars
                                                                                      |
                                        scripts/ekos_timdimm/postcapture.py  ->  ~/scintillation.csv
```

**`src/timdimm_tng/scintillation.py`** is a new module holding one public function and its helpers.
It performs no file I/O, loads no cubes, and reads no globals. Its entire input is the dict
`analyze_dimm_cube` returns, which makes every estimator testable against synthetic series with
known answers.

**`scripts/ekos_timdimm/postcapture.py`** calls it and writes the row. It is the only writer.

### `scintillation_stats(results)`

Consumes the `analyze_dimm_cube` results dict, using `aperture_fluxes`, `baseline_lengths`,
`frame_times`, `frame_index` and `N_bad`. Returns a flat dict of Python floats and ints — the
columns of the output row, minus the ones postcapture supplies from elsewhere (`time`, `target`,
`exptime`).

## Estimators

### Throughput

Assign faint and bright **once per cube**, from the median flux over all kept frames. The prism
aperture is always the fainter one. Assigning per frame takes the minimum of two noisy numbers every
time and biases the ratio low even for two identical apertures. `find_apertures` sorts by x centroid,
so the array index of the prism depends on the camera orientation, which has changed three times —
index is not identity.

Then report the **ratio of the mean fluxes**, `sum(faint) / sum(bright)`:

```
throughput = faint.sum() / bright.sum()
```

Not the mean of the per-frame ratios. Noise in the denominator inflates the mean of a ratio, and
1 ms frames scintillate hard enough for this to matter enormously. Two *identical* simulated
apertures give:

| frame-to-frame scatter | mean of ratios | ratio of means |
|---|---|---|
| 10% | 1.010 | 1.000 |
| 30% | 1.176 | 1.000 |
| 50% | 2.390 | 1.000 |

On real cubes the same comparison gives 0.863 and 1.094 against the correct 0.753 and 0.742. The
ratio of means is also the physically meaningful quantity: total light through the prism over total
light through the clear aperture.

### Scintillation index

Per kept frame, `r = faint / bright`. The index is the normalised variance:

```
scint_index_raw = var(r) / mean(r)**2
```

Built on the ratio rather than on a single aperture's flux, which makes it differential —
transparency changes and cloud move both apertures together and cancel, leaving what differs between
two apertures a few centimetres apart.

**The column is named `scint_index_raw` and no noise subtraction is applied.** The measured values
of 0.323 and 1.259 on the two `seeing_2024-05-05` cubes are too large to be atmospheric
scintillation alone; an index above 1 means the ratio's standard deviation exceeds its mean. Shot
noise and centroiding scatter are inside this number. Rather than bake in a correction that cannot
be validated against anything, the raw index is logged under a name that says so, and
`mean_flux_bright` and `mean_flux_faint` are logged beside it so a photon-noise floor can be
estimated and subtracted downstream by whoever needs it.

### Autocorrelation by frame lag

Both time constants use one shared helper. For a series `x` with cube indices `idx`, the
autocorrelation at integer lag *k* uses **only** the pairs whose indices differ by exactly *k*:

```
rho(k) = corr(x[i], x[j])  over all pairs with idx[j] - idx[i] == k
```

Dropouts are left as gaps. They are never closed up by correlating adjacent entries of the compacted
array. The helper also returns the number of contributing pairs at each lag.

The time axis is `dt`, the **median** inter-frame interval taken from `frame_times`, not the nominal
frame rate. Cadence jitter at 299 Hz is 0.15–0.21 ms with 98% of intervals within 10% of the median
— small, but the cadence has ranged over a factor of 30 across the archive and a nominal rate is not
a measurement.

### Image-motion time constant

Computed on **`baseline_lengths`** — the differential motion, the same series the seeing is computed
from. Not on the mean of `aperture_positions`, which is common-mode motion: telescope shake, wind on
the tube, tracking error. The two have different time constants and only the differential one is an
atmospheric quantity.

`rho(k)` is evaluated at lags 1 through 4 and a straight line is fitted to `log(rho)` against
`k*dt`. Then `tau_motion = -1 / slope`.

A fit rather than an e-folding read off the curve, because at 299 Hz the measured tau of 4–6 ms is
only 1.2–1.7 samples long. The 1/e crossing falls between two samples and interpolating it is
interpolating noise. Four lags is the most the decay supports before `rho` reaches the noise floor —
the measured sequence is 0.63 / 0.28 / 0.13 for one cube and 0.47 / 0.17 / 0.04 for the other.

*Provisional.* This estimator is chosen from what the data support, not from the literature. Tim has
reference papers to bring; if they prefer a structure function or a specific model, this section is
the one to revise. Nothing else in the design depends on which estimator is used.

### Scintillation time constant

The same machinery applied to the ratio series `r`, with censoring.

If `rho(1) < 0.2`, the series is decorrelated after a single frame and the time constant is shorter
than the sampling can resolve. Report:

```
tau_scint_ms      = dt in milliseconds     # the upper limit
tau_scint_censored = 1
```

Otherwise fit as for image motion and set `tau_scint_censored = 0`.

At 299 Hz this will censor: measured `rho(1)` is 0.10 and 0.01 on the two clean cubes. That is
consistent with the ~5 ms wind crossing time of a 50 mm aperture at 10 m/s but not measurable from
it; resolving it needs roughly 1 kHz, which is an acquisition question and out of scope.

`acf1_ratio` is logged unconditionally as the evidence behind the flag. If the frame rate ever rises
to where `rho(1)` stays above the threshold, the same code begins returning a fitted number and
clears the flag with no code change.

## Output schema

`~/scintillation.csv`, a single ever-growing file with a header written on creation — mirroring
`~/seeing.csv` rather than rotating nightly, so anything that already reads seeing.csv needs no new
pattern.

| column | source | meaning |
|---|---|---|
| `time` | postcapture | `Time.now().isot`, **byte-identical** to the seeing.csv row |
| `target` | `pointing_status['target']` | |
| `throughput` | stats | faint/bright, ratio of mean fluxes |
| `scint_index_raw` | stats | `var(r)/mean(r)**2`, no noise subtraction |
| `tau_motion_ms` | stats | fitted over lags 1–4 of the differential series |
| `tau_scint_ms` | stats | fitted, or `dt` when censored |
| `tau_scint_censored` | stats | 1 when `tau_scint_ms` is an upper limit |
| `acf1_ratio` | stats | lag-1 autocorrelation of the flux ratio |
| `cadence_hz` | stats | `1 / dt` from the median inter-frame interval |
| `n_frames` | stats | frames in the cube |
| `n_kept` | stats | frames that survived centroiding |
| `mean_flux_bright` | stats | for recovering a shot-noise floor later |
| `mean_flux_faint` | stats | |
| `exptime` | postcapture | already computed there |

`time` being byte-identical to the seeing.csv row is what lets the two files join with no fuzzy time
matching. Matching a row to an Adafruit RH reading is a nearest-sample join done downstream; this
file encodes nothing about it.

Floats are written to a fixed precision — `throughput` and `scint_index_raw` to 4 decimals, the taus
and `cadence_hz` to 2, `acf1_ratio` to 3 — so the file stays diffable and readable.

`n_frames` and `n_kept` are what make a row interpretable. A time constant from a heavily decimated
series is not a measurement: the notes record a 299 Hz cube that kept 435 of 4420 frames and gave an
answer contradicting a good cube at less than half the rate. Consumers are expected to filter on
`n_kept`.

## Where the row is written

In `scripts/ekos_timdimm/postcapture.py`, immediately after `analyze_dimm_cube` returns and
**before** the `seeing < 10.0 and N_bad < 50` quality block — not inside it.

A dewed prism is exactly the condition this feature exists to catch, and exactly the condition in
which the seeing analysis is likeliest to fail its gate. Gating the scintillation row on the seeing
row would silence the instrument when it matters most. `n_kept` and the seeing row's absence are
together enough for a consumer to judge the row.

If `analyze_dimm_cube` raises, no row is written. The existing `log.error` covers it.

### A latent bug to fix in the same edit

`postcapture.py:83-89` catches the exception from `analyze_dimm_cube`, logs it, moves the cube
aside — and then falls through to `if np.isfinite(seeing_data['seeing'].value)` with `seeing_data`
never bound, raising `NameError` and killing the script before the following lines run. The `except`
block needs `sys.exit(0)`.

This is pre-existing and unrelated to scintillation, but the new code sits directly on top of it and
it would otherwise be inherited.

## Failure behaviour

Degenerate inputs return NaN in the affected column. They do not raise, and they do not suppress the
row — a row with NaN taus and a populated `n_kept` is informative, a missing row is not.

| condition | result |
|---|---|
| `n_kept < 50` | all stats NaN except `n_frames`, `n_kept`, `cadence_hz` |
| `mean(bright) <= 0` or `mean(faint) <= 0` | `throughput`, `scint_index_raw` NaN |
| fewer than 2 usable lags, or non-negative fitted slope | that tau NaN |
| `rho(1)` not finite | `tau_scint_ms` NaN, `tau_scint_censored` 0 |

`n_frames`, `n_kept` and `cadence_hz` come from the cube rather than from the estimators and are
always populated. The 50-frame floor is a deliberate refusal rather than a computable-but-meaningless
answer.

## Testing

TDD throughout. Every estimator is exercised against synthetic series with analytically known
answers; no test depends on archived data being present.

**Throughput**
- two identical noisy apertures at 10%, 30% and 50% scatter recover 1.000, while mean-of-ratios
  gives 1.010, 1.176 and 2.390 — the bias is asserted as a fact about the naive estimator, not
  merely avoided
- faint/bright assignment is correct when the faint aperture is at index 0 and when it is at index 1
  (the camera-orientation problem)
- assignment is stable when individual frames happen to invert the ordering

**Scintillation index**
- a constant ratio gives 0
- a ratio with known lognormal scatter recovers the expected normalised variance

**Autocorrelation helper**
- white noise gives `rho(1)` near 0
- a constant-offset series gives `rho(1)` near 1
- pair counts at each lag match what the index array implies

**Time constants**
- an AR(1) series with known tau is recovered to within a few percent
- **the same series punctured by deleting 20% of frames at random recovers the same tau** — the test
  that proves gaps are handled as gaps rather than closed up
- a series whose indices are contiguous and one whose indices are sparse but describe the same
  underlying process agree

**Censoring**
- white-noise ratio sets `tau_scint_censored = 1` and `tau_scint_ms == dt`
- a slowly varying ratio sets it to 0 and returns a fitted value

**Degenerate cases**
- `n_kept = 49` returns NaN stats and does not raise
- zero mean flux returns NaN `throughput` and does not raise

**`frame_index`**
- `analyze_dimm_cube` returns `frame_index` with the same length as `aperture_fluxes`
- on a cube with induced bad frames, `frame_index` omits exactly those indices

## Out of scope

- Batch reanalysis of the archived cubes. Separate work.
- Any change to the frame rate or ROI.
- HDIMM.
- Shot-noise correction of the scintillation index.
- Joining to the Adafruit humidity log. The columns needed to do it are logged; the analysis is not
  part of this.

## As built

The design above is left as it was written. Four things changed during implementation, and the code
is the authority where they disagree:

- **The index is estimated in log space.** The schema table says `var(r)/mean(r)**2`; what shipped
  first was that variance over 5-sigma-clipped frames, and what is there now is `exp(sigma**2) - 1`
  with `sigma` from the MAD of `log(ratio)`. Same quantity, exactly, for the lognormal the ratio is —
  but robust and unbiased at once, where the clip was robust and biased low. `docs/scintillation_logging_notes.md`
  has the evidence that condemned the clipped version.
- **The correlations run on the log ratio, robustly cut.** `acf1_ratio` and the `tau_scint` fit use
  `log_ratio_series`, which drops frames beyond 5 MAD-sigma of the median log ratio. Pearson
  correlation is not robust, so a dropout frame that the index shrugs off could still censor a
  genuinely correlated cube. Same notes file, "The autocorrelation needs the opposite treatment".
- **Two columns were added:** `frac_rejected`, the fraction of frames with no usable logarithm, and
  `airmass`, which the index cannot be interpreted without — it goes as roughly sec(z)**3 while the
  seeing `analyze_dimm_cube` reports has already been divided by `airmass**0.6`. `airmass` is written
  at the 3 decimals `seeing.csv` uses.
- **A cube with unusable timestamps yields a partial row rather than nothing.** The failure table
  above has no entry for `dt` being NaN, and the first implementation suppressed every stat. Only
  the two time constants need a frame interval; throughput and the index need frame *order*, so
  those are still written.

- **`tau_scint_censored` is three-valued, and the gate is 1/e** (changed 2026-08-17, after the
  first full night on sky). The schema table above says 1 means an upper limit; it now also carries
  2, meaning no fit was obtained and `tau_scint_ms` is NaN. The invariant is that **0 always means a
  finite fitted measurement** — the failure table's "`rho(1)` not finite → censored 0" row is
  superseded, as is the early return for a cube with no usable `dt`. `ACF1_CENSOR_THRESHOLD` moved
  from 0.2 to `1/e = 0.368`, which is the value that makes the gate mean what it claims: `rho(1)` is
  `exp(-dt/tau)`, so `tau >= dt` is exactly `rho(1) >= 1/e`, and 0.2 was `tau = 0.62` frames. See
  `docs/scintillation_logging_notes.md` for the night that forced both changes.

Seeing validity (`seeing_is_valid`, `DIMM_IMAGE_SHAPE`, `MIN_CADENCE_HZ`) was outside this spec
entirely, and arrived from the archive run: cubes that cannot measure seeing were writing
sub-arcsecond values to `seeing.csv`. It gates only the `seeing.csv` write; the scintillation row is
written for any cube.
