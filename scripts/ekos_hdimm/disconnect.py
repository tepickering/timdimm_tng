#!/usr/bin/env python

import sys
from pathlib import Path
import logging
import logging.handlers

from timdimm_tng.ox_wagon import OxWagon


log = logging.getLogger("HDIMM")
log.setLevel(logging.INFO)

handler = logging.handlers.WatchedFileHandler(Path.home() / "hdimm.log")
formatter = logging.Formatter("%(asctime)s - %(name)s - %(levelname)s - %(message)s")
handler.setFormatter(formatter)
log.addHandler(handler)

log.info("HDIMM disconnected")

sys.exit(0)
