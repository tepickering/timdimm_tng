# Design: analyze_pictures

## Problem

Before each seeing measurement a single exposure is taken and written to
`~/Pictures/<target>/Light/<target>_Light_NNN.fits`. Nothing analyzes these frames. They
carry a nightly record of image quality — background level, spot brightness, spot size,
spot elongation — that would let us tell a bad night from a bad pointing, or find the
onset of a tracking problem, without re-reducing the SER cubes.

The script runs twice over its life: once in batch over the archive (`.fits.gz`), then
daily on the previous night's uncompressed `.fits`.

## Data

Frames from a ZWO ASI432MM on a Meade LX200: 1608x1104 uint16, 9 um pixels, 2500 mm focal
length, `SCALE = 0.7427` arcsec/pixel. Exposures are 1 ms, so the frame is essentially all
background apart from the two spots produced by the DIMM mask, which sit ~50 px apart and
are often visibly streaked.

`Pictures/` is flat: target, then image type, then files. There are **no per-night
directories**, so night boundaries come from `DATE-OBS`.

## Output

One row per image, wide. Columns:

- **Provenance:** `filename` (path relative to root), `target` (directory name), `night`
- **Header subset** (the 13 keywords in `header.txt`): `EXPTIME`, `CCD-TEMP`, `AIRMASS`,
  `OBJCTAZ`, `OBJCTALT`, `RA`, `DEC`, `PIERSIDE`, `EQUINOX`, `DATE-OBS`, `GAIN`, `OFFSET`,
  `OBJECT`, lower-cased and with `-` mapped to `_`
- **Background:** `bkg_median`, `bkg_rms`, `bkg_mean`
- **Detector:** `egain` (e- per stored count), `bitshift`, `snr_method`
- **Per star**, for `star0` and `star1`: `x`, `y`, `peak`, `flux`, `snr`, `fwhm`,
  `fwhm_gauss`, `sigma_major`, `sigma_minor`, `ellip`, `pa`, `sharpness`, `concentration`,
  `fit_ok`
- **Per image:** `n_stars`, `sep_pix`, `sep_arcsec`, `sep_pa`, `flux_ratio`, `status`

ECSV by default so units and column descriptions travel with the table; `--format csv`
drops them.

### Star labelling

`star0` and `star1` are assigned by **x centroid, ascending** — a positional label, not an
aperture identity. The camera orientation changed at some point in the archive, so the
mapping from position to mask aperture is not constant over the dataset. `flux_ratio`
(`star0_flux / star1_flux`) and `sep_pa` are recorded so the aperture assignment can be
recovered in later analysis without reprocessing the images. Nothing in this script tries
to infer it.

## Components

### `find_images(root, night=None, since=None)`

Walks `root/<target>/<imagetype>/*.fits` and `*.fits.gz`, reads headers only, returns
`(path, header)` pairs. A night runs local noon to local noon at the site — longitude from
`SITELONG`, falling back to the SAAO location in `locations.py` — and is labelled by its
starting date. `--last-night` is the daily-cron form.

### `measure_background(data)`

`sigma_clipped_stats` with detected sources masked. Returns median, RMS and mean. At 1 ms
the frame is almost entirely background, so this is well constrained.

### `measure_stars(data, bkg_rms)`

`DAOStarFinder` at ~10 sigma, keep the two brightest, sort by x centroid. Per star:

- circular aperture photometry, radius ~3x a first-pass moment width, with a local annulus
  background, giving total flux
- `peak` from the brightest pixel inside the aperture
- windowed second moments giving `sigma_major`, `sigma_minor`,
  `fwhm = 2.355 * sqrt(sigma_major * sigma_minor)`, `ellip = 1 - b/a`, and `pa` of the
  major axis
- a 2D elliptical Gaussian fit (`astropy.modeling`) giving `fwhm_gauss` and `fit_ok`; the
  fit is a cross-check, and its disagreement with the moment FWHM is itself a smear
  indicator, which is why a symmetric fit alone was rejected
- `concentration`: `peak / flux` normalized to the diffraction-limited value, reusing the
  strehl expression already in `analyze_cube.moments()`
- `sharpness` from DAOStarFinder

### Gain and SNR

`GAIN = 350` is the ZWO gain *index* in units of 0.1 dB, not e-/ADU, but the ASI432MM
response is known well enough to convert it.

**Bit depth.** The IMX432 ADC is 12-bit and the driver left-shifts by 4 into uint16: every
pixel value in the archived frames is a multiple of 16. The script **detects the shift**
rather than assuming it — the greatest power of two dividing every pixel value, capped at
16 — so a driver change that stops shifting does not silently corrupt the gain scaling. The
detected value is stored as `bitshift`.

**eGain.** Unity gain for the ASI432MM is at index 272, giving

```
egain_12bit = 10 ** ((272 - gain) / 200)      # e-/ADU at 12-bit
egain       = egain_12bit / bitshift          # e- per stored count
```

Cross-checks against ZWO's published curves: at gain 0 this gives 22.9 e-/ADU against a
plotted intercept of 23.7, which is itself `FW / 2**12 = 97000 / 4096 = 23.68` — so the
functional form is right and the 272 anchor reproduces it to 3%. At gain 350 it gives 0.407
e-/ADU_12, under which ZWO's quoted ~3.0 e- read noise becomes 118 stored counts; the
measured background RMS in the archived frames is 100 counts, consistent with read noise
plus a small sky contribution.

**SNR.** With `egain` in hand, the CCD equation applies directly. `bkg_rms` already
contains read noise and sky, so converting it to electrons gives the per-pixel background
noise without needing them separately:

```
flux_e = flux * egain
sigma_bkg_e = bkg_rms * egain
snr = flux_e / sqrt(flux_e + n_pix * sigma_bkg_e**2)
```

**Fallback.** The 272 anchor is specific to the ASI432MM, so it is applied only when
`INSTRUME` matches that camera. For any other camera the script falls back to the
background-limited `flux / (bkg_rms * sqrt(n_pix))`, leaves `egain` as NaN, and records
which form was used in a `snr_method` column, so mixed-camera tables stay interpretable.

### `analyze_image(path, header)`

Combines the above into one row. **Never raises.** A frame with zero or one detection
yields a row with `n_stars` set, NaNs elsewhere, and a `status` string, so bad frames stay
in the table rather than disappearing from it — a night with no detections must be
distinguishable from a night that was not processed.

## CLI

```
analyze_pictures --root ~/Pictures --all -o archive.ecsv
analyze_pictures --night 2025-10-09 -o nightly.ecsv
analyze_pictures --last-night --append master.ecsv
```

`--append` merges into an existing table and de-duplicates on `filename`, so re-running a
night is idempotent.

## Testing

TDD against synthetic frames built with `astropy.modeling`, where the expected values are
known exactly:

- a round Gaussian pair at known separation, flux and noise: asserts flux, FWHM,
  separation, background, SNR
- an elongated pair: asserts `ellip`, `pa`, and that `concentration` falls relative to the
  round case
- a blank frame: asserts the no-detection path produces a row, not an exception
- a single-star frame: asserts the one-detection path
- night-boundary selection across local noon, including a frame either side
- gain conversion: `egain` at index 272 is 1.0 e-/ADU_12, at index 0 is within 5% of 23.7,
  bit-shift detection returns 16 for shifted data and 1 for unshifted, and a non-ASI432MM
  `INSTRUME` takes the background-limited fallback

The five archived Achernar frames are a smoke test that the pipeline runs end to end on
real data. They are not a source of assertions, since their true values are unknown.

## Out of scope

- Inferring which mask aperture produced which spot (see *Star labelling*)
- Common-mode elongation between the two spots. `pa` is stored per star so it can be
  derived later, but it is not computed here.
- Any change to the SER-cube path in `analyze_cube.py`
