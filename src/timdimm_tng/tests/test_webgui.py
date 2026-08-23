"""
Tests for the web GUI's CSV readers and the conditions endpoint.

The GUI reads the tail of files that are being appended to live, so the cases that matter are the
degenerate ones: a file that does not exist yet, one holding only a header, and one whose last line
is half written. None of those may raise -- the page has to keep rendering.
"""

import tempfile
import unittest
from datetime import UTC, datetime, timedelta
from pathlib import Path

from timdimm_tng import webgui


class TestLastCsvRow(unittest.TestCase):
    def setUp(self):
        self.tmp_dir = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp_dir.name) / "test.csv"

    def tearDown(self):
        self.tmp_dir.cleanup()

    def test_the_last_row_comes_back_keyed_by_column(self):
        self.path.write_text("time,target,throughput\na,Atria,0.69\nb,Achernar,0.34\n")

        self.assertEqual(
            webgui._last_csv_row(self.path),
            {"time": "b", "target": "Achernar", "throughput": "0.34"},
        )

    def test_a_missing_file_is_not_an_error(self):
        self.assertIsNone(webgui._last_csv_row(self.path))

    def test_a_header_only_file_has_no_row(self):
        self.path.write_text("time,target,throughput\n")

        self.assertIsNone(webgui._last_csv_row(self.path))

    def test_an_empty_file_has_no_row(self):
        self.path.write_text("")

        self.assertIsNone(webgui._last_csv_row(self.path))

    def test_a_half_written_final_line_is_skipped_for_the_one_before_it(self):
        # the loggers append while the page polls, so a torn final line is expected, not exotic
        self.path.write_text("time,target,throughput\na,Atria,0.69\nb,Ach")

        self.assertEqual(webgui._last_csv_row(self.path)["throughput"], "0.69")

    def test_a_torn_line_with_nothing_before_it_has_no_row(self):
        self.path.write_text("time,target,throughput\nb,Ach")

        self.assertIsNone(webgui._last_csv_row(self.path))


class TestConditions(unittest.TestCase):
    def setUp(self):
        self.tmp_dir = tempfile.TemporaryDirectory()
        self.tmp = Path(self.tmp_dir.name)
        self.sht45 = self.tmp / "adafruit.csv"
        self.scint = self.tmp / "scintillation.csv"
        self._saved = (webgui.ADAFRUIT_FILE, webgui.SCINTILLATION_FILE)
        webgui.ADAFRUIT_FILE, webgui.SCINTILLATION_FILE = self.sht45, self.scint
        self.now = datetime(2026, 8, 22, 22, 30, tzinfo=UTC)

    def tearDown(self):
        webgui.ADAFRUIT_FILE, webgui.SCINTILLATION_FILE = self._saved
        self.tmp_dir.cleanup()

    def write_sht45(self, age_minutes, temperature="6.41", humidity="76.3"):
        stamp = (self.now - timedelta(minutes=age_minutes)).isoformat().replace("+00:00", "Z")
        self.sht45.write_text(
            "timestamp_utc,temperature_c,relative_humidity_percent\n"
            f"{stamp},{temperature},{humidity}\n"
        )

    def write_throughput(self, age_minutes, value="0.686", target="Achernar"):
        stamp = (self.now - timedelta(minutes=age_minutes)).replace(tzinfo=None).isoformat()
        self.scint.write_text(
            "time,target,throughput\n"
            f"{stamp},{target},{value}\n"
        )

    def test_a_fresh_sht45_reading_is_reported(self):
        self.write_sht45(age_minutes=0)

        sht45 = webgui._conditions(now=self.now)["sht45"]

        self.assertEqual(sht45["temperature"], 6.41)
        self.assertEqual(sht45["humidity"], 76.3)
        self.assertFalse(sht45["stale"])

    def test_an_old_sht45_reading_is_marked_stale(self):
        self.write_sht45(age_minutes=11)

        self.assertTrue(webgui._conditions(now=self.now)["sht45"]["stale"])

    def test_the_sht45_staleness_limit_matches_the_closure_check(self):
        # the same 10 minutes status.py uses to decide the sensor is not worth acting on
        self.write_sht45(age_minutes=9)
        self.assertFalse(webgui._conditions(now=self.now)["sht45"]["stale"])

    def test_a_missing_sht45_log_reports_nothing_rather_than_failing(self):
        self.assertIsNone(webgui._conditions(now=self.now)["sht45"])

    def test_a_clean_throughput_is_ok(self):
        self.write_throughput(age_minutes=0, value="0.686")

        throughput = webgui._conditions(now=self.now)["throughput"]

        self.assertEqual(throughput["value"], 0.686)
        self.assertEqual(throughput["level"], "ok")
        self.assertEqual(throughput["target"], "Achernar")

    def test_a_dewing_throughput_warns(self):
        self.write_throughput(age_minutes=0, value="0.34")

        self.assertEqual(webgui._conditions(now=self.now)["throughput"]["level"], "warning")

    def test_a_collapsed_throughput_is_severe(self):
        self.write_throughput(age_minutes=0, value="0.08")

        self.assertEqual(webgui._conditions(now=self.now)["throughput"]["level"], "severe")

    def test_an_old_throughput_is_marked_stale(self):
        self.write_throughput(age_minutes=16)

        self.assertTrue(webgui._conditions(now=self.now)["throughput"]["stale"])

    def test_a_throughput_from_the_last_cube_is_not_stale(self):
        # cubes land every ~40 s while observing, but gaps of several minutes are normal
        self.write_throughput(age_minutes=14)

        self.assertFalse(webgui._conditions(now=self.now)["throughput"]["stale"])

    def test_an_unparseable_throughput_reports_no_level(self):
        self.write_throughput(age_minutes=0, value="")

        throughput = webgui._conditions(now=self.now)["throughput"]

        self.assertIsNone(throughput["value"])
        self.assertIsNone(throughput["level"])

    def test_the_endpoint_serves_both_readings(self):
        from fastapi.testclient import TestClient

        self.write_sht45(age_minutes=0)
        self.write_throughput(age_minutes=0, value="0.34")

        with TestClient(webgui.app) as client:
            payload = client.get("/api/conditions").json()

        self.assertEqual(payload["sht45"]["humidity"], 76.3)
        self.assertEqual(payload["throughput"]["level"], "warning")


class TestSeeingFormatting(unittest.TestCase):
    def setUp(self):
        self.tmp_dir = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp_dir.name) / "seeing.csv"
        self._saved = webgui.SEEING_FILE
        webgui.SEEING_FILE = self.path

    def tearDown(self):
        webgui.SEEING_FILE = self._saved
        self.tmp_dir.cleanup()

    def latest(self, exptime):
        self.path.write_text(
            "time,target,seeing,airmass,azimuth,exptime\n"
            f"2026-08-23T03:44:11.868,Canopus,1.234,1.298,175.5,{exptime}\n"
        )
        return webgui._read_seeing_csv()[0]

    def test_seeing_is_shown_to_two_decimals(self):
        self.assertEqual(self.latest("0.001")["seeing"], '1.23"')

    def test_airmass_is_shown_to_two_decimals(self):
        self.assertEqual(self.latest("0.001")["airmass"], "1.30")

    def test_a_sub_millisecond_exposure_keeps_its_digit(self):
        # Canopus runs at 0.5 ms, which rounded to "0 ms" before
        self.assertEqual(self.latest("0.0005")["exptime"], "0.5 ms")

    def test_a_one_millisecond_exposure_still_reads_cleanly(self):
        self.assertEqual(self.latest("0.001")["exptime"], "1.0 ms")


if __name__ == "__main__":
    unittest.main()


class TestPageMarkup(unittest.TestCase):
    """
    The page is a string constant, so an edit that misses its target fails silently: the endpoint
    still serves, the tests still pass, and the card simply is not there. These assert the wiring.
    """

    def test_the_page_has_a_conditions_card(self):
        self.assertIn('id="conditions-table"', webgui.HTML_PAGE)

    def test_the_conditions_card_sits_above_the_seeing_chart(self):
        self.assertLess(
            webgui.HTML_PAGE.index('id="conditions-table"'),
            webgui.HTML_PAGE.index('id="seeing-chart"'),
        )

    def test_the_page_polls_the_conditions_endpoint(self):
        self.assertIn("/api/conditions", webgui.HTML_PAGE)
        self.assertIn("setInterval(fetchConditions", webgui.HTML_PAGE)

    def test_the_page_styles_both_severity_bands(self):
        self.assertIn("td.val.warn", webgui.HTML_PAGE)
        self.assertIn("td.val.alert", webgui.HTML_PAGE)
        self.assertIn("td.val.stale", webgui.HTML_PAGE)
