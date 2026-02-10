#!/usr/bin/env python

import sys
from pathlib import Path
import logging
import logging.handlers
import time

log = logging.getLogger("timDIMM")
log.setLevel(logging.INFO)

handler = logging.handlers.WatchedFileHandler(Path.home() / "ox_wagon.log")
formatter = logging.Formatter("%(asctime)s - %(name)s - %(levelname)s - %(message)s")
handler.setFormatter(formatter)
log.addHandler(handler)

log.info(f"Unparking Ox Wagon...")
time.sleep(60)

with open(Path.home() / "ox_wagon_status.txt", 'w') as coords:
    coords.truncate()
    coords.write('0 0 0.0')

log.info(f"Ox Wagon unparked and open...")

sys.exit(0)
