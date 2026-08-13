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

## Spot properties

The two spots are the same star seen through two apertures of the DIMM mask, so in principle they
should be identical. They are not.

**`star0` is measurably fatter than `star1`**: median FWHM 6.96 px against 4.37 px, a ratio of
1.54, and `star0` is the larger one in 90.9% of the 135,941 frames where both were measured. The
effect is far too consistent to be seeing, which would average out between two apertures a few
centimetres apart on the same night. It is most likely a focus difference between the two mask
apertures, or a genuine optical asymmetry. It has not been chased down.

`star0` and `star1` are **x-sorted positional labels, not mask-aperture identities** — the camera
orientation changed at some point during the archive, so the same physical aperture is not
necessarily `star0` throughout. `flux_ratio` and `sep_pa` are recorded so the assignment can be
recovered downstream. Any analysis of the size asymmetry needs to establish which label
corresponds to which aperture in the epoch it is looking at.

Median FWHM also differs between the two camera epochs (8.2 px against 6.2 px for `star0`). The
target mix changed at the same time, so this is not yet attributable to focus, seeing, or the
configuration change.

Spot separation is stable at a median `sep_pix` of 52.2 px (5th-95th percentile 40.3 to 68.5),
consistent with the mask geometry.

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
`star0`/`star1` size ratio at 1.64 and the fatter-in fraction at 100%; the full archive gives 1.54
and 90.9%.

**The frames themselves are gone.** `scripts/daily_cleanup` deletes each frame once it has been
measured, on the principle that everything worth keeping about a frame ends up in the table. The
table is therefore the only record, and is worth backing up off the acquisition machine.
