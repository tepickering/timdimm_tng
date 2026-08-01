import unittest

import astropy.units as u

from timdimm_tng.boresight import (
    PIER_EAST,
    PIER_UNKNOWN,
    PIER_WEST,
    boresight_separation,
    corrected_target,
    ra_offset,
)


class TestBoresightSeparation(unittest.TestCase):
    def test_separation_matches_measured_star_position(self):
        # target lands at (1030, 940) on a 1608x1104 chip when centered in the guide scope,
        # which is 449 px from the center at 0.7426"/px
        self.assertAlmostEqual(boresight_separation().to_value(u.arcsec), 333.4, places=1)


class TestRAOffset(unittest.TestCase):
    def test_pointing_east_from_west_side_of_pier_jogs_east(self):
        offset = ra_offset(-37.1236 * u.deg, PIER_WEST)
        self.assertGreater(offset.to_value(u.hourangle) * 3600, 0)

    def test_pointing_west_from_east_side_of_pier_jogs_west(self):
        offset = ra_offset(-37.1236 * u.deg, PIER_EAST)
        self.assertLess(offset.to_value(u.hourangle) * 3600, 0)

    def test_magnitude_at_measured_declination(self):
        # 333.4" / (15 cos(-37.1236)) = 27.9 seconds of RA
        offset = ra_offset(-37.1236 * u.deg, PIER_WEST)
        self.assertAlmostEqual(offset.to_value(u.hourangle) * 3600, 27.9, places=1)

    def test_pier_side_only_changes_sign_not_magnitude(self):
        west = ra_offset(-50 * u.deg, PIER_WEST).to_value(u.hourangle)
        east = ra_offset(-50 * u.deg, PIER_EAST).to_value(u.hourangle)
        self.assertAlmostEqual(west, -east, places=12)

    def test_offset_scales_as_inverse_cosine_of_declination(self):
        # on the celestial equator the offset is the raw separation converted to time
        equator = ra_offset(0 * u.deg, PIER_WEST).to_value(u.hourangle) * 3600
        self.assertAlmostEqual(equator, 22.23, places=2)

    def test_offset_grows_toward_the_pole(self):
        near = ra_offset(-30 * u.deg, PIER_WEST).to_value(u.hourangle)
        far = ra_offset(-65 * u.deg, PIER_WEST).to_value(u.hourangle)
        self.assertGreater(far, near)

    def test_unknown_pier_side_applies_no_offset(self):
        self.assertEqual(ra_offset(-40 * u.deg, PIER_UNKNOWN).to_value(u.hourangle), 0.0)


class TestCorrectedTarget(unittest.TestCase):
    def test_corrected_ra_is_target_plus_offset(self):
        ra, _ = corrected_target(12.0 * u.hourangle, -37.1236 * u.deg, PIER_WEST)
        expected = 12.0 + ra_offset(-37.1236 * u.deg, PIER_WEST).to_value(u.hourangle)
        self.assertAlmostEqual(ra.to_value(u.hourangle), expected, places=12)

    def test_declination_is_untouched(self):
        _, dec = corrected_target(12.0 * u.hourangle, -37.1236 * u.deg, PIER_WEST)
        self.assertAlmostEqual(dec.to_value(u.deg), -37.1236, places=12)

    def test_correction_wraps_around_zero_hours(self):
        ra, _ = corrected_target(23.999 * u.hourangle, 0 * u.deg, PIER_WEST)
        self.assertLess(ra.to_value(u.hourangle), 1.0)
        self.assertGreaterEqual(ra.to_value(u.hourangle), 0.0)


if __name__ == "__main__":
    unittest.main()
