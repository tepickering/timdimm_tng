import sys
import argparse
import logging
import warnings

from astropy.time import Time

from timdimm_tng.indi import INDI_Camera


warnings.filterwarnings("error", module="astropy._erfa")
log = logging.getLogger("SER video capture")
log.setLevel(logging.INFO)

ch = logging.StreamHandler(sys.stdout)
ch.setLevel(logging.INFO)
formatter = logging.Formatter("%(levelname)s - %(message)s")
ch.setFormatter(formatter)
log.addHandler(ch)


def main():
    parser = argparse.ArgumentParser(
        description="Utility for recording videos from INDI cameras"
    )

    parser.add_argument(
        "--host",
        metavar="<hostname>",
        help="Hostname of INDI Server Host Computer",
        default="localhost",
    )

    parser.add_argument(
        "--port", metavar="<port>", help="INDI Server Port", default=7624
    )

    parser.add_argument(
        "-c",
        "--camera",
        metavar="<INDI camera>",
        help="Name of INDI Camera",
        default="CCD Simulator",
    )

    parser.add_argument(
        "-e",
        "--exposure",
        metavar="<exposure time>",
        help="Camera Exposure Time in seconds",
        default=0.001,
    )

    capture_group = parser.add_mutually_exclusive_group()
    capture_group.add_argument(
        "-n",
        "--nframes",
        metavar="<record N frames>",
        help="Number of Frames to Capture",
        default=10,
    )

    capture_group.add_argument(
        "-d",
        "--duration",
        metavar="<record N seconds>",
        help="Duration to capture in seconds",
    )

    parser.add_argument(
        "--savedir", metavar="<save directory>", help="Directory to Save to"
    )

    parser.add_argument(
        "--filename", metavar="<filename>", help="Filename to Save Video to"
    )

    record_group = parser.add_mutually_exclusive_group()
    record_group.add_argument(
        "--ser", action="store_true", help="Use SER Video Recorder"
    )

    record_group.add_argument(
        "--ogv", action="store_true", help="Use OGV Video Recorder"
    )

    encoder_group = parser.add_mutually_exclusive_group()
    encoder_group.add_argument(
        "--raw", action="store_true", help="Use RAW Video Encoder"
    )

    encoder_group.add_argument(
        "--mjpeg", action="store_true", help="Use MJPEG Video Encoder"
    )

    args = parser.parse_args()

    cam = INDI_Camera(args.camera, host=args.host, port=args.port)

    # target = cam.get_prop("FITS_HEADER", "FITS_OBJECT")

    if args.filename is None:
        args.filename = f"{Time.now().strftime('%Y-%m-%dZ%H-%M-%S')}"

    if args.mjpeg:
        cam.mjpeg_mode()

    if args.raw:
        cam.raw_mode()

    if args.ogv:
        cam.ogv_mode()

    if args.ser:
        cam.ser_mode()

    cam.stream_exposure(args.exposure)

    if args.duration:
        cam.record_duration(args.duration, savedir=args.savedir, filename=args.filename)
    else:
        cam.record_frames(args.nframes, savedir=args.savedir, filename=args.filename)

    return 0


if __name__ == "__main__":
    main()
