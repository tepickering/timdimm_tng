#!/usr/bin/env python

import sys
from pathlib import Path
import logging
import logging.handlers

log = logging.getLogger("HDIMM")
log.setLevel(logging.INFO)

script, az = sys.argv

handler = logging.handlers.WatchedFileHandler(Path.home() / "hdimm.log")
formatter = logging.Formatter("%(asctime)s - %(name)s - %(levelname)s - %(message)s")
handler.setFormatter(formatter)
log.addHandler(handler)

with open(Path.home() / "hdimm_status.txt", 'r') as coords:
    str = coords.readline()

str = str[0:3] + az

with open(Path.home() / "hdimm_status.txt", 'w') as coords:
    coords.truncate()
    coords.write(str)

log.info(f"HDIMM receiving slew command to {az}...")

sys.exit(0)
