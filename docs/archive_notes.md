# Notes on the pre-seeing exposure archive

Working notes on the single exposures taken before each seeing measurement, and on what the
first full-archive run of `analyze_pictures` says about them. These are scratch notes kept so
the findings are not lost between sessions; they are meant to be folded into proper Sphinx
documentation later.

All numbers below come from a run over the whole archive on 2026-08-12, using the code at
commit `f62ba39` or later. Earlier tables are not comparable — see [Caveats](#caveats).

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
measurement failure.

Target counts are dominated by Sirius (44,169), Canopus (32,534), Achernar (25,445),
Spica (22,039) and Mimosa (20,077).

## Two camera configurations

**The camera settings changed exactly once in the archive, and both gain and offset moved
together.** There is a single transition and no night contains frames from both epochs, so the
archive splits cleanly on either date or gain.

| | Epoch 1 | Epoch 2 |
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
to do with the sky. Median `star0_flux` is 658,000 adu in epoch 1 against 64,000 in epoch 2.
Always group by gain before summarising a count-valued column.

**`bkg_median` is the offset pedestal, not sky.** It is *exactly* 1552 in every epoch-1 frame and
*exactly* 160 in every epoch-2 frame — the 5th and 95th percentiles are identical to the median.
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

| Epoch | Nights | Axis PA | Frames | Labels |
|---|---|---|---|---|
| B | 2025-01-01 to **2026-02-18** | 150.0 deg | 91,432 | as A |
| C | **2026-02-19** to 2026-03-09 | 71.7 deg | 7,733 | **swapped** |
| A | **2026-04-09** to 2026-08-08 | 103.9 deg | 36,943 | as B |

Both transitions are sharp — 2026-02-18 is entirely epoch B and the following night entirely
epoch C. There is no data between 2026-03-10 and 2026-04-08. Neither move coincides with the gain
change of 2025-10-30, which falls in the middle of epoch B: the camera settings and the camera
orientation were changed on separate occasions, so the two splits have to be applied
independently.

Spot separation is stable throughout at a median `sep_pix` of 52.2 px (5th-95th percentile 40.3 to
68.5), consistent with the mask geometry and unaffected by the rotations.

## The two spots are not identical

The two spots are the same star seen through two apertures of the DIMM mask, so in principle they
should have the same size. One is consistently much fatter than the other: **the same physical
aperture gives the larger spot in 96.4% of the 135,941 frames where both were measured**, with a
median FWHM ratio of 1.57 (7.11 px against 4.32 px). The effect is far too consistent to be
seeing, which would average out between two apertures a few centimetres apart on the same night.
A focus difference between the mask apertures is the obvious candidate. It has not been chased
down.

That figure is computed **after** undoing the epoch C label swap. The swap is what makes the
asymmetry a useful check on the labelling, because it inverts every measure of it at once:

| Epoch | `star0` fatter | median `star0_fwhm`/`star1_fwhm` | median `flux_ratio` |
|---|---|---|---|
| B | 98.1% | 1.65 | 0.73 |
| C | **2.0%** | **0.60** | **1.42** |
| A | 91.8% | 1.35 | 0.68 |

Epoch C inverts on both size and flux, and 1.42 is 1/0.70 — the same physical ratio read
backwards. Relabelled, epochs B and C give asymmetry ratios of 1.65 and 1.66, agreeing to within
1%, which is an independent check that the correction is right rather than fitted.

**Epoch A's asymmetry is genuinely weaker** (1.35 against 1.65), and it is not a labelling
artifact. Epoch A begins after the month-long gap in spring 2026, and the axis moved 30 degrees at
the same time, so a refocus or realignment during that shutdown would explain both. Median FWHM
also differs between the two *camera* epochs (8.2 px against 6.2 px for `star0`), but the target
mix changed at the same moment, so that one is confounded and not attributable to focus, seeing or
the configuration change.

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
size ratio at 1.64 and the fatter-in fraction at 100%; the full archive, with the epoch C labels
corrected, gives 1.57 and 96.4%.

**Never aggregate `star0`/`star1` columns across the whole archive without splitting on epoch
first.** The labels refer to different physical apertures in epoch C than in A and B, so a naive
archive-wide mean of any per-star column silently averages the two apertures together. The
uncorrected `star0`-fatter fraction is 90.9% against a true 96.4%, and any quantity that differs
between the apertures is diluted the same way.

**The frames themselves are gone.** `scripts/daily_cleanup` deletes each frame once it has been
measured, on the principle that everything worth keeping about a frame ends up in the table. The
table is therefore the only record, and is worth backing up off the acquisition machine.
