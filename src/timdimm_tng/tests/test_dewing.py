"""
Tests for the dewing closure protocol.

The protocol has three parts: a humidity warning zone that only logs, a closure on the prism
throughput collapsing, and a reopening hold that needs both humidity sensors dry for a sustained
period. The hold is the part with state, so most of the cases are about it resetting properly.
"""

import json
import tempfile
import unittest
from datetime import UTC, datetime, timedelta
from pathlib import Path

from timdimm_tng.scintillation import CLOSURE_THROUGHPUT, SEVERE_CONDENSATION_THROUGHPUT
from timdimm_tng.wx.dewing import (
    DEW_WARNING_HUMIDITY,
    REOPEN_DRY_PERIOD,
    REOPEN_HUMIDITY,
    THROUGHPUT_MAX_AGE,
    DewingState,
    Throughput,
    clear_state,
    humidity_is_warning,
    latest_throughput,
    load_state,
    save_state,
    throughput_requires_closure,
    update_reopen,
)


NOW = datetime(2026, 9, 8, 1, 30, tzinfo=UTC)


def test_the_warning_zone_starts_at_80_percent():
    assert DEW_WARNING_HUMIDITY == 80.0
    assert not humidity_is_warning(79.9)
    assert humidity_is_warning(80.0)
    assert humidity_is_warning(85.1)


def test_closure_sits_between_the_severe_band_and_the_warning_band():
    # 0.2 is above the 0.1 severe band: the roof closes before the prism is passing a tenth of its light
    assert CLOSURE_THROUGHPUT == 0.2
    assert CLOSURE_THROUGHPUT > SEVERE_CONDENSATION_THROUGHPUT


def test_a_fresh_collapsed_throughput_closes():
    reading = Throughput(value=0.16, target="Achernar", timestamp=NOW - timedelta(minutes=1))
    assert throughput_requires_closure(reading, now=NOW)


def test_the_closure_threshold_is_inclusive():
    reading = Throughput(value=CLOSURE_THROUGHPUT, target="Achernar", timestamp=NOW)
    assert throughput_requires_closure(reading, now=NOW)


def test_a_warning_band_throughput_does_not_close():
    # 0.31 is what Achernar read on 2026-08-31 after a reopening with the prism still wet
    reading = Throughput(value=0.31, target="Achernar", timestamp=NOW)
    assert not throughput_requires_closure(reading, now=NOW)


def test_a_stale_throughput_does_not_close():
    # the last cube before a closure is exactly the kind of reading that must not keep re-closing
    reading = Throughput(value=0.05, target="Canopus", timestamp=NOW - THROUGHPUT_MAX_AGE - timedelta(seconds=1))
    assert not throughput_requires_closure(reading, now=NOW)


def test_a_missing_throughput_does_not_close():
    assert not throughput_requires_closure(None, now=NOW)
    nan = Throughput(value=float("nan"), target="Canopus", timestamp=NOW)
    assert not throughput_requires_closure(nan, now=NOW)


class TestLatestThroughput(unittest.TestCase):
    def setUp(self):
        self.tmp_dir = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp_dir.name) / "scintillation.csv"

    def tearDown(self):
        self.tmp_dir.cleanup()

    def test_the_last_complete_row_is_parsed(self):
        self.path.write_text(
            "time,target,throughput,scint_index_raw\n"
            "2026-09-08T01:29:00.000,Achernar,0.6300,0.1\n"
            "2026-09-08T01:29:40.000,Achernar,0.1455,0.1\n"
            "2026-09-08T01:30:20.000,Ach"
        )
        reading = latest_throughput(self.path)
        self.assertEqual(reading.value, 0.1455)
        self.assertEqual(reading.target, "Achernar")
        self.assertEqual(reading.timestamp, datetime(2026, 9, 8, 1, 29, 40, tzinfo=UTC))

    def test_a_missing_file_gives_nothing(self):
        self.assertIsNone(latest_throughput(self.path))

    def test_an_unparseable_row_gives_nothing(self):
        self.path.write_text("time,target,throughput\nnot-a-time,Achernar,junk\n")
        self.assertIsNone(latest_throughput(self.path))


class TestReopenHold(unittest.TestCase):
    def setUp(self):
        self.state = DewingState(closed_at=NOW, throughput=0.16, target="Achernar")

    def test_the_hold_needs_both_sensors_at_or_below_75(self):
        assert REOPEN_HUMIDITY == 75.0
        state, reopen = update_reopen(self.state, salt_humidity=75.0, sht45_humidity=75.0, now=NOW)
        self.assertEqual(state.dry_since, NOW)
        self.assertFalse(reopen)

    def test_one_wet_sensor_keeps_the_clock_off(self):
        state, reopen = update_reopen(self.state, salt_humidity=60.0, sht45_humidity=75.1, now=NOW)
        self.assertIsNone(state.dry_since)
        self.assertFalse(reopen)

    def test_reopening_takes_20_dry_minutes(self):
        assert REOPEN_DRY_PERIOD == timedelta(minutes=20)
        state, _ = update_reopen(self.state, salt_humidity=60.0, sht45_humidity=70.0, now=NOW)
        later = NOW + timedelta(minutes=19, seconds=58)
        state, reopen = update_reopen(state, salt_humidity=60.0, sht45_humidity=70.0, now=later)
        self.assertFalse(reopen)
        self.assertEqual(state.dry_since, NOW)              # the clock keeps its original start
        state, reopen = update_reopen(state, salt_humidity=60.0, sht45_humidity=70.0, now=NOW + timedelta(minutes=20))
        self.assertTrue(reopen)

    def test_a_wet_reading_restarts_the_clock(self):
        state, _ = update_reopen(self.state, salt_humidity=60.0, sht45_humidity=70.0, now=NOW)
        state, _ = update_reopen(state, salt_humidity=76.0, sht45_humidity=70.0, now=NOW + timedelta(minutes=15))
        self.assertIsNone(state.dry_since)
        again = NOW + timedelta(minutes=16)
        state, reopen = update_reopen(state, salt_humidity=60.0, sht45_humidity=70.0, now=again)
        self.assertEqual(state.dry_since, again)
        self.assertFalse(reopen)

    def test_a_missing_sensor_counts_as_wet(self):
        # an invalid SALT feed or a stale SHT45 cannot vouch for dry air
        state, _ = update_reopen(self.state, salt_humidity=60.0, sht45_humidity=70.0, now=NOW)
        state, reopen = update_reopen(state, salt_humidity=None, sht45_humidity=70.0, now=NOW + timedelta(minutes=25))
        self.assertIsNone(state.dry_since)
        self.assertFalse(reopen)
        state, reopen = update_reopen(state, salt_humidity=60.0, sht45_humidity=None, now=NOW + timedelta(minutes=26))
        self.assertIsNone(state.dry_since)
        self.assertFalse(reopen)


class TestStateFile(unittest.TestCase):
    def setUp(self):
        self.tmp_dir = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp_dir.name) / "DEWING"

    def tearDown(self):
        self.tmp_dir.cleanup()

    def test_state_round_trips_through_json(self):
        state = DewingState(closed_at=NOW, throughput=0.16, target="Achernar", dry_since=NOW + timedelta(minutes=5))
        save_state(state, self.path)
        self.assertEqual(load_state(self.path), state)
        # status.py runs every couple of seconds; the file is what carries the hold between runs
        self.assertEqual(json.loads(self.path.read_text())["target"], "Achernar")

    def test_no_file_means_no_hold(self):
        self.assertIsNone(load_state(self.path))

    def test_a_corrupt_file_means_no_hold(self):
        # a torn write must not wedge the roof shut or open for good; it just drops the hold
        self.path.write_text("{")
        self.assertIsNone(load_state(self.path))

    def test_clearing_removes_the_file(self):
        save_state(DewingState(closed_at=NOW, throughput=0.16, target="Achernar"), self.path)
        clear_state(self.path)
        self.assertFalse(self.path.exists())
        clear_state(self.path)                              # already gone is fine
