"""
Camera gain, offset and the acquisition exposure ladder.

The ASI432MM runs at a fixed GAIN 200 / OFFSET 1. Those have been in use for a long time and the
calibration continuity is worth more than the headroom a lower gain would buy, so the *exposure* is
what varies with target brightness. Until 2026-08 they were set by hand through the INDI control
panel or the KStars/Ekos capture panel and nothing recorded what they were; they are pinned here and
written into ``scintillation.csv`` instead.

Why a ladder rather than one exposure
-------------------------------------
The ADC is 12-bit and the driver left-shifts by 4, so full scale is 4095 ADU_12 (65520 stored). At
1 ms Canopus's clear aperture peaks near 1028 ADU_12, a quarter of full scale, and scintillation
gives a 2.85x median-to-max excursion frame to frame, so its brightest frames already reach ~72%.
Sirius joins the schedule around 2026-09 at 0.72 mag brighter (a factor 1.94) and would reach 139%
of full scale on those frames -- hard saturation, which destroys the centroid as well as the flux.

Going shorter is cheap. Image motion has a correlation time of 6-11 ms measured on sky, and that
estimate is diluted by noise in the direction that *shortens* it, so even 2-3 ms exposures sit well
inside the regime that freezes the image. Photometrically Sirius at 0.25 ms still carries ~13800 e-
in the faint aperture, better than Fomalhaut or Shaula manage at 1 ms today. The 299 Hz cadence is
set by ROI readout rather than by exposure, so none of this moves ``dt``.

The tier boundaries
-------------------
Bounds are the faint (prism) aperture's peak pixel in **stored counts** on the probe cube, at
``PROBE_EXPTIME`` and ``CAMERA_GAIN``. The faint spot is the one measured because the probe must
stay unsaturated to be read at all, and it is the dimmer of the two. Expected readings, scaled from
a peak/aperture-sum ratio of 0.0599 measured directly on ``20260816_3.ser.gz``:

    Shaula 876, Mimosa 1170, Fomalhaut 1252, Achernar 2596, Canopus 7566, Sirius 14672

which the ladder maps to 1 ms for the first four, 0.5 ms for Canopus and 0.25 ms for Sirius. The
bottom rung is the pre-existing cloud fallback: an attenuated target lengthens to 2 ms rather than
being measured at poor signal.

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

#: Exposure of the short full-frame cube used to locate the two apertures. Was 5 ms, which put
#: Canopus's bright spot at ~5140 ADU_12 against a 4095 full scale -- clipped on every Canopus cube,
#: unnoticed because the threshold below reads the *faint* spot. Sirius would have clipped both.
PROBE_EXPTIME = 0.001

#: ``(upper bound on the faint spot's probe peak, exposure to use)``, ascending, open-ended at the
#: top. A reading below a bound takes that rung, so the bounds read as strict ``<``.
EXPOSURE_LADDER = (
    (300, 0.002),
    (4000, 0.001),
    (10000, 0.0005),
    (None, 0.00025),
)


def gain_scale(gain, reference=CAMERA_GAIN):
    """
    How much brighter a given gain reads than the reference, in raw counts.

    ZWO's ``GAIN`` is an index in units of 0.1 dB applied to the analogue chain, so counts scale as
    ``10 ** (gain / 200)``. Gain is pinned today, but the ladder's bounds are raw counts and are
    meaningless at another gain: at GAIN 140 every reading halves, and an unscaled 300-count bound
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


def probe_peak_headroom(bright_peak):
    """
    Factor by which the probe's brightest pixel sits below full scale.

    Below 1.0 the probe is clipping and the centroid it yields is built on a flat-topped PSF. Used
    to log a warning rather than to change behaviour: a saturated probe still locates the apertures
    well enough to be worth continuing with, it just should not pass silently.
    """
    if bright_peak <= 0:
        return float("inf")
    return FULL_SCALE_COUNTS / bright_peak
