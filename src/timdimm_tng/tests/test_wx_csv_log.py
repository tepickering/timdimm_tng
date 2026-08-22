"""
Tests for the weather CSV logger.

The two live readings embedded here were captured from the real feeds on 2026-08-22, so the
fixtures exercise the shapes the stations actually serve -- a null ``cloud``, arrays that must not
reach the file, and a SAST timestamp that is two hours ahead of the ``time`` column beside it.
"""

import datetime

import pytest

from timdimm_tng.wx.csv_log import (
    SAAO_IO_COLUMNS,
    SALT_COLUMNS,
    DEDUP_EXCLUDED,
    HEARTBEAT_SECONDS,
    ensure_header,
    format_row,
    last_logged_fields,
    log_reading,
    saao_io_row,
    salt_row,
)


LIVE_SAAO_IO = {
    "timestamp": "2026-08-22T21:53:07",
    "tmtdew": 5.74, "humidity": 66.79, "cloud": None, "wind": 19.37, "temperature": 6.83,
    "tmtdew_warn": 0, "humidity_warn": 0, "rain_warn": 0, "cloud_warn": None,
    "wind_warn": 0, "temperature_warn": 0,
    "seeing_timestamp": "2026-08-22T21:53:04", "seeing": 1.75,
    "atlas_timestamp": "2026-08-22T19:52:54.192", "atlas_cloud": 1, "atlas_rain": 1,
    "zp_data": [-0.10625, -0.04975], "zp_timestamp": "2026-08-22T21:52:00",
    "zp_ref_data": [], "zp_ref_timestamp": "None",
    "wind_dir": 157.29, "air_pressure": 833.68,
    "Valid": True,
}

LIVE_SALT = {
    "bms_validity": 511,
    "DateTime": "2026-08-22_21:53:00.0",
    "Bar_Press": 8336.8, "DewTemp": 1.09, "Rel_Hum": 66.8,
    "Wind_speed": 69.7, "Wind_dir": 157.3, "Temp": 6.8, "Rain": 0,
    "TimeStamp_SAST": datetime.datetime(2026, 8, 22, 21, 53, 0),
    "Open": True, "SkyCon": "DRY", "Valid": True,
}


def _lines(path):
    return path.read_text().splitlines()


# ---------------------------------------------------------------- row building


def test_saao_io_row_keeps_the_station_clock_separate_from_the_log_time():
    row = saao_io_row(LIVE_SAAO_IO, "2026-08-22T19:53:10.000")
    assert row["time"] == "2026-08-22T19:53:10.000"
    assert row["timestamp_sast"] == "2026-08-22T21:53:07"


def test_saao_io_row_drops_the_arrays_and_the_atlas_fields():
    row = saao_io_row(LIVE_SAAO_IO, "2026-08-22T19:53:10.000")
    assert set(row) == set(SAAO_IO_COLUMNS)
    for dropped in ("zp_data", "zp_ref_data", "zp_timestamp", "atlas_cloud", "atlas_rain"):
        assert dropped not in row


def test_saao_io_row_drops_the_seeing_we_measured_ourselves():
    # IO's seeing field is timdimm's own value fed back to us, ~26 s stale: 112 of the 116 rows
    # logged on 2026-08-22 appear verbatim in our seeing.csv. Logging it here would archive the
    # same measurement twice and invite it being mistaken for an independent check.
    row = saao_io_row(LIVE_SAAO_IO, "2026-08-22T19:53:10.000")
    assert "seeing" not in row
    assert "seeing_timestamp" not in row


def test_salt_row_uses_the_parsed_sast_datetime():
    row = salt_row(LIVE_SALT, "2026-08-22T19:53:10.000")
    assert set(row) == set(SALT_COLUMNS)
    assert row["timestamp_sast"] == "2026-08-22T21:53:00"
    assert row["Wind_speed"] == 69.7
    assert row["SkyCon"] == "DRY"


def test_salt_row_writes_the_shutter_state_as_a_bool():
    assert salt_row(LIVE_SALT, "2026-08-22T19:53:10.000")["Open"] is True
    assert salt_row(dict(LIVE_SALT, Open=False), "2026-08-22T19:53:10.000")["Open"] is False


# ---------------------------------------------------------------- formatting


def test_format_row_applies_fixed_precision():
    line = format_row({"a": 1.23456, "b": "x"}, ("a", "b"), {"a": 2})
    assert line == "1.23,x\n"


def test_format_row_writes_a_missing_value_as_an_empty_field():
    line = format_row({"a": None, "b": 3}, ("a", "b", "c"), {})
    assert line == ",3,\n"


def test_format_row_does_not_apply_precision_to_a_missing_value():
    # a None under a precision entry must not raise on the format spec
    assert format_row({"a": None}, ("a",), {"a": 2}) == "\n"


def test_the_live_saao_io_reading_formats_without_raising():
    row = saao_io_row(LIVE_SAAO_IO, "2026-08-22T19:53:10.000")
    line = format_row(row, SAAO_IO_COLUMNS, {})
    assert len(line.rstrip("\n").split(",")) == len(SAAO_IO_COLUMNS)


# ---------------------------------------------------------------- header


def test_ensure_header_creates_the_file(tmp_path):
    path = tmp_path / "wx.csv"
    ensure_header(path, "a,b\n")
    assert path.read_text() == "a,b\n"


def test_ensure_header_leaves_a_matching_file_alone(tmp_path):
    path = tmp_path / "wx.csv"
    path.write_text("a,b\n1,2\n")
    ensure_header(path, "a,b\n")
    assert path.read_text() == "a,b\n1,2\n"


def test_ensure_header_rotates_a_file_whose_columns_changed(tmp_path):
    path = tmp_path / "wx.csv"
    path.write_text("a,b\n1,2\n")
    ensure_header(path, "a,b,c\n")
    assert path.read_text() == "a,b,c\n"
    rotated = [p for p in tmp_path.iterdir() if p.name.startswith("wx.csv.")]
    assert len(rotated) == 1
    assert rotated[0].read_text() == "a,b\n1,2\n"


def test_ensure_header_does_not_clobber_an_earlier_rotation(tmp_path):
    path = tmp_path / "wx.csv"
    path.write_text("a\n1\n")
    ensure_header(path, "a,b\n")
    path.write_text("a,b\n2,3\n")
    ensure_header(path, "a,b,c\n")
    rotated = sorted(p for p in tmp_path.iterdir() if p.name.startswith("wx.csv."))
    assert len(rotated) == 2


# ---------------------------------------------------------------- dedup


def test_last_logged_fields_is_none_for_a_header_only_file(tmp_path):
    path = tmp_path / "wx.csv"
    ensure_header(path, "time,timestamp_sast\n")
    assert last_logged_fields(path) is None


def test_last_logged_fields_is_none_for_a_missing_file(tmp_path):
    assert last_logged_fields(tmp_path / "nope.csv") is None


def test_last_logged_fields_reads_the_final_row(tmp_path):
    path = tmp_path / "wx.csv"
    path.write_text("time,timestamp_sast\nA,1\nB,2\n")
    assert last_logged_fields(path) == ["B", "2"]


def test_last_logged_fields_survives_a_partial_final_line(tmp_path):
    # a row half-written when the machine went down must not poison every later comparison
    path = tmp_path / "wx.csv"
    path.write_text("time,timestamp_sast\nA,1\nB")
    assert last_logged_fields(path) is None


def test_only_the_two_clock_columns_are_excluded_from_the_dedup_key():
    # everything that is not one of our two clocks is part of the reading, Valid included
    assert DEDUP_EXCLUDED == ("time", "timestamp_sast")


# ---------------------------------------------------------------- log_reading


def _log(path, wx, now="2026-08-22T19:53:10.000"):
    return log_reading(path, wx, saao_io_row, SAAO_IO_COLUMNS, now)


def test_log_reading_writes_a_first_row(tmp_path):
    path = tmp_path / "saao_io.csv"
    assert _log(path, LIVE_SAAO_IO) is True
    lines = _lines(path)
    assert lines[0] == ",".join(SAAO_IO_COLUMNS)
    assert len(lines) == 2


def test_log_reading_skips_a_repeat_of_the_same_reading(tmp_path):
    path = tmp_path / "saao_io.csv"
    _log(path, LIVE_SAAO_IO)
    assert _log(path, LIVE_SAAO_IO, now="2026-08-22T19:53:12.000") is False
    assert len(_lines(path)) == 2


def test_log_reading_skips_a_reading_whose_only_change_is_the_station_clock(tmp_path):
    # the whole point: SALT republishes its XML every 5 s while the BMS underneath it updates
    # once a minute, so an advanced station clock over identical measurements is not a new reading
    path = tmp_path / "saao_io.csv"
    _log(path, LIVE_SAAO_IO)
    ticked = dict(LIVE_SAAO_IO, timestamp="2026-08-22T21:53:12")
    assert _log(path, ticked, now="2026-08-22T19:53:15.000") is False
    assert len(_lines(path)) == 2


def test_log_reading_writes_again_once_a_measurement_changes(tmp_path):
    path = tmp_path / "saao_io.csv"
    _log(path, LIVE_SAAO_IO)
    gust = dict(LIVE_SAAO_IO, timestamp="2026-08-22T21:54:07", wind=24.11)
    assert _log(path, gust, now="2026-08-22T19:54:10.000") is True
    assert len(_lines(path)) == 3


def test_log_reading_writes_when_only_valid_changes(tmp_path):
    # a station going stale under unchanged numbers is exactly the transition worth recording
    path = tmp_path / "saao_io.csv"
    _log(path, LIVE_SAAO_IO)
    assert _log(path, dict(LIVE_SAAO_IO, Valid=False), now="2026-08-22T19:53:40.000") is True


def test_log_reading_compares_formatted_values_not_raw_ones(tmp_path):
    # the file stores two decimals, so a change below that is not visible in it and must not
    # produce a row that looks identical to the one above it
    path = tmp_path / "saao_io.csv"
    _log(path, LIVE_SAAO_IO)
    jitter = dict(LIVE_SAAO_IO, temperature=LIVE_SAAO_IO["temperature"] + 0.0001)
    assert _log(path, jitter, now="2026-08-22T19:53:40.000") is False


def test_log_reading_writes_a_heartbeat_once_the_interval_passes(tmp_path):
    # value dedup alone makes a frozen station indistinguishable from steady conditions, which is
    # the one failure this log exists to catch, so an unchanged reading still lands eventually
    path = tmp_path / "saao_io.csv"
    first = datetime.datetime(2026, 8, 22, 19, 53, 10)
    _log(path, LIVE_SAAO_IO, now=first.isoformat())
    early = first + datetime.timedelta(seconds=HEARTBEAT_SECONDS - 1)
    assert _log(path, LIVE_SAAO_IO, now=early.isoformat()) is False
    due = first + datetime.timedelta(seconds=HEARTBEAT_SECONDS)
    assert _log(path, LIVE_SAAO_IO, now=due.isoformat()) is True


def test_the_heartbeat_row_carries_the_current_clocks(tmp_path):
    path = tmp_path / "saao_io.csv"
    _log(path, LIVE_SAAO_IO, now="2026-08-22T19:53:10.000")
    ticked = dict(LIVE_SAAO_IO, timestamp="2026-08-22T21:59:07")
    _log(path, ticked, now="2026-08-22T19:59:10.000")
    row = dict(zip(SAAO_IO_COLUMNS, _lines(path)[-1].split(",")))
    assert row["time"] == "2026-08-22T19:59:10.000"
    assert row["timestamp_sast"] == "2026-08-22T21:59:07"


def test_log_reading_writes_when_the_log_clock_goes_backwards(tmp_path):
    # a clock correction must not be able to suppress readings until it catches up again
    path = tmp_path / "saao_io.csv"
    _log(path, LIVE_SAAO_IO, now="2026-08-22T19:53:10.000")
    assert _log(path, LIVE_SAAO_IO, now="2026-08-22T18:00:00.000") is True


def test_log_reading_writes_when_the_last_log_time_is_unreadable(tmp_path):
    path = tmp_path / "saao_io.csv"
    _log(path, LIVE_SAAO_IO)
    lines = _lines(path)
    fields = lines[-1].split(",")
    fields[0] = "not-a-time"
    path.write_text("\n".join(lines[:-1] + [",".join(fields)]) + "\n")
    assert _log(path, LIVE_SAAO_IO, now="2026-08-22T19:53:12.000") is True


def test_log_reading_skips_a_reading_with_no_station_timestamp(tmp_path):
    path = tmp_path / "saao_io.csv"
    assert _log(path, {"Valid": False}) is False
    assert not path.exists()


def test_log_reading_skips_a_reading_missing_a_required_field(tmp_path):
    path = tmp_path / "saao_io.csv"
    incomplete = {k: v for k, v in LIVE_SAAO_IO.items() if k != "wind"}
    assert _log(path, incomplete) is False
    assert not path.exists()


def test_log_reading_still_records_a_stale_reading_and_marks_it(tmp_path):
    # check_wx clears Valid for a clock offset outside 120 +/- 10 minutes as well as for an
    # unreachable station. A stale reading is real data, so it is logged with Valid=False rather
    # than dropped, which is what keeps a clock skew from silently ending the weather record.
    path = tmp_path / "saao_io.csv"
    assert _log(path, dict(LIVE_SAAO_IO, Valid=False)) is True
    row = dict(zip(SAAO_IO_COLUMNS, _lines(path)[1].split(",")))
    assert row["Valid"] == "False"


def test_log_reading_rotates_when_the_columns_change(tmp_path):
    path = tmp_path / "saao_io.csv"
    _log(path, LIVE_SAAO_IO)
    log_reading(path, LIVE_SAAO_IO, saao_io_row, SAAO_IO_COLUMNS[:-1], "2026-08-22T19:54:00.000")
    assert _lines(path)[0] == ",".join(SAAO_IO_COLUMNS[:-1])
    assert any(p.name.startswith("saao_io.csv.") for p in tmp_path.iterdir())


def test_log_reading_handles_salt_too(tmp_path):
    path = tmp_path / "salt_wx.csv"
    assert log_reading(path, LIVE_SALT, salt_row, SALT_COLUMNS, "2026-08-22T19:53:10.000") is True
    assert log_reading(path, LIVE_SALT, salt_row, SALT_COLUMNS, "2026-08-22T19:53:15.000") is False


def test_log_reading_skips_salt_when_only_the_xml_publish_clock_ticks(tmp_path):
    # TimeStamp_SAST comes from tcs_xml_time_info__timestamp -- when the TCS published the XML,
    # not when the BMS took the reading. On 2026-08-22 that inflated an hour of SALT from 72 real
    # readings to 844 rows.
    path = tmp_path / "salt_wx.csv"
    log_reading(path, LIVE_SALT, salt_row, SALT_COLUMNS, "2026-08-22T19:53:10.000")
    republished = dict(LIVE_SALT, TimeStamp_SAST=datetime.datetime(2026, 8, 22, 21, 53, 5))
    assert log_reading(path, republished, salt_row, SALT_COLUMNS, "2026-08-22T19:53:15.000") is False
    assert len(_lines(path)) == 2


def test_log_reading_skips_salt_when_the_bms_is_invalid(tmp_path):
    path = tmp_path / "salt_wx.csv"
    assert log_reading(path, {"Valid": False}, salt_row, SALT_COLUMNS, "2026-08-22T19:53:10.000") is False
    assert not path.exists()


def test_columns_lead_with_time_then_the_station_clock():
    for columns in (SAAO_IO_COLUMNS, SALT_COLUMNS):
        assert columns[0] == "time"
        assert columns[1] == "timestamp_sast"


@pytest.mark.parametrize("columns", [SAAO_IO_COLUMNS, SALT_COLUMNS])
def test_no_column_contains_a_comma(columns):
    assert not any("," in column for column in columns)
