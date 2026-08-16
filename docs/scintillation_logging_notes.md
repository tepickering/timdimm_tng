# Notes toward logging scintillation from analyze_cube

Starting point for a spec, not a design. Records what has been decided, what has already been
measured, and the open questions — so the spec can be written in a fresh session alongside the
reference papers.

Nothing here is implemented. An exploratory implementation of the first two values was written and
reverted; its findings are kept below because they constrain the design.

## What we want

Four values logged per seeing measurement:

1. **Mean flux ratio** — the prism aperture's throughput relative to the clear one.
2. **Scintillation index** — from the variation of that flux ratio.
3. **Time constant of the scintillation.**
4. **Time constant of the image motion.**

## Decided

**`seeing.csv` is frozen.** Things outside this repository depend on its format, so no columns are
to be added to it. The new values go in a separate **`scintillation.csv`**.

**Why the flux ratio is worth logging** is covered in `archive_notes.md`: the mask has one clear
aperture and one carrying the wedge prism, the prism has poor anti-reflection coatings and collects
dust and condensation, and its throughput is therefore a direct measure of the state of the optics.
Nightly throughput tracks condensation clearly in the archive. The intended use is a cross-check
against the Adafruit humidity sensor, to find out whether the prism dews before the 90% RH
operating limit is reached. A dew heater is ruled out — the heat would generate turbulence.

## Already established, carry into the spec

**Report the ratio of the mean fluxes, not the mean of the per-frame ratios.** These are very
different numbers and the naive one is badly wrong. Noise in the denominator inflates the mean of a
ratio, and 1 ms frames scintillate hard enough for it to matter enormously. Two *identical*
simulated apertures give:

| frame-to-frame scatter | mean of ratios | ratio of means |
|---|---|---|
| 10% | 1.010 | 1.000 |
| 30% | 1.176 | 1.000 |
| 50% | 2.390 | 1.000 |

On a real cube (`indi_2023-06-22`, 2268 frames) the same comparison gives **1.312 against 0.945**.
The ratio of means is also the physically meaningful quantity — total light through the prism over
total through the clear aperture.

**Identify the apertures once per cube, not per frame.** `find_apertures()` sorts by x centroid, so
which index holds the prism depends on the camera orientation, which has changed three times (see
`archive_notes.md`). The prism is always the fainter aperture, so assign faint/bright from the
median flux over the whole cube. Choosing the fainter aperture frame by frame takes the minimum of
two noisy numbers every time and biases the ratio low even for identical apertures.

**Build the index on the ratio, not on a single aperture's flux.** That makes it differential:
transparency changes and cloud move both apertures together and cancel, leaving what differs
between two apertures a few centimetres apart. Definition used in the exploratory work was the
normalised variance `var(r)/mean(r)**2`.

## Cadence: what the cubes actually sample

Cube cadence varies by more than a factor of 30 across the archived examples, so any statement
about what is measurable has to name which configuration it refers to. **The intended rate is
299 Hz**, reached with a 400x400 ROI when the camera is running at full USB 3.x speed.

| Example | Frame size | Frames | Duration | Cadence |
|---|---|---|---|---|
| `seeing_2024-05-05T01:57`, `T04:49` | 400x400 | 4423 | 14.76 s | **3.342 ms, 299 Hz** |
| `indi_2023-12-08@20-48-35` | 400x400 | 4420 | 14.75 s | 3.342 ms, 299 Hz |
| `indi_2023-12-08` (7 cubes) | 400x400 | 1776 | 14.74 s | 8.316 ms, 120 Hz |
| `indi_2023-06-22@17-14-39` | 416x443 | 2268 | 51.80 s | 22.9 ms, 43.7 Hz |
| `indi_2025-03-11@01-09-43` | 1608x1104 | 156 | 14.73 s | 95.1 ms, 10.5 Hz |

The 156-frame, 95 ms recordings appear to be setup captures rather than seeing measurements —
`indi_2023-12-08` contains one alongside its fast cubes. The full-frame 2025-03-11 example is also
**saturating**, 86 pixels at or above 65000, which would bias centroids taken from it.

Cadence jitter is small at the fast rates: 0.15 to 0.21 ms standard deviation at 299 Hz, with 98%
of intervals within 10% of the median. It is not perfectly uniform, so an estimator should still
use `frame_times` rather than frame index, but this is nothing like the 43.7 Hz cube's 6% scatter.

## What is measurable at 299 Hz

Measured through `dimm_calc()`, the real centroiding path, on the two `seeing_2024-05-05` cubes.
Both are clean — 4423/4423 and 4422/4423 frames usable — so these correlations are computed on
essentially gapless series.

| | 01:57 | 04:49 |
|---|---|---|
| Throughput | 0.753 | 0.742 |
| Scintillation index of the ratio | 0.323 | 1.259 |
| Flux ratio correlation at 3.34 ms | **0.10** | **0.01** |
| Image motion correlation at 3.34 / 6.68 / 10.03 ms | **0.63 / 0.28 / 0.13** | **0.47 / 0.17 / 0.04** |

**Scintillation is still unresolved at 299 Hz.** The flux ratio is decorrelated after a single
frame. Its time constant is therefore below 3.34 ms, consistent with the ~5 ms wind crossing time
of a 50 mm aperture at 10 m/s but not measurable from it. Resolving it would need roughly 1 kHz,
which is an acquisition question — and at 400x400 and 16 bits that is about 128 MB/s before
overheads.

**Image motion is resolved at 299 Hz**, but only just. The decay is clean and monotonic, and
log-interpolating to 1/e gives **tau of about 5.6 ms and 4.1 ms** for the two cubes. That is only
1.2 to 1.7 samples per time constant, so it supports a fit over the first three or four lags rather
than reading an e-folding off the curve, and the spec should say which.

A caution carried forward: an earlier attempt on `indi_2023-12-08@20-48-35`, also a 299 Hz cube,
kept only 435 of 4420 frames because the target was faint enough to need a threshold of 7 in
`find_apertures()`. Correlating the surviving frames by index gave a nonsense answer that
contradicted the 120 Hz cube. That was a bad cube rather than a property of 299 Hz, but it shows
two things the spec must require: **correlate by frame lag with dropouts left as gaps**, never by
position in a compacted array, and **record how many frames survived**, since a time constant from
a decimated series is not a measurement.

## How precise is a single cube's image-motion tau

Measured during implementation, on synthetic series with a known input tau, through the same
estimator the pipeline now uses. At 4000 frames — a real 299 Hz cube is about 4400 — the fit is
**unbiased but noisy: 4.98 ms recovered from an input of 5.00, with a scatter of 0.59 ms** over 15
realisations. That is about 12%.

The scatter comes from the fit's dependence on the lag-4 correlation, which is only about 0.07 at
this tau. Taking the log of a small correlation amplifies its sampling noise, so the highest lag
used carries most of the error. It is still worth including — dropping to lags 1–3 costs more in fit
leverage than it saves in noise — but it sets the floor on what one cube can say.

**Consequence for interpreting the logged column:** night-to-night changes in `tau_motion_ms`
smaller than roughly 0.6 ms are not measurements. Averaging over a night's cubes tightens it as
usual; a single cube does not resolve a 10% change.

## Why the scintillation index is estimated in log space

The index shipped first as the normalised variance of the flux ratio over 5-sigma-clipped frames.
Clipping was needed because the statistic has the whole cube's noise in its denominator: on
`indi_2023-12-08@20-53-44` the bright aperture fell to 7 ADU against a median of 17357, the
per-frame ratio reached 3049, and the unclipped index came out **498**. Anything above 1 already
means the scatter exceeds the mean.

It worked, but it was **biased low, and increasingly so with the scintillation** — the worst
direction for a turbulence statistic. A symmetric cut on a lognormal removes real tail, not just
dropouts. On synthetic data the clipped estimator returned 0.2195 against a true 0.25 at 50%
scatter; on clean archived cubes it came in 25-30% low (0.621 to 0.383, 1.259 to 0.591) while
rejecting only 1-2% of frames.

Two diagnostics condemned it on real data:

- `corr(index, frac_clipped) = +0.957` over 80 archived cubes. Between-night variation in the index
  was variation in how many frames the clipper removed.
- **The index showed no correlation with seeing** (+0.05 pooled over 63 cubes, flat across seeing
  quartiles) even though it correlated strongly *within* individual nights, where the clipping
  fraction is roughly constant: +0.85 on 2023-06-22 and +0.92 on 2023-12-08. Scintillation and
  seeing are both turbulence integrals — differently weighted, so the correlation is imperfect, but
  its complete absence between nights was an estimator artefact.

Scintillation is multiplicative, so the ratio is lognormal, and for a lognormal the normalised
variance is exactly `exp(sigma**2) - 1` with `sigma` the standard deviation of the log. Estimating
`sigma` from the **median absolute deviation of `log(ratio)`** is robust *and* unbiased: a
median-based scale cannot be moved by outliers, so nothing has to be discarded to resist them.
Recovery on synthetic lognormal series is exact to better than 1% at 10, 20, 30 and 50% scatter.

Only frames with a ratio that is zero, negative or non-finite are dropped — they have no logarithm —
and the count is logged as `frac_rejected`, which replaces `frac_clipped`.

### The autocorrelation needs the opposite treatment

Making the index robust left `acf1_ratio` exposed, because it is a Pearson correlation and Pearson
is not robust. A dropout frame's ratio is in the thousands but still finite and still positive, so
nothing rejects it, and being isolated it enters one lag-1 pair as an enormous excursion beside an
ordinary neighbour. On a synthetic cube with 1% such frames, rho(1) falls from 0.75 to near zero —
logged as `tau_scint_censored = 1` beside a `frac_rejected` of **0.0**, which reads as a clean cube.

So the correlations run on `log_ratio_series`: the log of the ratio, with frames beyond
`ACF_CLIP_SIGMA = 5` robust sigma of its median removed. Clipping here is not the mistake clipping
made in the index. There the statistic *is* the scale of the distribution, so cutting the tail
shrinks the answer; a correlation is a shape statistic on a fixed set of pairs, and removing 1% of
frames leaves the decay alone. The log is the natural space regardless — scintillation is
multiplicative, so the log ratio is the additive quantity whose autocorrelation means something.

On clean real cubes the change is small and the conclusion unaffected: rho(1) moves 0.103 to 0.129
(2024-05-05 01:57), 0.126 to 0.145 and 0.050 to 0.052 (2026-08-16), with 0 to 3 frames of 4400
dropped. All remain far below `ACF1_CENSOR_THRESHOLD`, so scintillation is still unresolved at
299 Hz — the point of the fix is the cube that *isn't* clean.

## A cross-check worth noting

The throughput measured here from SER cubes, 0.753 and 0.742, agrees with the 0.716 measured from
the single pre-seeing exposures in `archive_notes.md`. Those come from a different instrument mode,
a different code path, and a different year. Two independent routes to the same number is decent
evidence that the prism throughput is a real, stable property and not an artifact of either
pipeline.

The estimator bias shows up again on this real data: mean-of-ratios gives 0.863 and 1.094 against
the correct 0.753 and 0.742.

## What the pipeline already provides

`analyze_dimm_cube()` returns, per frame kept:

- `aperture_fluxes` — flux in each aperture, the input to values 1 and 2
- `baseline_lengths` — the differential separation whose variance gives the seeing, the natural
  input to the image motion time constant
- `aperture_positions` — mean aperture position, i.e. the common-mode image motion
- `frame_times` — timestamps, needed given the non-uniform cadence

Frames where centroiding failed are dropped rather than marked, so the series have gaps that do not
announce themselves. Any time-domain estimator has to work from `frame_times` rather than assuming
the samples are contiguous.

## Open questions for the spec

- **Definition of each time constant.** Autocorrelation e-folding, structure function, or fit to a
  model? At 1.2 to 1.7 samples per time constant an e-folding read off the curve is too coarse, so
  this probably has to be a fit. The reference papers should settle it rather than a choice made
  here.
- **What to do about the scintillation time constant**, given 299 Hz does not resolve it. Log it as
  an upper limit, raise the frame rate towards 1 kHz, or drop it from the schema? Raising the rate
  costs SNR per frame and bandwidth, and the effect on the seeing measurement itself would have to
  be checked.
- **Whether the frame rate is stable enough to compare across nights.** The archive shows 10.5,
  43.7, 120 and 299 Hz configurations. A time constant logged without its cadence is not
  interpretable, so the cadence belongs in the schema.
- **HDIMM.** The three-aperture mask has no clear/prism pair, so the flux ratio as defined does not
  describe it. Log nothing, or define something else?
- **File format and rotation.** `scintillation.csv` schema, and whether it rotates nightly like the
  other logs.
- **Where it is written.** `timdimm_analyze()` writes the working-directory files; the production
  path is `scripts/ekos_timdimm/postcapture.py`, which writes `~/seeing.csv` and `~/seeing.txt`.
- **Joining to RH.** What key ties a `scintillation.csv` row to an Adafruit sensor reading, and is
  the sensor logging cadence enough for that.

## Reference papers

To be added — Tim has papers to bring to the spec session. `seeing()` already cites Tokovinin
(2002), https://www.jstor.org/stable/10.1086/342683, for the DIMM equations.
