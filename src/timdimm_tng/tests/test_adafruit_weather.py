import tempfile
import unittest
from datetime import UTC, datetime, timedelta
from pathlib import Path

from timdimm_tng.wx.adafruit import (
    Measurement,
    humidity_is_safe,
    latest_humidity,
    latest_measurement,
    measurement_is_stale,
    measurement_requires_closure,
)


class TestAdafruitWeather(unittest.TestCase):
    def setUp(self):
        self.tmp_dir = tempfile.TemporaryDirectory()
        self.log_path = Path(self.tmp_dir.name) / "adafruit.csv"

    def tearDown(self):
        self.tmp_dir.cleanup()

    def test_latest_humidity_uses_final_nonempty_row(self):
        self.log_path.write_text(
            "timestamp_utc,temperature_c,relative_humidity_percent\n"
            "2026-07-15T09:59:54.000Z,21.4,89.9\n"
            "2026-07-15T09:59:57.000Z,21.3,90.0\n"
            "\n"
        )

        self.assertEqual(latest_humidity(self.log_path), 90.0)

    def test_latest_measurement_parses_utc_timestamp(self):
        self.log_path.write_text("2026-07-15T09:59:57.000Z,21.3,89.9\n")

        measurement = latest_measurement(self.log_path)

        self.assertEqual(measurement.timestamp, datetime(2026, 7, 15, 9, 59, 57, tzinfo=UTC))
        self.assertEqual(measurement.humidity, 89.9)

    def test_humidity_at_limit_is_unsafe(self):
        self.assertTrue(humidity_is_safe(89.9))
        self.assertFalse(humidity_is_safe(90.0))

    def test_header_without_measurement_is_invalid(self):
        self.log_path.write_text("timestamp_utc,temperature_c,relative_humidity_percent\n")

        with self.assertRaisesRegex(ValueError, "Invalid Adafruit timestamp"):
            latest_humidity(self.log_path)

    def test_non_finite_humidity_is_invalid(self):
        self.log_path.write_text("2026-07-15T09:59:57.000Z,21.3,nan\n")

        with self.assertRaisesRegex(ValueError, "Invalid Adafruit humidity"):
            latest_humidity(self.log_path)

    def test_timestamp_without_timezone_is_invalid(self):
        self.log_path.write_text("2026-07-15T09:59:57.000,21.3,89.9\n")

        with self.assertRaisesRegex(ValueError, "timestamp has no timezone"):
            latest_measurement(self.log_path)

    def test_measurement_older_than_ten_minutes_is_stale(self):
        now = datetime(2026, 7, 15, 10, 10, tzinfo=UTC)

        self.assertFalse(measurement_is_stale(now - timedelta(minutes=10), now=now))
        self.assertTrue(measurement_is_stale(now - timedelta(minutes=10, seconds=1), now=now))

    def test_only_current_high_humidity_requires_closure(self):
        now = datetime(2026, 7, 15, 10, 10, tzinfo=UTC)
        current_high = Measurement(timestamp=now - timedelta(minutes=10), humidity=90.0)
        stale_high = Measurement(timestamp=now - timedelta(minutes=10, seconds=1), humidity=95.0)

        self.assertTrue(measurement_requires_closure(current_high, now=now))
        self.assertFalse(measurement_requires_closure(stale_high, now=now))


if __name__ == "__main__":
    unittest.main()
