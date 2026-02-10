#!/usr/bin/env python

import sys
from pathlib import Path
import logging
import logging.handlers

from timdimm_tng.ox_wagon import OxWagon


log = logging.getLogger("timDIMM")
log.setLevel(logging.INFO)

handler = logging.handlers.WatchedFileHandler(Path.home() / "timdimm.log")
formatter = logging.Formatter("%(asctime)s - %(name)s - %(levelname)s - %(message)s")
handler.setFormatter(formatter)
log.addHandler(handler)

dome = OxWagon()

dome.open()

log.info("Starting up timDIMM observing session...")

sys.exit(0)
