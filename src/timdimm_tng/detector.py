"""
Convert ZWO camera gain indices into e-/ADU.

ZWO report gain as an index in units of 0.1 dB, not as a conversion factor, so eGain falls
by a factor of 10 every 200 index counts. For the ASI432MM (IMX432) the curve is anchored at
its gain-0 intercept, 97000 e- of full well over a 12-bit ADC, which is where ZWO's own EGAIN
and full-well panels agree with each other. That puts unity gain at index 274.9 rather than
the 272 they publish; the 1% offset buys agreement with the plotted curve at every other gain.
"""

import numpy as np

#: full well of the IMX432 in electrons, from ZWO's published curves
ASI432_FULL_WELL = 97000.0

#: ADC bit depth of the IMX432
ASI432_ADC_BITS = 12

#: e-/ADU at gain index 0, referenced to 12-bit ADU
ASI432_EGAIN_0 = ASI432_FULL_WELL / 2**ASI432_ADC_BITS

#: the driver left-shifts 12-bit samples into uint16, so counts are multiples of 16
MAX_BITSHIFT = 16


def asi432_egain(gain_index):
    """
    eGain of an ASI432MM in e-/ADU at 12-bit, for a ZWO gain index in units of 0.1 dB.
    """
    return ASI432_EGAIN_0 * 10.0 ** (-gain_index / 200.0)


def detect_bitshift(data):
    """
    Return the power-of-two factor the data has been left-shifted by, capped at MAX_BITSHIFT.

    The IMX432 is a 12-bit sensor whose samples are left-shifted into uint16, so every count is
    a multiple of 16. This is detected rather than assumed: if a driver update ever stops
    shifting, assuming a shift would inflate every derived electron count by 16x.
    """
    values = np.asarray(data).astype(np.int64).ravel()
    nonzero = values[values != 0]
    if nonzero.size == 0:
        return 1
    shift = 1
    while shift < MAX_BITSHIFT and np.all(nonzero % (shift * 2) == 0):
        shift *= 2
    return shift


def egain_from_header(header, data):
    """
    Work out e- per stored count from a FITS header and its data.

    Returns (egain, bitshift, snr_method). The ASI432MM calibration above is the only one we
    have, so any other camera returns NaN and signals that the caller should fall back to a
    background-limited SNR rather than a CCD-equation one.
    """
    bitshift = detect_bitshift(data)
    instrument = str(header.get("INSTRUME", "")).upper()
    gain = header.get("GAIN")
    if "ASI432" not in instrument or gain is None:
        return float("nan"), bitshift, "background"
    return asi432_egain(float(gain)) / bitshift, bitshift, "ccd"
