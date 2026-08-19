def test_set_gain_and_offset(monkeypatch):
    from timdimm_tng.indi import INDI_Camera
    calls = []
    cam = INDI_Camera("ZWO CCD ASI432MM")
    monkeypatch.setattr(cam, "set_prop", lambda p, k, value=None: calls.append((p, k, value)))
    cam.set_gain(200)
    cam.set_offset(1)
    assert calls == [("CCD_CONTROLS", "Gain", 200), ("CCD_CONTROLS", "Offset", 1)]
