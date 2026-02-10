#!/usr/bin/env python

import sys
from pathlib import Path
import logging
import logging.handlers


log = logging.getLogger("HDIMM")
log.setLevel(logging.INFO)

handler = logging.handlers.WatchedFileHandler(Path.home() / "hdimm.log")
formatter = logging.Formatter("%(asctime)s - %(name)s - %(levelname)s - %(message)s")
handler.setFormatter(formatter)
log.addHandler(handler)

log.info("Parking HDIMM...")

with open(Path.home() / "hdimm_status.txt", 'w') as coords:
    coords.truncate()
    coords.write('1 0 0.0')

log.info("HDIMM parked and closed...")

sys.exit(0)
