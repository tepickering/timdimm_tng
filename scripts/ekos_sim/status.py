#!/usr/bin/env python

"""
When ekos is running with the dome scripting interface active, this script gets run every couple of seconds.
As such, this is a good place to do overall monitoring of conditions.
"""

import sys
import json
from pathlib import Path
import logging
import logging.handlers

import sdbus

from astropy.time import Time
import astropy.units as u

from timdimm_tng.dbus.scheduler import EkosSchedulerInterface
from timdimm_tng.dbus.mount import EkosMountInterface
from timdimm_tng.dbus.indi import INDIInterface
from timdimm_tng.dbus.ekos import EkosInterface

bus = sdbus.sd_bus_open_user()

scheduler = EkosSchedulerInterface(bus=bus)
mount = EkosMountInterface(bus=bus)
indi = INDIInterface(bus=bus)
ekos = EkosInterface(bus=bus)

log = logging.getLogger("timDIMM")
log.setLevel(logging.INFO)

handler = logging.handlers.WatchedFileHandler(Path.home() / "ox_wagon.log")
formatter = logging.Formatter("%(asctime)s - %(name)s - %(levelname)s - %(message)s")
handler.setFormatter(formatter)
log.addHandler(handler)

script, path = sys.argv

with open(Path.home() / "roof_status.json", 'r') as fp:
    roof_status = json.load(fp)

last_bad = Time(roof_status['last_bad'], format='isot')
wx_message = ""
open_ok = True

# placeholder, query SAAO wx stations in operation
wx_status = {
    'rh': 95.0,
    'temp': 5.0,
    'wind': 25.0,
    'precip': False,
    'cloudy': False
}

# humidity limit of 90%
if wx_status['rh'] >= 90.0:
    open_ok = False
    wx_message += f"High RH = {wx_status['rh']: .1f}%; "

# temp limit of -5 C
if wx_status['temp'] <= -5.0:
    open_ok = False
    wx_message += f"Too cold. T = {wx_status['temp']: .1f}; "

# wind limit of 50 kph
if wx_status['wind'] >= 50.0:
    open_ok = False
    wx_message += f"Too windy, wind = {wx_status['wind']: .1f} kph; "

# LCO only good precip sensor and not always timely
if wx_status['precip']:
    open_ok = False
    wx_message += "Precip detected; "

# LCO only cloud sensor and not always timely
if wx_status['cloudy']:
    open_ok = False
    wx_message += "Too cloudy"

if not open_ok:
    last_bad = Time.now()

safe_period = 5 * u.min

last_bad_diff = (Time.now() - last_bad)
if open_ok and last_bad_diff > safe_period:
    wx_message = "Safe to open"
    if scheduler.status == 0:
        log.info("Safe to open, but scheduler stopped. Restarting...")
        scheduler.start()
elif open_ok and last_bad_diff <= safe_period:
    open_ok = False
    wx_message = f"Only safe for the last {last_bad_diff.to(u.min): .1f}"

# update and write out roof status
roof_status['last_bad'] = last_bad.isot
roof_status['roof_status']['open_ok'] = open_ok
roof_status['roof_status']['reasons'] = wx_message

with open(Path.home() / "roof_status.json", 'w') as fp:
    json.dump(roof_status, fp, indent=4)

with open(Path.home() / "ox_wagon_status.txt", 'r') as coords:
    ox_wagon = coords.readline()
    with open(path, 'w') as indistat:
        indistat.truncate()
        indistat.write(ox_wagon)

# log.info(f"Ox Wagon status: {ox_wagon.strip()}")

sys.exit(0)
