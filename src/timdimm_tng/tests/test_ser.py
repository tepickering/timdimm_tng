"""
Tests for the SER cube reader.

The archived cubes include files whose capture was interrupted, so the header promises more frames
than the file actually holds. Those have to come back as the frames that are there rather than as an
exception, or one bad cube takes out a whole survey run.
"""

import numpy as np
import pytest

from timdimm_tng.ser import load_ser_file
from timdimm_tng.tests.ser_helpers import HEIGHT, NFRAMES, START_TICKS, TICKS_PER_FRAME, WIDTH, write_ser


def test_reads_a_complete_cube(tmp_path):
    cube = load_ser_file(write_ser(tmp_path / "good.ser"))

    assert cube["nframe"] == NFRAMES
    assert cube["data"].shape == (NFRAMES, HEIGHT, WIDTH)
    assert cube["data"][2, 1, 1] == 2 * HEIGHT * WIDTH + WIDTH + 1
    assert len(cube["frame_times"]) == NFRAMES
    assert cube["frame_times"][0].isot.startswith("2024-05-05")


def test_a_truncated_cube_returns_the_frames_that_are_there(tmp_path):
    """A cube cut off mid-capture: the header claims 5 frames, only 3 whole ones were written."""
    path = tmp_path / "truncated.ser"
    write_ser(path)
    whole = 178 + 3 * HEIGHT * WIDTH * 2
    with open(path, "r+b") as fp:
        fp.truncate(whole + HEIGHT * WIDTH)  # three whole frames plus half of a fourth

    with pytest.warns(UserWarning, match="truncated"):
        cube = load_ser_file(path)

    assert cube["data"].shape == (3, HEIGHT, WIDTH)
    assert cube["nframe"] == 3
    assert cube["nframe_header"] == NFRAMES
    np.testing.assert_array_equal(cube["data"][2], np.arange(
        2 * HEIGHT * WIDTH, 3 * HEIGHT * WIDTH, dtype=np.uint16).reshape(HEIGHT, WIDTH))


def test_a_truncated_cube_has_no_timestamp_trailer(tmp_path):
    """The trailer sits after the image data, so a cut-off cube loses it entirely."""
    path = tmp_path / "truncated.ser"
    write_ser(path)
    with open(path, "r+b") as fp:
        fp.truncate(178 + 3 * HEIGHT * WIDTH * 2)

    with pytest.warns(UserWarning):
        cube = load_ser_file(path)

    assert len(cube["frame_times"]) == 0


def test_a_short_trailer_is_not_padded_out(tmp_path):
    """Timestamps for frames that were never written must not be invented."""
    path = tmp_path / "shorttrailer.ser"
    write_ser(path, timestamps=START_TICKS + TICKS_PER_FRAME * np.arange(2, dtype=np.uint64))

    cube = load_ser_file(path)

    assert cube["data"].shape == (NFRAMES, HEIGHT, WIDTH)
    assert len(cube["frame_times"]) == 2


def test_a_cube_with_no_whole_frames_is_empty_rather_than_an_error(tmp_path):
    path = tmp_path / "stub.ser"
    write_ser(path)
    with open(path, "r+b") as fp:
        fp.truncate(178 + 10)

    with pytest.warns(UserWarning, match="truncated"):
        cube = load_ser_file(path)

    assert cube["nframe"] == 0
    assert cube["data"].shape == (0, HEIGHT, WIDTH)
    assert len(cube["frame_times"]) == 0
