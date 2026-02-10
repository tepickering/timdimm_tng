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

log.info("Ox Wagon disconnected")

state = dome.status()

for k, v in state.items():
    log.info("%30s : \t %s" % (k, v))

sys.exit(0)
