import gzip
import os
import subprocess
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).parents[3]
ROTATION_SCRIPT = REPO_ROOT / "scripts" / "rotate_adafruit_log"


class TestRotateAdafruitLog(unittest.TestCase):
    def setUp(self):
        self.tmp_dir = tempfile.TemporaryDirectory()
        self.tmp_path = Path(self.tmp_dir.name)
        self.log_path = self.tmp_path / "adafruit.csv"
        self.systemctl_calls = self.tmp_path / "systemctl-calls"
        self.fake_systemctl = self.tmp_path / "systemctl"
        self.fake_systemctl.write_text('#!/bin/bash\necho "$*" >> "$SYSTEMCTL_CALLS"\n')
        self.fake_systemctl.chmod(0o755)
        self.environment = {
            **os.environ,
            "ADAFRUIT_LOG_FILE": str(self.log_path),
            "ADAFRUIT_ROTATION_DATE": "2026-07-15",
            "SYSTEMCTL_CALLS": str(self.systemctl_calls),
            "SYSTEMCTL_COMMAND": str(self.fake_systemctl),
        }

    def tearDown(self):
        self.tmp_dir.cleanup()

    def run_rotation(self):
        return subprocess.run(
            ["bash", str(ROTATION_SCRIPT)],
            env=self.environment,
            capture_output=True,
            text=True,
        )

    def test_rotates_csv_and_restarts_logger(self):
        csv_content = "timestamp_utc,temperature_c,relative_humidity_percent\n2026-07-15T09:59:57.000Z,21.4,37.2\n"
        self.log_path.write_text(csv_content)

        result = self.run_rotation()

        archive_path = self.tmp_path / "adafruit-2026-07-15.csv.gz"
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse(self.log_path.exists())
        with gzip.open(archive_path, "rt") as archive_file:
            self.assertEqual(archive_file.read(), csv_content)
        self.assertEqual(
            self.systemctl_calls.read_text().splitlines(),
            ["stop adafruit-sht45.service", "start adafruit-sht45.service"],
        )

    def test_existing_archive_is_not_overwritten_and_logger_restarts(self):
        self.log_path.write_text("new data\n")
        archive_path = self.tmp_path / "adafruit-2026-07-15.csv.gz"
        archive_path.write_text("existing archive\n")

        result = self.run_rotation()

        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(self.log_path.read_text(), "new data\n")
        self.assertEqual(archive_path.read_text(), "existing archive\n")
        self.assertEqual(
            self.systemctl_calls.read_text().splitlines(),
            ["stop adafruit-sht45.service", "start adafruit-sht45.service"],
        )


if __name__ == "__main__":
    unittest.main()
