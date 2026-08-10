import unittest

import astropy.units as u

from timdimm_tng.boresight import (
    ALIGN_COMPLETE,
    ALIGN_IDLE,
    ALIGN_PROGRESS,
    ALIGN_SLEWING,
    PIER_EAST,
    PIER_UNKNOWN,
    PIER_WEST,
    BoresightCorrector,
    ra_offset,
)

DEC = -37.1236


class TestBoresightCorrector(unittest.TestCase):
    def setUp(self):
        self.corrector = BoresightCorrector()

    def test_idle_align_is_left_alone(self):
        self.assertIsNone(self.corrector.update(ALIGN_IDLE, 12.0, DEC, PIER_WEST))

    def test_completed_align_is_left_alone(self):
        self.assertIsNone(self.corrector.update(ALIGN_COMPLETE, 12.0, DEC, PIER_WEST))

    def test_align_in_progress_gets_corrected_target(self):
        result = self.corrector.update(ALIGN_PROGRESS, 12.0, DEC, PIER_WEST)
        self.assertIsNotNone(result)
        expected = 12.0 + ra_offset(DEC * u.deg, PIER_WEST).to_value(u.hourangle)
        self.assertAlmostEqual(result[0], expected, places=9)
        self.assertAlmostEqual(result[1], DEC, places=9)

    def test_align_slewing_also_gets_corrected(self):
        self.assertIsNotNone(self.corrector.update(ALIGN_SLEWING, 12.0, DEC, PIER_WEST))

    def test_correction_is_not_applied_twice_to_the_same_target(self):
        first = self.corrector.update(ALIGN_PROGRESS, 12.0, DEC, PIER_WEST)
        assert first is not None
        # align now reports the corrected coordinates back to us
        self.assertIsNone(self.corrector.update(ALIGN_PROGRESS, first[0], DEC, PIER_WEST))

    def test_a_new_target_is_corrected_again(self):
        first = self.corrector.update(ALIGN_PROGRESS, 12.0, DEC, PIER_WEST)
        assert first is not None
        self.corrector.update(ALIGN_PROGRESS, first[0], DEC, PIER_WEST)
        self.assertIsNotNone(self.corrector.update(ALIGN_PROGRESS, 3.5, DEC, PIER_WEST))

    def test_same_target_after_pier_flip_recorrects_from_the_original_target(self):
        first = self.corrector.update(ALIGN_PROGRESS, 12.0, DEC, PIER_WEST)
        assert first is not None
        # align echoes our corrected coords back, but the mount has flipped. the new correction
        # has to be measured from the original 12.0, not from the already-corrected value.
        result = self.corrector.update(ALIGN_PROGRESS, first[0], DEC, PIER_EAST)
        assert result is not None
        expected = 12.0 + ra_offset(DEC * u.deg, PIER_EAST).to_value(u.hourangle)
        self.assertAlmostEqual(result[0], expected, places=9)

    def test_flip_is_handled_even_when_align_completed_in_between(self):
        # the real meridian flip case: align finishes, the mount flips, and ekos starts a new
        # align run still holding the coordinates we pushed it last time. we have to recognize
        # those as ours and recorrect from the original target, not stack a second correction.
        first = self.corrector.update(ALIGN_PROGRESS, 12.0, DEC, PIER_WEST)
        assert first is not None
        self.corrector.update(ALIGN_COMPLETE, first[0], DEC, PIER_WEST)
        result = self.corrector.update(ALIGN_PROGRESS, first[0], DEC, PIER_EAST)
        assert result is not None
        expected = 12.0 + ra_offset(DEC * u.deg, PIER_EAST).to_value(u.hourangle)
        self.assertAlmostEqual(result[0], expected, places=9)

    def test_flip_destination_is_recognized_as_our_own_target(self):
        # ekos overwrites the align target with the mount's current pointing when it starts a
        # meridian flip, so the post-flip align run starts from our corrected coordinates plus
        # whatever align and guiding residual was on the sky, not from an exact echo.
        first = self.corrector.update(ALIGN_PROGRESS, 12.0, DEC, PIER_WEST)
        assert first is not None
        pointing = first[0] + 20 / 15 / 3600  # 20" of residual, well inside align tolerance
        result = self.corrector.update(ALIGN_PROGRESS, pointing, DEC, PIER_EAST)
        assert result is not None
        expected = 12.0 + ra_offset(DEC * u.deg, PIER_EAST).to_value(u.hourangle)
        self.assertAlmostEqual(result[0], expected, places=9)

    def test_a_genuinely_new_target_is_not_mistaken_for_our_own(self):
        first = self.corrector.update(ALIGN_PROGRESS, 12.0, DEC, PIER_WEST)
        assert first is not None
        # a different star, closer than the correction itself but far outside the residual
        result = self.corrector.update(ALIGN_PROGRESS, first[0] + 0.05, DEC, PIER_WEST)
        assert result is not None
        expected = first[0] + 0.05 + ra_offset(DEC * u.deg, PIER_WEST).to_value(u.hourangle)
        self.assertAlmostEqual(result[0], expected, places=9)

    def test_echoed_target_is_left_alone_when_align_restarts_on_the_same_side(self):
        first = self.corrector.update(ALIGN_PROGRESS, 12.0, DEC, PIER_WEST)
        assert first is not None
        self.corrector.update(ALIGN_COMPLETE, first[0], DEC, PIER_WEST)
        self.assertIsNone(self.corrector.update(ALIGN_PROGRESS, first[0], DEC, PIER_WEST))

    def test_unknown_pier_side_issues_no_correction(self):
        self.assertIsNone(self.corrector.update(ALIGN_PROGRESS, 12.0, DEC, PIER_UNKNOWN))

    def test_target_is_corrected_again_after_align_finishes_and_restarts(self):
        first = self.corrector.update(ALIGN_PROGRESS, 12.0, DEC, PIER_WEST)
        assert first is not None
        self.corrector.update(ALIGN_COMPLETE, first[0], DEC, PIER_WEST)
        self.assertIsNotNone(self.corrector.update(ALIGN_PROGRESS, 12.0, DEC, PIER_WEST))


if __name__ == "__main__":
    unittest.main()
