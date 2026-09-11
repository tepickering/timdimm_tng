"""
Closure protocol for condensation on the prism.

The humidity limits close the roof at 90% RH, but the prism dews at about 80% -- every event so far
started with the SHT45 near 80-85% while SALT read drier still (see `scintillation.CONDENSATION_THROUGHPUT`).
So the protocol has three parts:

* **warning** -- SHT45 humidity at or above `DEW_WARNING_HUMIDITY` is logged and shown, nothing more;
* **closure** -- the last cube's prism throughput at or below `scintillation.CLOSURE_THROUGHPUT` closes
  the roof, on that reading alone: no clean cube reads anywhere near it;
* **reopening** -- after a throughput closure the roof stays shut until both SALT and the SHT45 have
  read `REOPEN_HUMIDITY` or below for `REOPEN_DRY_PERIOD` without a break.

`status.py` runs every couple of seconds and holds nothing between runs, so the reopening clock is
kept in a small JSON file; `load_state` / `save_state` / `clear_state` manage it.
"""

import json
import math
from dataclasses import asdict, dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

from timdimm_tng.csv_tail import last_csv_row
from timdimm_tng.scintillation import CLOSURE_THROUGHPUT


#: SHT45 relative humidity at or above which the prism is liable to dew. Logged as a warning only.
DEW_WARNING_HUMIDITY = 80.0

#: Both SALT and the SHT45 must read at or below this to count as dry for reopening.
REOPEN_HUMIDITY = 75.0

#: How long both sensors must stay dry, without a break, before a throughput closure lifts.
REOPEN_DRY_PERIOD = timedelta(minutes=20)

#: How old the last cube may be before its throughput says nothing about the optics now. Cubes land
#: every ~40 s while observing; a reading older than this is from before a slew, a closure or a fault.
THROUGHPUT_MAX_AGE = timedelta(minutes=15)


@dataclass(frozen=True)
class Throughput:
    value: float
    target: str
    timestamp: datetime


@dataclass(frozen=True)
class DewingState:
    """A throughput closure in force, and how long the air has been dry since."""
    closed_at: datetime
    throughput: float
    target: str
    #: When both sensors were last seen turning dry, or ``None`` while either is wet or missing.
    dry_since: datetime | None = None


def humidity_is_warning(humidity):
    return humidity >= DEW_WARNING_HUMIDITY


def latest_throughput(path):
    """
    The last cube's prism throughput from ``scintillation.csv``, or ``None`` if there is no usable row.
    """
    row = last_csv_row(path)
    if row is None:
        return None
    try:
        stamp = datetime.fromisoformat(row["time"])
        value = float(row["throughput"])
    except (KeyError, TypeError, ValueError):
        return None
    if stamp.tzinfo is None:
        stamp = stamp.replace(tzinfo=UTC)
    return Throughput(value=value, target=row.get("target", ""), timestamp=stamp)


def throughput_requires_closure(reading, now=None):
    """
    Whether a throughput reading calls for closing the roof.

    A missing or NaN reading does not: `scintillation.throughput` returns NaN for a failed measurement,
    which says nothing about the optics. Nor does a stale one -- the last cube before a closure is
    exactly the reading that must not keep the roof shut once the hold has lifted.
    """
    if reading is None or math.isnan(reading.value):
        return False
    now = datetime.now(UTC) if now is None else now
    if now - reading.timestamp > THROUGHPUT_MAX_AGE:
        return False
    return reading.value <= CLOSURE_THROUGHPUT


def update_reopen(state, salt_humidity, sht45_humidity, now=None):
    """
    Advance the reopening clock by one reading from each sensor.

    Parameters
    ----------
    state : DewingState
        The closure in force.
    salt_humidity, sht45_humidity : float or None
        The current readings; ``None`` for a sensor that is invalid, stale or unavailable, which
        counts as wet -- it cannot vouch for the air.
    now : ~datetime.datetime, optional

    Returns
    -------
    (DewingState, bool)
        The updated state and whether the hold has lifted.
    """
    now = datetime.now(UTC) if now is None else now
    dry = (
        salt_humidity is not None and sht45_humidity is not None
        and salt_humidity <= REOPEN_HUMIDITY and sht45_humidity <= REOPEN_HUMIDITY
    )
    if not dry:
        return DewingState(state.closed_at, state.throughput, state.target, dry_since=None), False
    dry_since = state.dry_since if state.dry_since is not None else now
    updated = DewingState(state.closed_at, state.throughput, state.target, dry_since=dry_since)
    return updated, now - dry_since >= REOPEN_DRY_PERIOD


def load_state(path):
    """The closure recorded at ``path``, or ``None`` if there is none or the file is unreadable."""
    path = Path(path)
    try:
        data = json.loads(path.read_text())
        dry_since = data["dry_since"]
        return DewingState(
            closed_at=datetime.fromisoformat(data["closed_at"]),
            throughput=float(data["throughput"]),
            target=str(data["target"]),
            dry_since=None if dry_since is None else datetime.fromisoformat(dry_since),
        )
    except (OSError, ValueError, TypeError, KeyError):
        return None


def save_state(state, path):
    data = asdict(state)
    for key in ("closed_at", "dry_since"):
        if data[key] is not None:
            data[key] = data[key].isoformat()
    Path(path).write_text(json.dumps(data, indent=4))


def clear_state(path):
    Path(path).unlink(missing_ok=True)
