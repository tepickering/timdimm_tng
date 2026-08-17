# Notes toward logging scintillation from analyze_cube

Starting point for a spec, not a design. Records what has been decided, what has already been
measured, and the open questions — so the spec can be written in a fresh session alongside the
reference papers.

The first four values ship in `src/timdimm_tng/scintillation.py` and are logged to
`~/scintillation.csv` in production as of 2026-08-16; the spec is
`docs/superpowers/specs/2026-08-14-scintillation-logging-design.md`. Findings from the exploratory
implementation that preceded it are kept below because they constrain the design, and the later
sections record what the first night on sky and the reference papers have since changed.

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

## The first full night on sky, 2026-08-16

451 cubes, 22:49 to 04:18, on Fomalhaut, Achernar and Canopus. It settled the censoring question
and raised a sharper one.

**The gate was mis-calibrated and is now 1/e.** `rho(1)` is `exp(-dt/tau)`, so requiring the time
constant to be at least one frame is exactly `rho(1) >= 1/e = 0.368`. The gate stood at 0.2, which
is `tau = 0.62` frames, and everything it admitted in between was sub-frame — reported as a fitted
measurement while being smaller than the interval that could measure it. That band was not a corner
case: of the 162 rows the old gate passed, **32 came back NaN** because `fit_tau` then failed, and
their `acf1_ratio` values run 0.200 to 0.350 — the mis-calibrated band exactly. `tau_scint_censored`
was 0 on all 32, indistinguishable from a good fit, so the column now carries 2 for a failed fit and
0 means a finite fitted value and nothing else.

The honest census of the night, at the corrected gate: **55 rows of 451 (12%) clear 1/e**. The
archive's "73% censored" was optimistic for the same reason — at 299 Hz scintillation is unresolved,
and one night of real data did not change that.

**The tau estimators track signal strength, not just timescale.** `tau_motion_ms` correlates with
`scint_index_raw` at Spearman +0.696 pooled and **+0.515 within Achernar alone** (357 cubes, airmass
1.10 to 1.25), against only +0.24 with seeing. Binning Achernar by index is monotonic across all
five bins — index 0.055 gives `tau_motion` 2.32 ms, index 0.201 gives 3.63 ms, with censoring
falling 96% to 67% over the same range. White measurement noise dilutes an autocorrelation towards
zero, so a weak signal shortens the apparent time constant; a real timescale should not care how
large the signal is. **Treat both tau columns as SNR-contaminated until this is separated.** The
test would be injecting known noise into a synthetic series at fixed tau and watching the recovered
tau move.

**Airmass is still not settled**, and this observing pattern cannot settle it. Pooled
`corr(index, airmass)` is +0.691, which looks decisive, but it is entirely between-target: the
scheduler takes the brightest star above 45 degrees, so each target owns a contiguous block of the
night and target, airmass and hour are collinear. Within a target the airmass span is about 0.15 and
the fitted `d ln(index) / d ln(X)` comes out at +8.6 for Achernar and -7.6 for Canopus against a
theoretical ~3 — noise, not measurement. Breaking the degeneracy needs interleaved targets at
different airmasses, which is a scheduler change not worth making for this. Separating it will have
to come from many nights, where a given target recurs at different airmasses.

`corr(index, seeing)` was +0.283 pooled over the night, the same weak value the archive gives.

## Kornilov 2011: get the timescale from the index, not from its decay

V. Kornilov, *Stellar scintillation in short exposure regime and atmospheric coherence time
evaluation*, A&A, arXiv:1103.6265. This is the MASS temporal theory. It is **not** a profile
restoration paper — that is Tokovinin et al. 2003 and Kornilov et al. 2007, which it cites — but it
bears directly on the time constants we log, and it says our estimator is the wrong shape.

Its central result is that a finite exposure `tau` low-passes the scintillation and depresses the
index quadratically (Eq. 4):

    s_tau^2 = s_0^2 - (tau^2 / 6) * V2U,    V2U = integral Cn2(h) * w(h)^2 * U(h) dh

so measuring the index at two exposures yields the wind moment with no need to resolve anything
(Eq. 10), and with `r0` from the DIMM, Eq. 14 gives the atmospheric coherence time
`tau_0 = 0.314 * r0 / V2bar`. The timescale is read off *how much the index shrinks* when you
integrate longer. There is no sampling floor to fight — which is the entire problem with the
`fit_tau` approach, where 12% of rows on 2026-08-16 cleared the one-frame gate.

**Interleaved exposures are not available to us.** Exposure cannot be varied within a single SER
capture, and alternating between cubes leaves enough gap time for conditions to change, so the two
indices would not describe the same atmosphere. Eq. 8/9, which synthesise the 2*tau index from
adjacent frames, do not rescue this either: they require exposures that tile the time axis
contiguously, and at 1 ms exposure on a 3.342 ms cadence our duty cycle is **0.299**. Summing
adjacent frames gives two 1 ms samples 3.3 ms apart, not one 2 ms exposure.

### The same quantity is reachable from two lags of the autocorrelation

An exposure and a lag are two ways of applying a known low-pass filter, and to second order both
read the same second spectral moment `M2 = integral f^2 S(f) df`:

    exposure:  s_tau^2  = s_0^2 - (pi^2 tau^2 / 3) M2      matching Eq. 4 gives V2U = 2 pi^2 M2
    lag:       cov(D)   = s_0^2 - 2 pi^2 D^2 M2

Differencing the index against the covariance gives `V2U = s^2 (1 - rho_1) / D^2`, where `D` is the
frame interval. That form is worthless in practice: white photon noise adds to `s^2` but to no
nonzero lag, so it enters the estimate at full weight. Differencing **two lags** instead removes it
completely:

    V2U = s^2 * (rho_1 - rho_2) / (3 D^2)

The exposure filter cancels at this order, so the measured index and measured correlations go in
directly, with no zero-exposure correction. Verified numerically on synthetic series of 4400 frames
with a Gaussian ACF (200 seeds; an AR(1) is useless as a test here — its ACF has a cusp at zero lag,
so its `M2` diverges):

| true T | D/T | recovered, no noise | with equal-power white noise | 5-95 with noise |
|---|---|---|---|---|
| 8 ms | 0.42 | -19% | -20% | 471 - 671 (truth 703) |
| 15 ms | 0.22 | -5.8% | -6.3% | 106 - 278 (truth 200) |
| 30 ms | 0.11 | -0.5% | -3.8% | -38 - 130 (truth 50) |

Two things to read off that table. The bias is the quadratic truncation and scales as `(D/T)^2`, so
the method needs `D << T` — the direct analogue of Kornilov's short-exposure regime, and the reason
his Eq. 5/6 check matters. And **photon noise costs precision, not accuracy**: the median barely
moves, while the 5-95 spread widens until the estimate can go negative. That is the same trade
Kornilov names for DESI in §9, which is "noisier by an order of magnitude" for working with small
differences.

### What this needs before it can be tried

- **`acf2_ratio` must be logged.** We record only `acf1_ratio`, so the estimator cannot be evaluated
  on 2026-08-16 retrospectively. One column, and `scintillation.csv` is not frozen — `seeing.csv` is.
- **Photon noise still has to be handled**, even though the estimator is immune in the median. The
  spread above is what an equal-power noise term does to a single cube, and our shot-noise term is
  worth ~31% of the median index. This is Kornilov's §9 warning: *"The most dangerous is a systematic
  error due to an incorrect accounting for photon noise."*
- **Absolute `tau_0` needs `U(h)` for our aperture**, from the Eq. 2 integral (Bessel J0/J1 and
  Struve H0/H1, Eq. 3) and the decomposition coefficients of his Appendix A. Without it the estimator
  gives a *relative* wind moment that can be tracked and correlated, but not a coherence time in ms.

### Our optics, and what they permit

timDIMM is `D = 50 mm` with a `200 mm` baseline (`timdimm_seeing`, `analyze_cube.py:173`) — **not**
the 76.2 mm / 143 mm defaults of `seeing()`, which belong to another configuration. At 500 nm:

| h | r_F = sqrt(lambda h) | D/r_F | b/r_F |
|---|---|---|---|
| 1 km | 2.2 cm | 2.24 | 8.94 |
| 2 km | 3.2 cm | 1.58 | 6.32 |
| 5 km | 5.0 cm | 1.00 | 4.00 |
| 10 km | 7.1 cm | 0.71 | 2.83 |
| 15 km | 8.7 cm | 0.58 | 2.31 |
| 20 km | 10.0 cm | 0.50 | 2.00 |

`D/r_F` runs 0.5 to 1.0 through the whole free atmosphere and exceeds 1 only below ~5 km, so we sit
on the **small-aperture** side. Neither of Kornilov's asymptotes applies: not `D >> r_F`
(`U(h) ~ 17.22 lambda^-2/3 D^-3 h^4/3`), and not the point aperture, for which he notes no asymptote
exists at all since the integral diverges as `D -> 0`. Consequences: little aperture averaging, hence
a large index — consistent with the 0.11 to 0.40 we measure — and an altitude weighting tending
towards the point-source `h^5/6` rather than `h^2`, so the free atmosphere is weighted *less*
strongly than the large-aperture case. 50 mm falls between MASS apertures B (3.7 cm) and C (7 cm),
which also implies we fall out of the short-exposure regime somewhat more often than MASS aperture C
does: smaller apertures are more sensitive to turbulence motion, and his Table 1 gives 12.5% (B) and
6.3% (C) out of SE at 2 ms.

**Our index is not one of Kornilov's cross-indices.** MASS cross-indices are between *concentric*
apertures of differing diameter sharing one pupil. Ours are two *equal* 50 mm apertures separated
laterally by 200 mm, a geometry that does not appear in the paper, so neither his Fig. 1 weighting
functions nor the remark that cross-indices go negative at low altitude transfers to us. The
weighting function we would need is `W_diff(h) = 2 W(h) [1 - C(b,h)/C(0,h)]` with `C` the spatial
covariance of the intensity, derived for our configuration. On the credit side `b/r_F` is 2.0 to 4.0
in the free atmosphere and ~9 at 1 km, so the two apertures are well decorrelated and
`var(log ratio) ~ 2 sigma^2` is a fair working approximation, improving towards low altitude.

**One aperture diameter means one moment, not a profile.** MASS inverts a profile because four
concentric apertures give ten indices; we have a single diameter, hence a single weighting function,
hence a single number. No processing changes that. What we can do without new hardware is combine two
differently-weighted integrals we already measure at the same instant on the same star — seeing gives
`integral Cn2 dh`, the index gives a higher-weighted moment — and form an effective turbulence
height. One number rather than a profile, but it is the number that says ground layer or free
atmosphere. The `h^5/6` weighting above makes that lever weaker than a large aperture would give, and
how much weaker is the `W(h)` calculation, not a guess.

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

- Tokovinin (2002), https://www.jstor.org/stable/10.1086/342683 — the DIMM equations `seeing()`
  already cites.
- Kornilov (2011), arXiv:1103.6265, A&A — stellar scintillation in the short exposure regime and
  `tau_0` evaluation. See the section above for what it changes here.
- Cited by the above and not yet read, for when the weighting functions are needed: Tokovinin et al.
  (2003), MNRAS 343, 891 and Kornilov et al. (2007), MNRAS 382, 1268 for the MASS profile
  restoration and the `W(h)` set; Kornilov (2011), arXiv:1101.3211 for the long-exposure regime and
  the `A_s` spectral filter.
