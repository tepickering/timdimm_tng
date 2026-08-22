"""
Append SALT and SAAO IO weather readings to per-source CSV files.

The observatory's weather lives in SAAO databases we cannot query, so the only durable record we
can build is the one we write ourselves as the readings pass through. ``status.py`` already calls
``get_current_conditions`` every couple of seconds while the dome interface is live, which makes it
the one place where both stations are already in hand -- no extra polling, no second network path
to fail.

Three properties matter, and each is a function below:

* **One row per station reading.** ``status.py`` fires far faster than either station updates, so a
  reading whose measurements match the row above it is dropped. Neither station's clock can serve
  as that key: SALT's ``TimeStamp_SAST`` is ``tcs_xml_time_info__timestamp``, the moment the TCS
  published its XML, which ticks every 5 s over a BMS that updates every 60 s. Keying on it turned
  an hour of SALT on 2026-08-22 into 844 rows carrying 72 distinct readings. The BMS block updates
  atomically -- across that hour every field that changed did so on the same 71 rows -- so the
  measurements themselves are a faithful stand-in for a measurement time the feed does not expose.
  Comparison is on the formatted fields, since a change below the file's precision is not in it.
* **A heartbeat, so silence still means something.** Dropping unchanged readings would make a
  frozen station look exactly like steady conditions, which is the failure this log most needs to
  show. An unchanged reading is written anyway once `HEARTBEAT_SECONDS` have passed.
* **A header that always describes its rows.** Same rule as ``scintillation.csv``: a file whose
  header no longer matches is moved aside rather than appended to, because the old rows are real
  measurements and appending wider rows under a narrower header leaves a file that will not parse.
* **A log time that joins the seeing archive.** Every row leads with ``time``, the UTC instant the
  reading was taken from the feed, formatted the way ``seeing.csv`` and ``scintillation.csv``
  format theirs. ``timestamp_sast`` beside it is the station's own clock, which is SAST -- two
  hours ahead -- and is the dedup key, not the join key.

Units are whatever the station serves, deliberately unconverted so nothing silently changes value
between the feed and the file:

* SALT ``Wind_speed`` is km/h (``salt_weather_xml`` multiplies the 10 m sensor's m/s by 3.6),
  ``Bar_Press`` is the feed's value times ten, and temperatures are Celsius.
* SAAO IO ``wind`` is as served by ``io.saao.ac.za`` and ``air_pressure`` is hPa. Both, along with
  temperature, humidity and wind direction, were relayed verbatim from SALT on 2026-08-22 -- 115 of
  116 values appeared in the SALT series unchanged -- because two of the site's stations were down
  after a storm and IO falls back on the most robust one. They are logged separately regardless, so
  the archive shows when IO stops agreeing with SALT again.
* SAAO IO ``tmtdew`` is the dewpoint *depression*, T - T(dew), not a dewpoint. The site closes the
  telescopes on it: it says how much margin a surface has before condensation starts, which a bare
  dewpoint does not. SALT's ``DewTemp`` beside it is a true dewpoint, and ``Temp - DewTemp``
  reproduces ``tmtdew`` to 0.00 +/- 0.05 C.
"""

from datetime import datetime


__all__ = [
    "SAAO_IO_COLUMNS", "SALT_COLUMNS", "SAAO_IO_PRECISION", "SALT_PRECISION",
    "DEDUP_EXCLUDED", "HEARTBEAT_SECONDS",
    "ensure_header", "format_row", "last_logged_fields", "log_reading",
    "saao_io_row", "salt_row", "log_saao_io", "log_salt",
]


#: SAAO IO's weather and its warning flags. The feed also carries ``zp_data`` and ``zp_ref_data``
#: -- arrays, which have no CSV representation -- and the ``atlas_*`` cloud and rain fields, which
#: are a separate instrument on its own clock. Both are left out. So is the feed's ``seeing``: that
#: is our own measurement coming back to us about 26 s late, and archiving it here would duplicate
#: ``seeing.csv`` while looking like an independent check on it.
SAAO_IO_COLUMNS = (
    "time", "timestamp_sast",
    "temperature", "humidity", "tmtdew", "wind", "wind_dir", "air_pressure", "cloud",
    "temperature_warn", "humidity_warn", "tmtdew_warn", "wind_warn", "rain_warn", "cloud_warn",
    "Valid",
)

#: Everything ``parse_salt_xml`` derives from the BMS cluster, in the names it gives them.
SALT_COLUMNS = (
    "time", "timestamp_sast",
    "Temp", "Rel_Hum", "DewTemp", "Wind_speed", "Wind_dir", "Bar_Press",
    "Rain", "SkyCon", "Open", "Valid",
)

#: Without a station timestamp there is no dedup key and no way to place the reading in time, so a
#: reading missing any of these is not logged at all. Everything else may be absent: SAAO IO serves
#: ``cloud`` as null whenever its cloud sensor is down, and that is worth recording as a gap.
SAAO_IO_REQUIRED = ("timestamp", "temperature", "humidity", "wind")
SALT_REQUIRED = ("TimeStamp_SAST", "Temp", "Rel_Hum", "Wind_speed")

#: Fixed precision keeps the files diffable and stops float repr noise from making two identical
#: readings look different. Anything absent here is written with ``str()``.
SAAO_IO_PRECISION = {
    "temperature": 2, "humidity": 2, "tmtdew": 2, "wind": 2, "wind_dir": 2,
    "air_pressure": 2, "cloud": 2,
}
SALT_PRECISION = {
    "Temp": 2, "Rel_Hum": 2, "DewTemp": 2, "Wind_speed": 2, "Wind_dir": 2, "Bar_Press": 2,
}

#: The two columns that are clocks rather than measurements, and so are not part of the dedup key.
#: Everything else is the reading, ``Valid`` included -- a station going stale under unchanged
#: numbers is a transition worth a row of its own.
DEDUP_EXCLUDED = ("time", "timestamp_sast")

#: How long an unchanged reading may go unlogged before a row is written anyway.
HEARTBEAT_SECONDS = 300


def ensure_header(path, header):
    """
    Make ``path`` a CSV whose first line is ``header``, preserving any older file.

    Parameters
    ----------
    path : ~pathlib.Path
        The CSV to check. Created with the header if absent.
    header : str
        The current header line, newline included.
    """
    if path.exists():
        with open(path) as fp:
            if fp.readline() == header:
                return
        stamp = datetime.fromtimestamp(path.stat().st_mtime).strftime("%Y%m%dT%H%M%S")
        rotated = path.with_name(f"{path.name}.{stamp}")
        # a second column change within the same second must not destroy the first rotation
        suffix = 0
        while rotated.exists():
            suffix += 1
            rotated = path.with_name(f"{path.name}.{stamp}.{suffix}")
        path.rename(rotated)

    with open(path, "w") as fp:
        fp.write(header)


def format_row(values, columns, precision):
    """
    Format one CSV row, newline included.

    A value that is absent or ``None`` is written as an empty field rather than the string
    ``None``, so a sensor outage reads as missing data to anything parsing the file.

    Parameters
    ----------
    values : dict
        The row's values, keyed by column name.
    columns : tuple of str
        Column order.
    precision : dict
        Decimal places per column. Columns absent here are written with ``str()``.

    Returns
    -------
    str
        The formatted row.
    """
    fields = []
    for column in columns:
        value = values.get(column)
        digits = precision.get(column)
        if value is None:
            fields.append("")
        elif digits is not None:
            fields.append(f"{value:.{digits}f}")
        else:
            fields.append(str(value))
    return ",".join(fields) + "\n"


def last_logged_fields(path):
    """
    Read the file's last data row as a list of fields, or ``None`` if there isn't one.

    Reads the whole file, which stays cheap at a row a minute. A final line without a trailing
    newline is treated as absent: it means the process died mid-write, and comparing against a
    truncated row would either suppress a real reading or, worse, match nothing ever again.

    Parameters
    ----------
    path : ~pathlib.Path
        The CSV to read.

    Returns
    -------
    list of str or None
        The last row's fields, in column order.
    """
    try:
        with open(path) as fp:
            text = fp.read()
    except FileNotFoundError:
        return None

    if not text.endswith("\n"):
        return None

    lines = text.splitlines()
    if len(lines) < 2:
        return None
    return lines[-1].split(",")


def _measurements(fields, columns):
    """Return the fields that make up the reading, dropping the two clocks."""
    return [field for column, field in zip(columns, fields) if column not in DEDUP_EXCLUDED]


def _heartbeat_due(previous, now, interval=HEARTBEAT_SECONDS):
    """
    Whether an unchanged reading should be written anyway.

    A log time that will not parse, or one that has gone backwards, counts as due. Both mean the
    comparison cannot be trusted, and writing a redundant row costs a line where suppressing a real
    one could hide a station freezing.
    """
    try:
        elapsed = (datetime.fromisoformat(now) - datetime.fromisoformat(previous)).total_seconds()
    except (TypeError, ValueError):
        return True
    return not 0 <= elapsed < interval


def saao_io_row(wx, now):
    """
    Build a ``saao_io.csv`` row from a ``parse_saao_io`` dict.

    Parameters
    ----------
    wx : dict
        The station reading.
    now : str
        UTC log time, formatted as ``seeing.csv`` formats its ``time``.

    Returns
    -------
    dict
        Row values keyed by column name.
    """
    row = {column: wx.get(column) for column in SAAO_IO_COLUMNS}
    row["time"] = now
    row["timestamp_sast"] = wx.get("timestamp")
    row["Valid"] = bool(wx.get("Valid", False))
    return row


def salt_row(wx, now):
    """
    Build a ``salt_wx.csv`` row from a ``parse_salt_xml`` dict.

    ``TimeStamp_SAST`` arrives as a ``datetime`` and is written in ISO form, which sorts correctly
    as text and matches how SAAO IO serves its own clock.

    Parameters
    ----------
    wx : dict
        The station reading.
    now : str
        UTC log time, formatted as ``seeing.csv`` formats its ``time``.

    Returns
    -------
    dict
        Row values keyed by column name.
    """
    row = {column: wx.get(column) for column in SALT_COLUMNS}
    row["time"] = now
    timestamp = wx.get("TimeStamp_SAST")
    row["timestamp_sast"] = timestamp.isoformat() if hasattr(timestamp, "isoformat") else timestamp
    row["Valid"] = bool(wx.get("Valid", False))
    return row


def _required_for(build_row):
    return SAAO_IO_REQUIRED if build_row is saao_io_row else SALT_REQUIRED


def log_reading(path, wx, build_row, columns, now, precision=None):
    """
    Append one station reading to ``path``, unless it is unusable or already logged.

    A reading is skipped when its measurements format identically to the row above it and the
    heartbeat is not yet due. See the module docstring for why the station clock cannot be the key.

    ``Valid`` is carried as a column rather than used as the gate. ``check_wx`` clears it for a
    clock offset outside 120 +/- 10 minutes as well as for an unreachable station, and a stale
    reading is still real data -- gating on it would let a clock skew at either end silently end
    the weather record. What is actually required is a station timestamp and the core measurements.

    Parameters
    ----------
    path : ~pathlib.Path
        The CSV to append to.
    wx : dict
        The station reading, as ``get_current_conditions`` returns it.
    build_row : callable
        ``saao_io_row`` or ``salt_row``.
    columns : tuple of str
        Column order for this file.
    now : str
        UTC log time, formatted as ``seeing.csv`` formats its ``time``.
    precision : dict, optional
        Decimal places per column. Defaults to the map matching ``build_row``.

    Returns
    -------
    bool
        Whether a row was written.
    """
    if precision is None:
        precision = SAAO_IO_PRECISION if build_row is saao_io_row else SALT_PRECISION

    for key in _required_for(build_row):
        if wx.get(key) is None:
            return False

    row = build_row(wx, now)
    if row["timestamp_sast"] is None:
        return False

    ensure_header(path, ",".join(columns) + "\n")
    line = format_row(row, columns, precision)

    previous = last_logged_fields(path)
    if previous is not None and len(previous) == len(columns):
        fields = line.rstrip("\n").split(",")
        unchanged = _measurements(fields, columns) == _measurements(previous, columns)
        if unchanged and not _heartbeat_due(previous[columns.index("time")], now):
            return False

    with open(path, "a") as fp:
        fp.write(line)
    return True


def log_saao_io(path, wx, now):
    """Append a SAAO IO reading to ``path``. See `log_reading`."""
    return log_reading(path, wx, saao_io_row, SAAO_IO_COLUMNS, now)


def log_salt(path, wx, now):
    """Append a SALT reading to ``path``. See `log_reading`."""
    return log_reading(path, wx, salt_row, SALT_COLUMNS, now)
