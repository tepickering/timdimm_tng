"""Builders for synthetic SER cubes, shared by the reader tests and the cube-analysis tests."""

import struct

import numpy as np

WIDTH, HEIGHT, NFRAMES = 8, 6, 5
#: 100 ns ticks since 0001-01-01, i.e. the SER timestamp epoch. This is 2024-05-05T01:57 UTC.
START_TICKS = 638504710570000128
TICKS_PER_FRAME = 33000  # 3.3 ms


def write_ser(path, frames=None, nframe_header=None, timestamps=None, depth=16):
    """Write a minimal but spec-conforming SER file, with knobs for corrupting it.

    The cube dimensions come from ``frames``, so callers can build whatever shape they need.
    """
    if frames is None:
        frames = np.arange(NFRAMES * HEIGHT * WIDTH, dtype=np.uint16).reshape(NFRAMES, HEIGHT, WIDTH)
    frames = np.asarray(frames)
    nframes, height, width = frames.shape
    if nframe_header is None:
        nframe_header = nframes
    if timestamps is None:
        timestamps = START_TICKS + TICKS_PER_FRAME * np.arange(nframes, dtype=np.uint64)

    with open(path, "wb") as fp:
        fp.write(b"LUCAM-RECORDER")
        for value in (0, 0, 1, width, height, depth, nframe_header):
            fp.write(struct.pack("<I", value))
        for text in ("observer", "instrument", "telescope"):
            fp.write(text.encode().ljust(40, b"\0"))
        fp.write(struct.pack("<Q", START_TICKS))
        fp.write(struct.pack("<Q", START_TICKS))
        fp.write(np.asarray(frames, dtype=np.uint16 if depth > 8 else np.uint8).tobytes())
        fp.write(np.asarray(timestamps, dtype=np.uint64).tobytes())
    return path
