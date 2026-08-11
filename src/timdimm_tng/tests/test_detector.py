import numpy as np
import pytest

from timdimm_tng.detector import ASI432_EGAIN_0, asi432_egain, detect_bitshift, egain_from_header


def test_egain_at_gain_zero_is_the_full_well_intercept():
    # 97000 e- full well over a 12-bit ADC
    assert asi432_egain(0) == pytest.approx(97000 / 2**12, rel=1e-6)
    assert ASI432_EGAIN_0 == pytest.approx(23.68, abs=0.01)


def test_egain_crosses_unity_near_index_275():
    # 0.1 dB per index step, so egain falls by 10x every 200 index counts
    assert asi432_egain(274.9) == pytest.approx(1.0, rel=0.01)
    assert asi432_egain(200) / asi432_egain(400) == pytest.approx(10.0, rel=1e-6)


def test_egain_at_operational_gain_350():
    assert asi432_egain(350) == pytest.approx(0.421, abs=0.002)


def test_detect_bitshift_finds_the_four_bit_left_shift():
    rng = np.random.default_rng(0)
    twelve_bit = rng.integers(0, 4096, size=(64, 64))
    assert detect_bitshift(twelve_bit * 16) == 16


def test_detect_bitshift_returns_one_for_unshifted_data():
    rng = np.random.default_rng(0)
    # random 16-bit data is not uniformly divisible by 2
    assert detect_bitshift(rng.integers(0, 65536, size=(64, 64))) == 1


def test_detect_bitshift_caps_at_sixteen():
    # data that happens to be divisible by 64 must still report at most 16
    rng = np.random.default_rng(0)
    assert detect_bitshift(rng.integers(0, 1024, size=(64, 64)) * 64) == 16


def test_egain_from_header_uses_the_ccd_equation_for_the_asi432():
    rng = np.random.default_rng(0)
    data = rng.integers(0, 4096, size=(64, 64)) * 16
    header = {"INSTRUME": "ZWO CCD ASI432MM", "GAIN": 350}
    egain, bitshift, method = egain_from_header(header, data)
    assert bitshift == 16
    assert method == "ccd"
    # e- per stored count is the 12-bit egain divided by the shift
    assert egain == pytest.approx(0.421 / 16, abs=1e-4)


def test_egain_from_header_falls_back_for_an_unknown_camera():
    rng = np.random.default_rng(0)
    data = rng.integers(0, 4096, size=(64, 64)) * 16
    header = {"INSTRUME": "Some Other Camera", "GAIN": 350}
    egain, bitshift, method = egain_from_header(header, data)
    assert np.isnan(egain)
    assert method == "background"


def test_egain_from_header_falls_back_when_gain_is_missing():
    rng = np.random.default_rng(0)
    data = rng.integers(0, 4096, size=(64, 64)) * 16
    egain, _, method = egain_from_header({"INSTRUME": "ZWO CCD ASI432MM"}, data)
    assert np.isnan(egain)
    assert method == "background"
