"""
Tests for the daily rotation of the weather CSVs.

Unlike the Adafruit logger, nothing needs to be stopped first: ``status.py`` opens and closes the
file once per row, and ``csv_log.ensure_header`` writes a fresh header whenever the file is gone.
A row written between the rename and the next append lands in the archive, which is where a
reading taken before the rotation belongs anyway.
"""

import gzip
import os
import subprocess
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).parents[3]
ROTATION_SCRIPT = REPO_ROOT / "scripts" / "rotate_wx_logs"

SALT_CSV = "time,timestamp_sast,Temp\n2026-08-22T20:09:31.984,2026-08-22T22:09:31,7.20\n"
SAAO_IO_CSV = "time,timestamp_sast,temperature\n2026-08-22T20:09:31.984,2026-08-22T22:08:49,7.03\n"


class TestRotateWxLogs(unittest.TestCase):
    def setUp(self):
        self.tmp_dir = tempfile.TemporaryDirectory()
        self.tmp_path = Path(self.tmp_dir.name)
        self.salt = self.tmp_path / "salt_wx.csv"
        self.saao_io = self.tmp_path / "saao_io.csv"
        self.environment = {
            **os.environ,
            "WX_LOG_DIR": str(self.tmp_path),
            "WX_ROTATION_DATE": "2026-08-22",
        }

    def tearDown(self):
        self.tmp_dir.cleanup()

    def run_rotation(self):
        return subprocess.run(
            ["bash", str(ROTATION_SCRIPT)], env=self.environment, capture_output=True, text=True
        )

    def archive(self, name):
        return self.tmp_path / f"{name}-2026-08-22.csv.gz"

    def test_rotates_both_weather_logs(self):
        self.salt.write_text(SALT_CSV)
        self.saao_io.write_text(SAAO_IO_CSV)

        result = self.run_rotation()

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse(self.salt.exists())
        self.assertFalse(self.saao_io.exists())
        for name, content in (("salt_wx", SALT_CSV), ("saao_io", SAAO_IO_CSV)):
            with gzip.open(self.archive(name), "rt") as archive_file:
                self.assertEqual(archive_file.read(), content)

    def test_a_missing_log_is_not_an_error_and_the_other_still_rotates(self):
        # the roof interface may not have run at all on a clouded-out day
        self.salt.write_text(SALT_CSV)

        result = self.run_rotation()

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(self.archive("salt_wx").exists())
        self.assertFalse(self.archive("saao_io").exists())

    def test_nothing_to_rotate_succeeds(self):
        self.assertEqual(self.run_rotation().returncode, 0)

    def test_existing_archive_is_not_overwritten(self):
        self.salt.write_text(SALT_CSV)
        self.archive("salt_wx").write_text("existing archive\n")

        result = self.run_rotation()

        self.assertEqual(result.returncode, 1)
        self.assertEqual(self.salt.read_text(), SALT_CSV)
        self.assertEqual(self.archive("salt_wx").read_text(), "existing archive\n")

    def test_one_refusal_does_not_block_the_other_log(self):
        self.salt.write_text(SALT_CSV)
        self.saao_io.write_text(SAAO_IO_CSV)
        self.archive("salt_wx").write_text("existing archive\n")

        result = self.run_rotation()

        self.assertEqual(result.returncode, 1)
        self.assertEqual(self.salt.read_text(), SALT_CSV)
        with gzip.open(self.archive("saao_io"), "rt") as archive_file:
            self.assertEqual(archive_file.read(), SAAO_IO_CSV)

    def test_an_uncompressed_archive_also_blocks_rotation(self):
        # a previous run that died between the rename and the gzip
        self.salt.write_text(SALT_CSV)
        (self.tmp_path / "salt_wx-2026-08-22.csv").write_text("half-rotated\n")

        result = self.run_rotation()

        self.assertEqual(result.returncode, 1)
        self.assertEqual(self.salt.read_text(), SALT_CSV)


if __name__ == "__main__":
    unittest.main()
