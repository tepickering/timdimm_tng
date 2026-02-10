#!/usr/bin/env python

import json
import sys
from pathlib import Path
import logging
import logging.handlers

import sdbus

import numpy as np

from astropy import units as u

from timdimm_tng.dbus.capture import Capture
from timdimm_tng.dbus.mount import Mount

bus = sdbus.sd_bus_open_user()

mount = Mount(bus=bus)
capture = Capture(bus=bus)

log = logging.getLogger("HDIMM")
log.setLevel(logging.INFO)

handler = logging.handlers.WatchedFileHandler(Path.home() / "hdimm.log")
formatter = logging.Formatter("%(asctime)s - %(name)s - %(levelname)s - %(message)s")
handler.setFormatter(formatter)
log.addHandler(handler)

log.info("Running pre-job...")

try:
    az, el = float(mount.horizontal_coords[0]), float(mount.horizontal_coords[1])
    ra, dec = float(mount.equatorial_coords[0]), float(mount.equatorial_coords[1])
    ha = float(mount.hour_angle)
    target = capture.target_name
    airmass = 1. / np.sin(el * u.degree)
except Exception as e:
    log.error(f"Failed loading mount info: {e}")

log.info(f"Observing {target} at Az={az:.1f}°, El={el:.1f}°")

status = {
    'target': str(target),
    'az': az, # * u.degree,
    'el': el, # * u.degree,
    'ra': ra, # * u.hourangle,
    'dec': dec, # * u.degree,
    'ha': ha, # * u.hourangle,
    'airmass': float(airmass)
}

with open(Path.home() / "pointing_status.json", 'w') as fp:
    fp.write(json.dumps(status, indent=4))

sys.exit(0)
