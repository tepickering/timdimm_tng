"""Read the last complete row of a CSV that is being appended to."""

import csv
import io
import subprocess
from pathlib import Path


def last_csv_row(path):
    """
    The last complete data row of a CSV, as a dict keyed by column.

    The files this reads are appended to while they are polled, so the final line is regularly
    half written. Such a line is skipped in favour of the one before it rather than returned with
    missing fields, and anything unreadable comes back as ``None`` -- callers must keep going
    whatever the loggers are doing.

    Parameters
    ----------
    path : ~pathlib.Path
        The CSV to read.

    Returns
    -------
    dict or None
        The last complete row, or ``None`` if the file is absent, empty, header-only, or holds no
        complete row.
    """
    path = Path(path)
    if not path.exists():
        return None

    try:
        with path.open() as fp:
            header = fp.readline().strip()
        if not header:
            return None
        result = subprocess.run(
            ["tail", "-5", str(path)], capture_output=True, text=True, timeout=5,
        )
    except (OSError, subprocess.SubprocessError):
        return None

    columns = header.split(",")
    reader = csv.DictReader(io.StringIO(header + "\n" + result.stdout), fieldnames=columns)
    complete = [
        row for row in reader
        if row.get(columns[0]) != columns[0]                     # skip the header if tail caught it
        and None not in row.values() and None not in row         # no short row, no extra fields
    ]
    return dict(complete[-1]) if complete else None
