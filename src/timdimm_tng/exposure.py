"""
Camera gain, offset and the acquisition exposure ladder.

The ASI432MM runs at a fixed GAIN 200 / OFFSET 1. Those have been in use for a long time and the
calibration continuity is worth more than the headroom a lower gain would buy, so the *exposure* is
what varies with target brightness. Until 2026-08 they were set by hand through the INDI control
panel or the KStars/Ekos capture panel and nothing recorded what they were; they are pinned here and
written into ``scintillation.csv`` instead.

Two exposures, two jobs
-----------------------
The **probe** is a short full-frame cube whose only job is to locate the two apertures and read the
faint one's peak. It runs long, at ``PROBE_EXPTIME`` = 5 ms, on purpose: the long integration
averages over scintillation and buys signal-to-noise when cloud has attenuated the target, which is
exactly when the apertures are hardest to find. Bright targets clip it and that is fine -- a
saturated star still centroids well enough to place a 400x400 ROI around a 43-pixel baseline, and
Sirius ran this way before without trouble. Nothing photometric is taken from the probe.

The **science** cube defaults to 1 ms. That is the number the ladder below moves around, and it
moves for one reason: non-linearity, not saturation.

Why the science exposure is a ladder
------------------------------------
The ADC is 12-bit and the driver left-shifts by 4, so full scale is 4095 ADU_12 (65520 stored). At
1 ms Canopus's clear aperture peaks near 1028 ADU_12, a quarter of full scale, and its measured
throughput ratio sits systematically high -- ``d ln(throughput) / d ln(flux)`` of 0.0284 +/- 0.0041
over the range 2.9% to 25% of full scale, with no knee. Sirius joins the schedule around 2026-09 at
0.72 mag brighter (a factor 1.94) and would sit twice as deep into that curve. Shortening the
exposure walks the brightest targets back down it.

Going shorter is cheap. Image motion has a correlation time of 6-11 ms measured on sky, and that
estimate is diluted by noise in the direction that *shortens* it, so even 2-3 ms exposures sit well
inside the regime that freezes the image. Photometrically Sirius at 0.25 ms still carries ~13800 e-
in the faint aperture, better than Fomalhaut or Shaula manage at 1 ms today. The 299 Hz cadence is
set by ROI readout rather than by exposure, so none of this moves ``dt``.

The tier boundaries
-------------------
Bounds are the faint (prism) aperture's peak pixel in **stored counts on the probe cube**, at
``PROBE_EXPTIME`` and ``CAMERA_GAIN``. The faint spot is the one read because it is the one that
stays unclipped longest; the bright spot is expected to saturate on the probe. Expected readings,
scaled from a peak/aperture-sum ratio of 0.0599 measured directly on ``20260816_3.ser.gz``:

    Shaula 4380, Mimosa 5850, Fomalhaut 6260, Achernar 12980, Canopus 37830, Sirius >50000

which the ladder maps to 1 ms for the first four, 0.5 ms for Canopus and 0.25 ms for Sirius. Sirius
is bright enough to clip even the faint spot on a 5 ms probe, so it reads the full-scale 65520 and
lands on the top rung by pinning rather than by measurement -- the right direction to fail, since
anything that saturates the probe's faint aperture wants the shortest science exposure available.

The bottom rung is the pre-existing cloud fallback, kept at its original value: an attenuated target
lengthens to 2 ms rather than being measured at poor signal.

One systematic this creates. A finite exposure depresses the scintillation index by
``(tau**2 / 6) * V2U`` (Kornilov 2011 Eq. 4); at the measured ``f_c`` of roughly 600 Hz that is 0.4%
at 0.25 ms, 1.5% at 0.5 ms, 6% at 1 ms and **24% at 2 ms**. ``scint_index_raw`` is therefore not
comparable across tiers without correcting for it, which is why ``exptime`` is logged beside it.
"""

#: ZWO gain index, in units of 0.1 dB. Not a conversion factor -- see ``gain_scale``.
CAMERA_GAIN = 200

#: Black level. Low, but measured pixel histograms run smoothly down to 1 ADU_12 without piling up
#: at zero, so it does not clip.
CAMERA_OFFSET = 1

#: 12-bit ADC left-shifted by 4 into uint16: every stored value is a multiple of 16.
FULL_SCALE_ADU12 = 4095
ADU_SHIFT = 16
FULL_SCALE_COUNTS = FULL_SCALE_ADU12 * ADU_SHIFT

#: Exposure of the full-frame cube used to locate the two apertures. Long deliberately: it averages
#: over scintillation and carries signal-to-noise through cloud, which is when the apertures are
#: hardest to find. Bright targets clip it and that is intended -- see the module docstring.
PROBE_EXPTIME = 0.005

#: DAOfind-style detection cut for the probe, in units of the image's standard deviation -- so it
#: tracks signal-to-noise, not counts, and only means what it says at ``PROBE_EXPTIME``. Held at the
#: value the 5 ms probe has always used. Briefly shortening the probe to 1 ms in 2026-08 divided
#: every target's significance by five and put the fainter half of the schedule under this cut while
#: the spots were still obvious by eye; the exposure is the thing that has to stay put, not the cut.
PROBE_THRESHOLD = 35.0

#: ``(upper bound on the faint spot's probe peak, exposure to use)``, ascending, open-ended at the
#: top. A reading below a bound takes that rung, so the bounds read as strict ``<``.
EXPOSURE_LADDER = (
    (1500, 0.002),
    (20000, 0.001),
    (50000, 0.0005),
    (None, 0.00025),
)


def gain_scale(gain, reference=CAMERA_GAIN):
    """
    How much brighter a given gain reads than the reference, in raw counts.

    ZWO's ``GAIN`` is an index in units of 0.1 dB applied to the analogue chain, so counts scale as
    ``10 ** (gain / 200)``. Gain is pinned today, but the ladder's bounds are raw counts and are
    meaningless at another gain: at GAIN 140 every reading halves, and an unscaled 1500-count bound
    would drop lightly attenuated targets into the 2 ms fallback purely because the gain moved.
    """
    return 10 ** ((gain - reference) / 200)


def select_exptime(faint_peak, gain=CAMERA_GAIN):
    """
    Choose the science exposure from the faint aperture's peak on the probe cube.

    Parameters
    ----------
    faint_peak : float
        Peak pixel of the *fainter* of the two apertures, in stored counts, measured on the probe
        cube taken at ``PROBE_EXPTIME``.
    gain : int
        The gain the probe was taken at, used to scale the bounds. Defaults to the pinned
        ``CAMERA_GAIN``.

    Returns
    -------
    float
        Exposure time in seconds, one of the rungs of ``EXPOSURE_LADDER``.
    """
    scale = gain_scale(gain)
    for bound, exptime in EXPOSURE_LADDER:
        if bound is None or faint_peak < bound * scale:
            return exptime
