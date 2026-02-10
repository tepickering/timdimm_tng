#!/usr/bin/env python

import sys
from pathlib import Path
import logging
import logging.handlers

from timdimm_tng.ox_wagon import OxWagon


log = logging.getLogger("timDIMM")
log.setLevel(logging.INFO)

handler = logging.handlers.WatchedFileHandler(Path.home() / "ox_wagon.log")
formatter = logging.Formatter("%(asctime)s - %(name)s - %(levelname)s - %(message)s")
handler.setFormatter(formatter)
log.addHandler(handler)

dome = OxWagon()

with open(Path.home() / "ox_wagon_status.txt", 'r') as coords:
    str = coords.readline()

str = str[0] + ' 1 ' + str[4:]

with open(Path.home() / "ox_wagon_status.txt", 'w') as coords:
    coords.truncate()
    coords.write(str)

log.info("Resetting Ox Wagon...")

resp = dome.reset()

log.info(f"Ox Wagon reset response: {resp}")

log.info("Opening Ox Wagon...")

resp = dome.open()

log.info(f"Ox Wagon open response: {resp}")

sys.exit(0)
