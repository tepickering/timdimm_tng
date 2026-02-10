#!/usr/bin/env python

import sys
from pathlib import Path
import logging
import logging.handlers
import time

log = logging.getLogger("timDIMM")
log.setLevel(logging.INFO)

handler = logging.handlers.WatchedFileHandler(Path.home() / "timdimm.log")
formatter = logging.Formatter("%(asctime)s - %(name)s - %(levelname)s - %(message)s")
handler.setFormatter(formatter)
log.addHandler(handler)

log.info(f"Running post-job...")
time.sleep(30)

sys.exit(0)
