#!/usr/bin/env python

import sys
from pathlib import Path
import time

import logging
import logging.handlers

log = logging.getLogger("HDIMM")
log.setLevel(logging.INFO)

handler = logging.handlers.WatchedFileHandler(Path.home() / "hdimm.log")
formatter = logging.Formatter("%(asctime)s - %(name)s - %(levelname)s - %(message)s")
handler.setFormatter(formatter)
log.addHandler(handler)

log.info("Running post-job; sleeping 10 sec...")
time.sleep(10)

sys.exit(0)
