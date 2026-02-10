#!/usr/bin/env python

import sys
from pathlib import Path
import logging
import logging.handlers
import time

import sdbus

from timdimm_tng.ox_wagon import OxWagon
from timdimm_tng.dbus.mount import Mount

log = logging.getLogger("timDIMM")
log.setLevel(logging.INFO)

handler = logging.handlers.WatchedFileHandler(Path.home() / "ox_wagon.log")
formatter = logging.Formatter("%(asctime)s - %(name)s - %(levelname)s - %(message)s")
handler.setFormatter(formatter)
log.addHandler(handler)

# before opening ox wagon, configure the mount to activate meridian flips from within ekos.
# this is required to get alignment and guiding tasks to run after the flip is performed.
# by default, ekos will have a checkbox checked saying this is enabled within the mount tab,
# but it actually is not as reported by the interface. running this command does the same thing
# as toggling the checkbox in the ekos interface.
bus = sdbus.sd_bus_open_user()
mount = Mount(bus=bus)
mount.set_meridian_flip_values(activate=True, hours=1.0)

dome = OxWagon()

dome.reset()
dome.open()

log.info("Unparking Ox Wagon...")

with open(Path.home() / "ox_wagon_status.txt", 'w') as coords:
    coords.truncate()
    coords.write('0 0 0.0')

log.info("Ox Wagon unparked and open...")

sys.exit(0)
