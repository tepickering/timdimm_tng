#!/usr/bin/env python

"""
When ekos is running with the dome scripting interface active, this script gets run every couple of seconds.
As such, this is a good place to do overall monitoring of conditions.
"""

import sys
import json
import time

from pathlib import Path
import logging
import logging.handlers

import sdbus

from astropy.time import Time
from astropy.coordinates import get_sun, AltAz
import astropy.units as u

from timdimm_tng.locations import SAAO

from timdimm_tng.ox_wagon import OxWagon
from timdimm_tng.dbus.scheduler import Scheduler
from timdimm_tng.dbus.mount import Mount
from timdimm_tng.dbus.indi import INDI
from timdimm_tng.dbus.ekos import Ekos
from timdimm_tng.dbus.dome import Dome

from timdimm_tng.wx.check_wx import get_current_conditions


bus = sdbus.sd_bus_open_user()

scheduler = Scheduler(bus=bus)
mount = Mount(bus=bus)
indi = INDI(bus=bus)
ekos = Ekos(bus=bus)
dome = Dome(bus=bus)

log = logging.getLogger("timDIMM")
log.setLevel(logging.INFO)

handler = logging.handlers.WatchedFileHandler(Path.home() / "ox_wagon.log")
formatter = logging.Formatter("%(asctime)s - %(name)s - %(levelname)s - %(message)s")
handler.setFormatter(formatter)
log.addHandler(handler)

script, path = sys.argv

roof_status = Path.home() / "roof_status.json"

if roof_status.exists():
    with open(roof_status, 'r') as fp:
        roof_status = json.load(fp)
else:
    roof_status = {}
    roof_status['roof_status'] = {}

wx_message = ""
open_ok = False

sun_coord = get_sun(Time.now())
sun_azel = sun_coord.transform_to(AltAz(obstime=Time.now(), location=SAAO))

# check weather and if SALT or MONET think it's safe to open
try:
    wx, safety_checks = get_current_conditions()

    # if safety_checks['monet']:
    #     open_ok = True
    #     log.info("MONET safety check passed. Safe to open.")
    #     wx_message += "MONET says it's ok to open; "

    if safety_checks['salt']:
        open_ok = True
        log.info("SALT safety check passed. Safe to open.")
        wx_message += "SALT says it's ok to open; "

except Exception as e:
    log.error(f"Can't get current conditions: {e}")
    open_ok = False

# set the safety limit to civil twilight, -6 degrees.
# needs to be dark enough for autoguiding to be happy.
if sun_azel.alt > -6 * u.deg:
    open_ok = False
    if sun_azel.alt > 0 * u.deg:
        msg = f"Sun is up: {sun_azel.alt: .1f} above the horizon; "
        log.info(msg)
        wx_message += msg
    else:
        msg = f"Early twilight: sun is at {sun_azel.alt: .1f}; "
        log.info(msg)
        wx_message += msg

stopfile = Path.home() / "STOP"
if stopfile.exists():
    open_ok = False
    log.info("Manual stop forced")
    wx_message += "Manual stop forced"

if open_ok:
    wx_message = "Safe conditions according to either SALT or MONET"
    log.info("Safe to be open")
    try:
        log.info("Sending ox wagon open command to keep it open...")
        o = OxWagon()
        o.command('RESET', debug=False)
        time.sleep(2)
        o.command('OPEN', debug=False)
    except Exception as e:
        log.info(f"Can't access ox wagon: {e}")
    if not scheduler.status:
        log.info("Scheduler stopped. Restarting...")
        scheduler.reset_all_jobs()
        scheduler.load_scheduler(str(Path.home() / "timdimm_tng" / "timdimm_schedule.esl"))
        scheduler.start()
        # make sure meridian flips are enabled within ekos. the dbus api says "hours"
        # for this argument, but it's labeled as "deg" in the ekos interface. unsure
        # which is correct, but this is less than what's configured within the mount's
        # firmware which is all that matters so that ekos triggers the flip before the
        # mount does.
        mount.set_meridian_flip_values(activate=False, hours=1.0)  # need to toggle when doing this manually
        mount.set_meridian_flip_values(activate=True, hours=1.0)
else:
    log.info("Unsafe conditions. Not ok to be open...")

    try:
        log.info("Make sure oxwagon close command is sent...")
        o = OxWagon()
        o.command('CLOSE', debug=False)
    except Exception as e:
        log.info(f"Can't access ox wagon: {e}")

    # if we're still not clear to be open, make sure we're parked and closed
    try:
        if scheduler.status:
            log.info("Not ok to open, but scheduler running. Stopping...")
            scheduler.stop()
    except Exception as e:
        log.info(f"Can't query scheduler status: {e}")

    try:
        if mount.park_status != 1:
            log.info("Not ok to open, but mount not parked. Parking telescope...")
            mount.park()
    except Exception as e:
        log.info(f"Can't park mount: {e}")
        log.info(f"Parked status: {mount.park_status}")

# update and write out roof status
roof_status['roof_status']['open_ok'] = open_ok
roof_status['roof_status']['reasons'] = wx_message

with open(Path.home() / "roof_status.json", 'w') as fp:
    json.dump(roof_status, fp, indent=4)

with open(Path.home() / "ox_wagon_status.txt", 'r') as coords:
    ox_wagon = coords.readline()
    with open(path, 'w') as indistat:
        indistat.truncate()
        indistat.write(ox_wagon)

log.info(f"Ox Wagon status: {ox_wagon.strip()}")

sys.exit(0)
