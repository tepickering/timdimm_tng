# Notes on the pre-seeing exposure archive

Working notes on the single exposures taken before each seeing measurement, and on what the
first full-archive run of `analyze_pictures` says about them. These are scratch notes kept so
the findings are not lost between sessions; they are meant to be folded into proper Sphinx
documentation later.

All numbers below come from a run over the whole archive on 2026-08-12, using the code at
commit `f62ba39` or later. Earlier tables are not comparable — see [Caveats](#caveats).

## Instrument history

Four events split the archive. They are independent of each other — no two coincide — so a query
that cares about more than one has to apply each split separately.

| Date | Event | What it changed |
|---|---|---|
| 2025-10-30 | camera reconfigured | `gain` 350 to 200, `offset` 10 to 1 |
| 2026-02-19 | USB cable replaced, camera rotated in the process | mask axis 150 deg to 72 deg; **`star0`/`star1` labels swap** |
| 2026-03-10 to 2026-04-08 | mount hardware failure; system disassembled for the repair | no data for 30 nights |
| 2026-04-09 | reassembled after the repair | mask axis 72 deg to 104 deg; labels swap back; spot size asymmetry drops from 1.65 to 1.35 |

The rotations on 2026-02-19 and 2026-04-09 were both incidental to other work rather than
deliberate, which is why neither lines up with a configuration change and why the mask axis does
not return to its original angle.

## The archive

| | |
|---|---|
| Frames measured | 171,714 |
| Nights | 329 |
| Span | 2025-01-01 to 2026-08-09 |
| Targets | 11 |
| Frames per night | median 460, max 2,795 |
| Table | 60 columns, 87.5 MB as ECSV |

Detection outcome:

| Result | Frames | Share |
|---|---|---|
| Both spots measured | 136,112 | 79% |
| One spot only | 19,121 | 11% |
| No spots | 16,481 | 10% |

The frames with no detection are not spread evenly — they pile up on particular nights
(2026-07-09 alone accounts for 1,879), which is the signature of cloud rather than of a
measurement failure. The 30 nights lost to the mount repair contribute no frames at all rather
than empty ones.

Target counts are dominated by Sirius (44,169), Canopus (32,534), Achernar (25,445),
Spica (22,039) and Mimosa (20,077).

## Two camera configurations

**The camera settings changed exactly once in the archive, and both gain and offset moved
together.** There is a single transition and no night contains frames from both epochs, so the
archive splits cleanly on either date or gain.

| | gain 350 | gain 200 |
|---|---|---|
| Nights | 2025-01-01 to **2025-10-29** | **2025-10-30** to 2026-08-09 |
| Last / first frame | 2025-10-29T20:39:51 | 2025-10-30T17:55:56 |
| `gain` | 350 | 200 |
| `offset` | 10 | 1 |
| `egain` (e-/ADU) | 0.026 | 0.148 |
| `bkg_median` (adu) | 1552 | 160 |
| `bkg_rms` (adu) | 99.7 | 24.3 |
| Frames | 51,789 (145 nights) | 119,925 (184 nights) |

Two things follow from this, and they are the reason the split matters:

**Anything measured in counts is two populations, not one time series.** Background level, flux,
peak and SNR all shift by a factor of several across the boundary for reasons that have nothing
to do with the sky. Median `star0_flux` is 658,000 adu at gain 350 against 64,000 at gain 200.
Always group by gain before summarising a count-valued column.

**`bkg_median` is the offset pedestal, not sky.** It is *exactly* 1552 in every gain 350 frame and
*exactly* 160 in every gain 200 frame — the 5th and 95th percentiles are identical to the median.
At a 1 ms exposure the sky contributes nothing measurable, so the frame median is just the bias
level. It is useful as a check that the camera configuration has not changed underneath you, and
useless as a sky brightness measurement. `bkg_rms` (100 adu and 24.3 adu) is the quantity that
carries the read noise.

The `egain` ratio confirms the gain scaling: 0.148 / 0.026 = 5.7, against 10^(15.0/20) = 5.62 for
a 150-unit change in a 0.1 dB gain index. See the ASI432MM notes for the calibration itself.

## Three orientation epochs

`star0` and `star1` are **x-sorted positional labels, not mask-aperture identities**: whichever
spot has the smaller x is called `star0`. The mask axis moved twice during the archive, and both
moves carried it across a position angle of 90 degrees — which is exactly where the two spots
exchange x-order. **The labels therefore swap between epochs.** `sep_pa` is what identifies the
epoch; it is folded into (-90, +90] by the x-sorting, so the table below reports it as an axis
angle mod 180.

| Epoch | Nights | Axis PA | Frames | Labels | Ended by |
|---|---|---|---|---|---|
| 1 | 2025-01-01 to **2026-02-18** | 150.0 deg | 91,432 | as 3 | USB cable replacement |
| 2 | **2026-02-19** to 2026-03-09 | 71.7 deg | 7,733 | **swapped** | mount failure |
| 3 | **2026-04-09** to 2026-08-08 | 103.9 deg | 36,943 | as 1 | current |

Both transitions are sharp — 2026-02-18 is entirely epoch 1 and the following night entirely
epoch 2 — because both were single discrete disturbances: the camera was rotated inadvertently
while a USB cable was being replaced, and rotated again when the system was reassembled after the
mount repair. Neither move coincides with the gain change of 2025-10-30, which falls in the middle
of epoch 1, so the camera settings and the camera orientation are independent splits.

Spot separation is stable throughout at a median `sep_pix` of 52.2 px (5th-95th percentile 40.3 to
68.5), consistent with the mask geometry and unaffected by the rotations.

## Which aperture is which

The mask has **one clear aperture and one carrying a small-angle wedge prism**. The prism is what
splits a single target into two images: it deflects its beam by a fixed small angle, which is why
`sep_pix` is stable at 52 px regardless of the star. The prism has no anti-reflection coating
worth the name, and it collects dust and condensation.

**The prism aperture is therefore always the fainter one, and `flux_ratio` is what identifies the
apertures.** This is the reliable discriminant — more so than position, which the rotations move
around, or size. It also means the throughput ratio is a direct measure of the state of the prism,
which turns out to be useful (see below).

## The two spots are not identical

The two spots differ in two distinct ways, and the mount repair separates them cleanly.

**The prism spot is fainter**: against the clear aperture it delivers

| | prism | clear | ratio |
|---|---|---|---|
| `flux` | 194,646 | 278,088 | **0.716** |
| `peak` | 4,800 | 14,688 | 0.397 |
| `snr` | 96.5 | 125.4 | 0.779 |

A median throughput of 0.716 means the prism aperture loses about 30% of the light. The prism
aperture is the brighter one in 23.6% of frames, which is scintillation rather than any reversal of
the sign (see the frame-to-frame scatter below).

**The throughput is getting worse.** Regressing nightly throughput on date over the 266
well-sampled nights gives **-0.083 per year**, 95% confidence interval -0.099 to -0.068:

| Period | Nights | Nightly throughput |
|---|---|---|
| 2025 H1 | 68 | 0.796 |
| 2025 H2 | 87 | 0.744 |
| 2026 H1 | 84 | 0.709 |
| 2026 H2 | 27 | 0.685 |

So the loss has two parts: a floor set by the missing anti-reflection coatings, and a slowly
growing contribution consistent with dust settling on the prism. Condensation rides on top of both
as excursions rather than as trend. At this rate the prism sheds roughly 8 percentage points of
throughput a year, which is the figure to weigh against the risk of cleaning it. This is the rate
on the plateau: the SER cubes below show a much faster settling in the first months after
installation, which had already finished before this archive begins.

### The SER cubes confirm it independently

The archived SER cubes carry the same measurement back to the ASI432MM's commissioning in June
2023, through a different instrument mode and a different code path. `scripts/prism_throughput` was
run over the archives on three machines — this one, `auriga` and `vulpecula` — giving 310 rows over
207 distinct cubes. The three archives overlap heavily: 103 rows are the same cube held on more than
one machine. Those are a free reproducibility check, and they pass — every repeated cube returns the
same throughput to four decimal places on both machines. The only apparent disagreement is three
different files that happen to share the name `seeing.ser.gz`, which is why cubes are deduplicated
on the measurement, not on the filename.

After cutting cubes with fewer than 150 usable frames, no real two-spot separation, or a
scintillation index above 5, 142 remain, all of them dated. Full-frame cubes are then dropped as
well — see below — leaving 134 cubes over 20 dates:

| Date | Cubes | Throughput | Spread | Separation | Rate |
|---|---|---|---|---|---|
| 2023-06-22 | 13 | 0.936 | 0.012 | 48-52 px | 270 Hz |
| 2023-06-23 | 4 | 0.866 | 0.012 | 25-26 px | 271 Hz |
| 2023-06-24 | 8 | 0.861 | 0.014 | 24 px | 381 Hz |
| 2023-07-03 | 43 | 0.877 | 0.025 | 38-44 px | 300 Hz |
| 2023-12-08 | 30 | 0.795 | 0.041 | 47-48 px | 299 Hz |
| 2024-02-20 | 3 | 0.745 | 0.009 | 63-64 px | 299 Hz |
| 2024-02-23 | 2 | 0.789 | 0.014 | 63-64 px | 299 Hz |
| 2024-02-24 | 1 | 0.790 | - | 57 px | 299 Hz |
| 2024-03-25 | 1 | 0.733 | - | 61 px | - |
| 2024-04-11 | 5 | 0.733 | 0.019 | 45-49 px | 299 Hz |
| 2024-04-12 | 1 | 0.694 | - | 52 px | 299 Hz |
| 2024-04-13 | 1 | 0.726 | - | 53 px | 299 Hz |
| 2024-04-29 | 7 | 0.747 | 0.018 | 58-59 px | 299 Hz |
| 2024-04-30 | 3 | 0.733 | 0.017 | 60-61 px | 299 Hz |
| 2024-05-04 | 1 | 0.770 | - | 46 px | 299 Hz |
| 2024-05-05 | 5 | 0.750 | 0.032 | 46-50 px | 299 Hz |
| 2024-06-11 | 2 | 0.730 | 0.002 | 50 px | 300 Hz |
| 2024-06-17 | 2 | 0.750 | 0.006 | 52 px | 299 Hz |
| 2024-12-11 | 1 | 0.706 | - | 66 px | 299 Hz |
| 2024-12-13 | 1 | 0.739 | - | 54 px | 300 Hz |

The prism was passing about 94% of the clear aperture when it was commissioned and is now under
70%. Within any one night the spread is small — 0.012 across thirteen cubes on 2023-06-22 — so the
year-scale change is far larger than the measurement scatter.

Dates come from the cubes' own frame timestamps. They are UTC, matching `DATE-OBS` in the FITS
archive, so a cube taken after midnight SAST lands on the following date — which is why 2024-05-04
appears above for a cube whose filename says `2024-05-05T01:57+02:00`. Consistent between the two
datasets and irrelevant to epoch comparisons, but wrong if whole observing nights are ever wanted.

**The decline is not linear, and that is the main thing the extra dates buy.** With only three
points after commissioning the earlier fit gave -0.114 per year and predicted 0.524 for August 2026
against a measured 0.685, which was recorded here as unexplained over-extrapolation. The denser
series shows why. The throughput falls at **-0.304 per year over the first six months** and then at
**-0.056 per year** over the following year. Fitting all twenty dates with an exponential settling
onto a floor, weighted by the number of cubes per date, gives floor **0.691 ± 0.050**, amplitude
0.202, time constant **7.9 ± 3.6 months**, rms residual 0.024. That form predicts **0.692** for
August 2026 against a measured 0.685, where a single straight line through the same data predicts
0.461 and fits worse (rms 0.032).

So the shape is a fast settling in the first months after installation onto a floor near 0.69, plus
the slow residual drift of a few points a year that the single exposures measure independently as
-0.083 per year. The -0.114 per year quoted before was an average over a transient and a plateau and
describes neither. The time constant is the least certain part — 7.9 ± 3.6 months, and it moved from
4 to 8 months when five more dates arrived, because only the 2023-06 to 2023-12 gap constrains it.
Everything after that has settled: a further date added later moved the floor and the time constant
by less than the last digit quoted.

Three limits remain on how far this can be pushed:

**Full-frame cubes have to be excluded.** The eight 1608x1104 cubes read high and disagree between
aperture radii by 0.025, against 0.002 for the ROI cubes. They are saturating setup captures:
clipping the bright spot pushes the ratio toward unity, and the amount depends on the radius. This
retracts the 2025-03-11 point (0.704) used in the earlier version of this table — it was one such
cube, and its agreement with the trend was coincidence.

**The two datasets are still not on a common scale.** The SER series and the single exposures
cannot be merged into one fit, only compared as trends. With 2025-03-11 withdrawn there is no SER
cube contemporaneous with the single-exposure archive, so the size of the offset between methods is
not measured. The one candidate — `indi_2025-08-17@19-30-23` on `vulpecula`, the only archived cube
from the overlap period — is a full-frame setup capture that was cut off after 16 frames, so it
fails on all three counts. Closing this gap needs a deliberate ROI capture at the present epoch; it
is the single most useful cube anyone could take for these notes.

**The optics were changing during commissioning.** Spot separation runs 24 to 66 px across the
series, so the mask or the focal length moved several times. Restricting to the single most
populated configuration (separation 45-55 px, 61 cubes over 10 dates) gives -0.136 per year with a
95% interval of -0.230 to +0.040 — same picture, and the same non-linearity, but too few dates for
the slope alone to be worth much. Group by separation before comparing anything across dates.

Aperture radius is not driving any of this: on the dates with four or more cubes, r=11 and r=20
agree to within 0.023. The larger disagreements are all on single-cube dates.

The first pass over these archives left thirteen good cubes undated, because the survey took its
dates from the path and they sit at paths like `bad3.ser.gz` with no date in them. That was a defect
in the tool, since fixed — the SER `dateobs` field is written with a broken epoch, year 123 for a
2023 cube, but `dateobs_utc` and the per-frame timestamps are correct. The re-run above dates every
cube from its own timestamps, and the recovered ones added five dates through February to June 2024,
the stretch that most constrains the shape of the curve.

Two cubes also failed outright on that pass, on a header promising more frames than the file holds —
a capture interrupted part way through. The reader now keeps the whole frames that survive, which
recovered `last_good_seeing.ser.gz` as the 2024-03-25 point above: 2095 frames, 419 of them measured,
and no timestamp trailer, since that sits after the image data and is lost with it. Such cubes are
reported as `ok, truncated` and are worth including — their frames are ordinary, they just cover
less of the night than a whole cube would.

The pooled, deduplicated survey is kept at `~/SAAO/timdimm_data/throughput_pooled.ecsv`, one row per
distinct cube with the machine it came from. The per-machine TSVs it was built from are beside it.

**The prism spot is also fatter**: median FWHM ratio 1.57 (7.11 px against 4.32 px), and it is the
larger of the two in 96.4% of the 135,941 frames where both were measured. Far too consistent to be
seeing, which would average out between two apertures a few centimetres apart on the same night.
Candidate causes are aberration introduced by the extra optic, or scattering off the dust and the
poor coating — the same contamination that costs the throughput. The two mechanisms are not
distinguished here, though the repair below argues at least part of it is alignment.

The peak ratio of 0.397 is just the two effects compounding: about 30% less light spread over a
1.57x wider spot (area ratio ~2.5).

### The repair separates alignment from throughput

| Epoch | throughput prism/clear | FWHM ratio prism/clear |
|---|---|---|
| 1 | 0.735 | 1.647 |
| 2 | 0.702 | 1.657 |
| 3 (after the repair) | 0.679 | **1.347** |

**The two have different time signatures.** The size ratio *steps* at the reassembly, 1.65 to 1.35.
The throughput does not step: fitting nightly throughput with a trend plus a step at 2026-04-09
puts the step at -0.002, with a 95% interval of -0.030 to +0.027 that comfortably contains zero.
Its decline is continuous straight through the repair.

So the size difference is an alignment or focus state, disturbed by taking the system apart and put
back differently, while the throughput is a gradually accumulating property of the prism surface
that a disassembly neither helped nor hurt. That is what one expects if the size mismatch is
alignment and the light loss is coating plus dust.

Two things argue the throughput deficit is real rather than a measurement artifact. It holds per
target within every epoch — 0.65 to 0.78 across all 17 target/epoch combinations with more than 500
frames, spanning both gain settings and a wide range of stellar brightness. And the correlation
between log throughput and log FWHM ratio is only 0.24, so the deficit does not track the size
difference frame to frame, as it would if measuring a broader spot were what produced it.

Not yet ruled out: the local background annulus scales with the aperture, so the prism spot's
annulus sits farther out, and at a median separation of 52 px the two annuli stand in different
relation to the neighbouring spot. That mechanism is known to bite here — it distorted a synthetic
test during development. It would take a controlled check to exclude a few percent of
contamination, though it is hard to see it producing a stable 30%.

### Throughput as a condensation monitor

Because the prism is the surface that dews up, **the nightly trend in throughput detects
condensation directly**, and it is a much sharper signal than the nightly median suggests.

Frame to frame the ratio is very broad — 5th to 95th percentile 0.28 to 1.69, exceeding 1.0 in 24%
of frames. That is scintillation: two small apertures, 1 ms exposures, uncorrelated speckle. It
averages out. Per-night medians are stable at **0.727, 5th-95th percentile 0.608 to 0.850** across
the 266 nights with at least 100 frames. Between-night scatter of the medians is 0.092 against a
typical within-night scatter of 0.473, so the nightly median is the statistic that carries
information about the optics and single frames carry almost none.

Bad nights are unmistakable, and they decline monotonically through the night rather than sitting
at a low level:

| Night | throughput binned through the night |
|---|---|
| 2026-05-15 (normal) | 0.69 0.70 0.66 0.66 0.67 0.64 0.65 |
| 2025-10-26 | 0.77 0.72 0.62 0.34 **0.02** 0.01 0.01 — never recovers |
| 2026-04-27 | 0.65 0.60 0.46 0.15 **0.06** — over about 90 minutes |
| 2026-06-05 | 0.55 0.25 **0.06** 0.20 0.42 0.64 — dews over, then clears |
| 2026-07-20 | 0.66 0.61 0.36 0.46 0.64 0.30 **0.08** |

A normal night is flat to a few percent. The affected nights fall by more than an order of
magnitude, sometimes recovering when the dew clears.

### Dew costs frames, not accuracy

It is tempting to read the low-throughput frames as corrupted. They are not. **Seeing is measured
from centroids**, and a centroid is insensitive to how much light the spot has lost as long as the
spot is detected and centroided reliably. The archive says that holds comfortably even when the
prism is badly dewed:

| Night | throughput | median prism SNR | implied centroid sigma |
|---|---|---|---|
| 2026-05-15 (normal) | 0.663 | 61.7 | 0.038 px |
| 2026-07-20 | 0.483 | 38.2 | 0.060 px |
| 2026-06-05 | 0.333 | 43.6 | 0.045 px |
| 2025-10-26 | **0.055** | 31.3 | 0.067 px |

Even on the worst night in the archive the surviving prism detections centroid to better than a
tenth of a pixel, against differential motion of order a pixel. Archive-wide the prism spot falls
below SNR 20 in 2.45% of two-star frames, below SNR 10 in 0.32%, and below SNR 5 in 0.01%. Seeing
from these frames is fine.

**What dew actually costs is detections.** When the prism spot drops under the detection threshold
the frame yields no seeing measurement at all, and that is strongly driven by throughput:

| Night | throughput | single-star share of detections |
|---|---|---|
| 2026-05-15 (normal) | 0.663 | 3.2% |
| 2026-07-20 | 0.483 | 20.7% |
| 2026-06-05 | 0.333 | 45.1% |
| 2026-04-27 | 0.235 | **70.3%** |

Over the 266 well-sampled nights the correlation between nightly throughput and single-star share
is -0.35, and it is monotonic in bins: median single-star share is 5.3% on nights above 0.8
throughput, 7.5% between 0.6 and 0.8, 20.7% between 0.4 and 0.6, and 45% below 0.4.

So the practical effect of a dewed prism is a thinner night — fewer usable measurements, spread
unevenly through it — rather than biased ones. That makes nightly throughput useful as an
engineering signal and as a completeness statistic, but **not** as a quality cut on the seeing
values themselves.

**A dew heater is not an option.** The heat it puts into the light path would generate turbulence
and corrupt the seeing measurement, which defeats the purpose of the instrument.

The more promising route is a better safety check: **combine the flux ratio with the Adafruit
humidity sensor now attached to the system.** The existing rule closes at 90% RH, and the question
is whether condensation on the prism actually begins below that limit — the archive shows the
prism dewing on nights that were presumably inside the operating envelope. The throughput ratio
gives an independent, direct measurement of when the prism is dewing, so pairing it against logged
RH tests the limit rather than assuming it. This needs another month or two of data with the
Adafruit sensor running before it is worth analysing.

### The label swap as a consistency check

The figures above are computed **after** undoing the epoch 2 label swap. The swap is useful in its
own right, because it inverts every measure of the asymmetry at once:

| Epoch | `star0` fatter | median `star0_fwhm`/`star1_fwhm` | median `flux_ratio` |
|---|---|---|---|
| 1 | 98.1% | 1.65 | 0.73 |
| 2 | **2.0%** | **0.60** | **1.42** |
| 3 | 91.8% | 1.35 | 0.68 |

Epoch 2 inverts on both size and flux, and 1.42 is 1/0.70 — the same physical ratio read
backwards. Relabelled, epochs 1 and 2 give asymmetry ratios of 1.65 and 1.66, agreeing to within
1%, which is an independent check that the correction is right rather than fitted.

Median FWHM also differs between the two *camera* epochs (8.2 px against 6.2 px for `star0`), but
the target mix changed at the same moment, so that one is confounded and not attributable to
focus, seeing or the configuration change.

## Measurement quality

The photometry aperture radius is iterated onto `3*sigma_major` rather than fixed, because a fixed
aperture truncates a smeared spot along its long axis and biases the ellipticity low — and
elongation is a signal of interest.

Sizes are now essentially always recovered: FWHM is NaN in 0.23% of `star0` measurements and 0.05%
of `star1`. The remaining cases are genuinely marginal detections.

**About 13% of spots sit at the `MIN_APER_RADIUS` floor of 6 px.** `star1`'s median FWHM of 4.37 px
implies `3*sigma` of about 5.6 px, just under the floor, so for the sharper spot the aperture ends
up slightly larger than the intended fixed point rather than converged onto it. The direction is
harmless — a too-large aperture admits more sky but does not truncate the long axis — but those
rows are not strictly at `3*sigma`. Only 121 rows reach the 40 px ceiling. Lowering the floor
would need testing against real sharp spots first; the floor exists because very small apertures
made the second moments noisy.

## Caveats

**Tables built before commit `f62ba39` have invalid shape columns.** The aperture iteration started
at `3*DETECTION_FWHM` = 15 px, where a faint spot is mostly sky; the background-subtracted second
moments go negative there and photutils returns NaN axes. That aborted the iteration on its first
pass, so `fwhm`, `fwhm_gauss`, `sigma_major`, `sigma_minor`, `ellip` and `pa` were missing for
about 17% of two-star frames and biased roughly 5% low where they were present. `flux`, `snr`,
positions and `sep_pix` are unaffected. Regenerate rather than trusting an old table.

**Statistics from small subsets of this archive are biased**, because the frames the old code
succeeded on were preferentially the brighter, fatter spots. An earlier 636-entry sample put the
size ratio at 1.64 and the fatter-in fraction at 100%; the full archive, with the epoch 2 labels
corrected, gives 1.57 and 96.4%.

**Never aggregate `star0`/`star1` columns across the whole archive without splitting on epoch
first.** The labels refer to different physical apertures in epoch 2 than in 1 and 3, so a naive
archive-wide mean of any per-star column silently averages the two apertures together. The
uncorrected `star0`-fatter fraction is 90.9% against a true 96.4%, and any quantity that differs
between the apertures is diluted the same way.

**The frames themselves are gone.** `scripts/daily_cleanup` deletes each frame once it has been
measured, on the principle that everything worth keeping about a frame ends up in the table. The
table is therefore the only record, and is worth backing up off the acquisition machine.
