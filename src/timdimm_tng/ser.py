"""
the specifications for unpacking SER files are given at:
http://www.grischa-hahn.homepage.t-online.de/astro/ser/SER%20Doc%20V3b.pdf
"""

from struct import unpack
from pathlib import Path
from enum import Enum

import numpy as np

from astropy.time import Time
import astropy.units as u


def read_int(fp, endian="<"):
    val = unpack(f"{endian}I", fp.read(4))[0]
    return val


def read_long(fp, endian="<"):
    val = unpack(f"{endian}Q", fp.read(8))[0]
    return val


def read_str(fp, len):
    return fp.read(len).decode().strip()


def parse_time(timestamp):
    """
    According to Microsoft documentation, SER timestamps have the following format:

    “Holds IEEE 64-bit (8-byte) values that represent dates ranging from January 1 of the year 0001
    through December 31 of the year 9999, and times from 12:00:00 AM (midnight) through
    11:59:59.9999999 PM. Each increment represents 100 nanoseconds of elapsed time since the
    beginning of January 1 of the year 1 in the Gregorian calendar. The maximum value represents
    100 nanoseconds before the beginning of January 1 of the year 10000.”
    According to the findings of Raoul Behrend, Université de Genève, the date record is not a 64 bits
    unsigned integer as stated, but a 62 bits unsigned integer. He got no information about the use of
    the two MSB.
    """
    # this implementation of the microsoft-provided spec has been tested and does work as intended
    return timestamp * 100e-9 * u.second + Time("0001-01-01 00:00:00")


class Color_ID(Enum):
    MONO = 0
    BAYER_RGGB = 8
    BAYER_GRBG = 9
    BAYER_GBRG = 10
    BAYER_BGGR = 11
    BAYER_CYYM = 16
    BAYER_YCMY = 17
    BAYER_YMCY = 18
    BAYER_MYYC = 19
    RGB = 100
    BGR = 101


def load_ser_file(filename):
    """
    Load SER file based on specifications given at:

    http://www.grischa-hahn.homepage.t-online.de/astro/ser/SER%20Doc%20V3b.pdf

    Comments are transcribed from that documentation.
    """
    p = Path(filename)
    with open(p, "r+b") as fp:
        output = {}
        output["filename"] = str(filename)

        # 1_FileID
        # Format: String
        # Length: 14 Byte (14 ASCII characters)
        # Content: "LUCAM-RECORDER" (fix)
        output["file_id"] = read_str(fp, 14)

        # 2_LuID
        # Format: Integer_32 (little-endian)
        # Length: 4 Byte
        # Content: Lumenera camera series ID (currently unused; default = 0)
        output["lu_id"] = read_int(fp)

        # 3_ColorID
        # Format: Integer_32 (little-endian)
        # Length: 4 Byte
        # Content:
        #     MONO = 0
        #     BAYER_RGGB = 8
        #     BAYER_GRBG = 9
        #     BAYER_GBRG = 10
        #     BAYER_BGGR = 11
        #     BAYER_CYYM = 16
        #     BAYER_YCMY = 17
        #     BAYER_YMCY = 18
        #     BAYER_MYYC = 19
        #     RGB = 100
        #     BGR = 101
        output["color_id"] = read_int(fp)
        if output["color_id"] < 100:
            output["nplanes"] = 1
        else:
            output["nplanes"] = 3

        # 4_LittleEndian
        # Format: Integer_32 (little-endian)
        # Length: 4 Byte
        # Content: 0 (FALSE) for big-endian byte order in 16 bit image data
        #          1 (TRUE) for little-endian byte order in 16 bit image data
        output["littleendian"] = read_int(fp)

        # 5_ImageWidth
        # Format: Integer_32 (little-endian)
        # Length: 4 Byte
        # Content: Width of every image in pixel
        output["im_width"] = read_int(fp)

        # 6_ImageHeight
        # Format: Integer_32 (little-endian)
        # Length: 4 Byte
        # Content: Height of every image in pixel
        output["im_height"] = read_int(fp)

        # 7_PixelDepthPerPlane
        # Format: Integer_32 (little-endian)
        # Length: 4 Byte
        # Content: True bit depth per pixel per plane
        output["pix_depth_per_plane"] = read_int(fp)

        if output["color_id"] in (Color_ID.RGB, Color_ID.BGR):
            output["nplanes"] = 3
        else:
            output["nplanes"] = 1

        if output["pix_depth_per_plane"] < 9:
            output["bytes_per_pixel"] = output["nplanes"]
        else:
            output["bytes_per_pixel"] = 2 * output["nplanes"]

        # 8_FrameCount
        # Format: Integer_32 (little-endian)
        # Length: 4 Byte
        # Content: Number of image frames in SER file
        output["nframe"] = read_int(fp)

        # 9_Observer
        # Format: String
        # Length: 40 Byte (40 ASCII characters {32…126 dec.}, fill unused characters with 0 dec.)
        # Content: Name of observer
        output["observer"] = read_str(fp, 40)

        # 10_Instrument
        # Format: String
        # Length: 40 Byte (40 ASCII characters {32…126 dec.}, fill unused characters with 0 dec.)
        # Content: Name of used camera
        output["instrument"] = read_str(fp, 40)

        # 11_Telescope
        # Format: String
        # Length: 40 Byte (40 ASCII characters {32…126 dec.}, fill unused characters with 0 dec.)
        # Content: Name of used telescope
        output["telescope"] = read_str(fp, 40)

        # 12_DateTime
        # Format: Date / Integer_64 (little-endian)
        # Length: 8 Byte
        # Content: Start time of image stream (local time)
        # If 12_DateTime <= 0 then 12_DateTime is invalid and the SER file does not contain a
        # Time stamp trailer.
        output["dateobs"] = parse_time(read_long(fp))

        # 13_DateTime_UTC
        # Format: Date / Integer_64 (little-endian)
        # Length: 8 Byte
        # Content: Start time of image stream in UTC
        output["dateobs_utc"] = parse_time(read_long(fp))

        # Image data starts at File start offset decimal 178
        # Size of every image frame in byte is: 5_ImageWidth x 6_ImageHeigth x BytePerPixel
        data_buf = fp.read(
            output["nframe"]
            * output["im_width"]
            * output["im_height"]
            * output["bytes_per_pixel"]
        )
        if output["bytes_per_pixel"] == 1:
            output["data"] = np.frombuffer(data_buf, dtype=np.uint8).reshape(
                (output["nframe"], output["im_height"], output["im_width"])
            )
        else:
            output["data"] = np.frombuffer(data_buf, dtype=np.uint16).reshape(
                (output["nframe"], output["im_height"], output["im_width"])
            )

        # Trailer starts at byte offset: 178 + 8_FrameCount x 5_ImageWidth x 6_ImageHeigth x BytePerPixel.
        # Trailer contains Date / Integer_64 (little-endian) time stamps in UTC for every image frame.
        trailer_buf = fp.read()
        output["frame_times"] = parse_time(np.frombuffer(trailer_buf, dtype=np.uint64))

        return output
