import csv
import tempfile
import unittest
from pathlib import Path

from scripts.log_adafruit import CSV_HEADER, log_measurements, parse_measurement


class FakeSerial:
    def __init__(self, lines):
        self.lines = iter(lines)

    def readline(self):
        try:
            return next(self.lines)
        except StopIteration:
            raise KeyboardInterrupt


class TestLogAdafruit(unittest.TestCase):
    def test_parse_measurement(self):
        cases = [
            ("21.4, 37.2\r\n", (21.4, 37.2)),
            (" -5.0 , 100.0 ", (-5.0, 100.0)),
            ("Current mode is: No Heat, High Precision", None),
            ("", None),
            ("nan, 45.0", None),
        ]
        for line, expected in cases:
            with self.subTest(line=line):
                self.assertEqual(parse_measurement(line), expected)

    def test_log_measurements_writes_header_and_skips_startup_text(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            output_path = Path(tmp_dir) / "adafruit.csv"
            serial_port = FakeSerial([b"Current mode is: No Heat, High Precision\r\n", b"\r\n", b"21.4, 37.2\r\n"])

            with self.assertRaises(KeyboardInterrupt):
                log_measurements(serial_port, output_path, timestamp_factory=lambda: "2026-07-15T19:00:00.000Z")

            with output_path.open(newline="") as output_file:
                self.assertEqual(
                    list(csv.reader(output_file)),
                    [
                        list(CSV_HEADER),
                        ["2026-07-15T19:00:00.000Z", "21.4", "37.2"],
                    ],
                )

    def test_log_measurements_appends_without_repeating_header(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            output_path = Path(tmp_dir) / "adafruit.csv"
            output_path.write_text("timestamp_utc,temperature_c,relative_humidity_percent\n")
            serial_port = FakeSerial([b"22.0, 38.0\n"])

            with self.assertRaises(KeyboardInterrupt):
                log_measurements(serial_port, output_path, timestamp_factory=lambda: "2026-07-15T19:00:03.000Z")

            self.assertEqual(
                output_path.read_text().splitlines(),
                [
                    "timestamp_utc,temperature_c,relative_humidity_percent",
                    "2026-07-15T19:00:03.000Z,22.0,38.0",
                ],
            )


if __name__ == "__main__":
    unittest.main()
