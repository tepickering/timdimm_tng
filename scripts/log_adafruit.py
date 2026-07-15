#!/usr/bin/env python3

"""Log SHT45 measurements received over USB serial to a CSV file."""

import argparse
import csv
import math
import sys
from datetime import UTC, datetime
from pathlib import Path


DEFAULT_PORT = (
    "/dev/serial/by-id/"
    "usb-Adafruit_Industries_LLC_SHT4x_Trinkey_M0_1D7A4E235359575020312E3512210CFF-if00"
)
CSV_HEADER = ("timestamp_utc", "temperature_c", "relative_humidity_percent")


def parse_measurement(line):
    """Return temperature and humidity from a device data line."""
    fields = [field.strip() for field in line.strip().split(",")]
    if len(fields) != 2:
        return None

    try:
        measurement = tuple(float(field) for field in fields)
    except ValueError:
        return None

    if not all(math.isfinite(value) for value in measurement):
        return None
    return measurement


def utc_timestamp():
    return datetime.now(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def log_measurements(serial_port, output_path, timestamp_factory=utc_timestamp):
    """Read measurements until interrupted and append them to output_path."""
    output_path = Path(output_path).expanduser()
    write_header = not output_path.exists() or output_path.stat().st_size == 0

    with output_path.open("a", encoding="utf-8", newline="") as output_file:
        writer = csv.writer(output_file)
        if write_header:
            writer.writerow(CSV_HEADER)
            output_file.flush()

        while True:
            raw_line = serial_port.readline()
            if not raw_line:
                continue

            measurement = parse_measurement(raw_line.decode("ascii", errors="replace"))
            if measurement is None:
                continue

            writer.writerow((timestamp_factory(), *measurement))
            output_file.flush()


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", default=DEFAULT_PORT, help="serial device path")
    parser.add_argument("--baudrate", type=int, default=115200, help="serial baud rate (default: 115200)")
    parser.add_argument(
        "--output",
        type=Path,
        default=Path.home() / "adafruit.csv",
        help="CSV output path (default: ~/adafruit.csv)",
    )
    return parser.parse_args(argv)


def main(argv=None):
    args = parse_args(argv)

    try:
        import serial
    except ImportError:
        print("pyserial is required; run this script in the timdimm conda environment", file=sys.stderr)
        return 1

    print(f"Logging {args.port} to {args.output.expanduser()}", file=sys.stderr)
    try:
        with serial.Serial(args.port, baudrate=args.baudrate, timeout=10) as serial_port:
            log_measurements(serial_port, args.output)
    except KeyboardInterrupt:
        print("\nStopped", file=sys.stderr)
        return 0
    except (OSError, serial.SerialException) as error:
        print(f"Unable to log sensor data: {error}", file=sys.stderr)
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
