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

## The open problem: the cubes may not resolve the scintillation

This is the question the spec has to answer first, because it may need a change to acquisition
rather than to analysis.

Measured from `indi_record_2023-06-22@17-14-39.ser`:

| | |
|---|---|
| Frames | 2268 |
| Duration | 51.8 s |
| Cadence | 22.9 ms median, **43.7 Hz** |
| Cadence jitter | std 1.5 ms; 92% of intervals within 10% of the median |

**The flux ratio is already decorrelated at one frame of lag.** Autocorrelation of the per-frame
ratio for lags 1 to 6 came out `[-0.014, -0.012, -0.020, 0.012, -0.000, 0.100]` — consistent with
zero. So the scintillation time constant is shorter than the 22.9 ms sampling interval and cannot
be measured from these cubes at all.

That is the expected order of magnitude: the wind crossing time of a 50 mm aperture at 10 m/s is
about 5 ms, so several hundred Hz would be needed to resolve it. Image motion is slower, typically
tens of milliseconds, so its time constant may be measurable at 43.7 Hz — but marginally, and that
needs checking rather than assuming.

Caveat on the number above: it came from a quick pass with **fixed** apertures rather than the
pipeline's per-frame recentering, and only 551 of 2268 frames had both apertures usable, because
image motion carries the spots out of a fixed aperture. The lag-1 decorrelation is unlikely to be
an artifact of that, but it should be redone properly through `dimm_calc()` before the spec relies
on it.

**The cadence is also not uniform**, which rules out a naive FFT or an autocorrelation on frame
index. Either resample onto a uniform grid, or use an estimator that takes the timestamps —
a structure function, or a Lomb-Scargle periodogram.

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
  model? The reference papers should settle this rather than a choice made here.
- **Can the current cubes support it at all?** If not: raise the frame rate (at what cost to SNR
  and to the seeing measurement?), or log only what is measurable and record the limit.
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
