"""Read the latest local Adafruit SHT45 humidity measurement."""

import csv
import math
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path


HUMIDITY_LIMIT = 90.0
MAX_MEASUREMENT_AGE = timedelta(minutes=10)


@dataclass(frozen=True)
class Measurement:
    timestamp: datetime
    humidity: float


def _last_nonempty_line(path):
    with Path(path).open("rb") as log_file:
        log_file.seek(0, 2)
        position = log_file.tell()
        buffer = b""

        while position > 0:
            read_size = min(position, 4096)
            position -= read_size
            log_file.seek(position)
            buffer = log_file.read(read_size) + buffer
            lines = buffer.splitlines()

            # The first line may be partial until the beginning of the file is reached.
            complete_lines = lines if position == 0 else lines[1:]
            for line in reversed(complete_lines):
                if line.strip():
                    return line.decode("utf-8")

    raise ValueError(f"Adafruit sensor log is empty: {path}")


def latest_measurement(path=None):
    """Return timestamp and relative humidity from the final nonempty CSV row."""
    path = Path.home() / "adafruit.csv" if path is None else Path(path)
    line = _last_nonempty_line(path)

    try:
        row = next(csv.reader([line]))
    except csv.Error as error:
        raise ValueError(f"Invalid Adafruit sensor row: {line!r}") from error

    if len(row) != 3:
        raise ValueError(f"Invalid Adafruit sensor row: {line!r}")

    try:
        timestamp = datetime.fromisoformat(row[0])
    except ValueError as error:
        raise ValueError(f"Invalid Adafruit timestamp: {row[0]!r}") from error

    if timestamp.tzinfo is None or timestamp.utcoffset() is None:
        raise ValueError(f"Adafruit timestamp has no timezone: {row[0]!r}")

    try:
        humidity = float(row[2])
    except ValueError as error:
        raise ValueError(f"Invalid Adafruit humidity value: {row[2]!r}") from error

    if not math.isfinite(humidity):
        raise ValueError(f"Invalid Adafruit humidity value: {row[2]!r}")
    return Measurement(timestamp=timestamp.astimezone(UTC), humidity=humidity)


def latest_humidity(path=None):
    return latest_measurement(path).humidity


def humidity_is_safe(humidity):
    return humidity < HUMIDITY_LIMIT


def measurement_is_stale(timestamp, now=None):
    now = datetime.now(UTC) if now is None else now
    return now - timestamp > MAX_MEASUREMENT_AGE


def measurement_requires_closure(measurement, now=None):
    return not measurement_is_stale(measurement.timestamp, now=now) and not humidity_is_safe(measurement.humidity)
