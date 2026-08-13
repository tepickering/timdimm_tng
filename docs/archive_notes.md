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

## The two spots are not identical

The two spots are the same star seen through two apertures of the DIMM mask, so in principle they
should match. They differ in two distinct ways, and the mount repair separates the two cleanly.

**One spot is much fatter**: the same physical aperture gives the larger spot in 96.4% of the
135,941 frames where both were measured, median FWHM ratio 1.57 (7.11 px against 4.32 px). The
effect is far too consistent to be seeing, which would average out between two apertures a few
centimetres apart on the same night.

**The fatter spot is also the fainter one** — not what a naive reading would predict, and the more
interesting of the two findings. Against the sharp aperture the fat one delivers:

| | fat aperture | thin aperture | ratio |
|---|---|---|---|
| `flux` | 194,646 | 278,088 | **0.716** |
| `peak` | 4,800 | 14,688 | 0.397 |
| `snr` | 96.5 | 125.4 | 0.779 |

The fat aperture is brighter in only 23.6% of frames. The peak ratio is roughly what spreading the
same light over a 1.57x wider spot would give (area ratio ~2.5), so that part is just defocus —
but **total flux is not conserved, and it should be.** The photometry radius is iterated onto
`3*sigma`, so it grows with the spot and captures ~99% of a gaussian either way. The fat aperture
is genuinely passing about 30% less light.

### The repair separates focus from throughput

| Epoch | flux ratio fat/thin | FWHM ratio fat/thin |
|---|---|---|
| 1 | 0.735 | 1.647 |
| 2 | 0.702 | 1.657 |
| 3 (after the repair) | 0.679 | **1.347** |

**The size ratio changed when the system was reassembled; the flux ratio did not.** Two independent
effects, then. The size difference is an alignment or focus state — disturbed by taking the system
apart and putting it back together. The throughput difference survived a full disassembly, which
points at the mask itself: unequal aperture areas, or one aperture partly obstructed or vignetted.
That would make it a fixed property of the optics rather than something a realignment can fix.

Two things argue the flux deficit is real rather than a measurement artifact. It holds per target
within every epoch — 0.65 to 0.78 across all 17 target/epoch combinations with more than 500
frames, spanning both gain settings and a wide range of stellar brightness. And the correlation
between log flux ratio and log FWHM ratio is only 0.24, so the deficit does not track the size
difference frame to frame, as it would if measuring a broader spot were what produced it.

Not yet ruled out: the local background annulus scales with the aperture, so the fat spot's annulus
sits farther out, and at a median separation of 52 px the two annuli stand in different relation to
the neighbouring spot. That mechanism is known to bite here — it distorted a synthetic test during
development. It would take a controlled check to exclude a few percent of contamination, though it
is hard to see it producing a stable 30%.

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
