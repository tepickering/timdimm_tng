#!/usr/bin/env python

"""
When ekos is running with the dome scripting interface active, this script gets run every couple of seconds.
As such, this is a good place to do overall monitoring of conditions.
"""

import sys
import json
import time
from datetime import UTC, datetime

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
from timdimm_tng.wx.csv_log import log_saao_io, log_salt
from timdimm_tng.wx.adafruit import (
    HUMIDITY_LIMIT,
    latest_measurement,
    measurement_is_stale,
    measurement_requires_closure,
)
from timdimm_tng.wx.dewing import (
    DEW_WARNING_HUMIDITY,
    REOPEN_DRY_PERIOD,
    REOPEN_HUMIDITY,
    DewingState,
    clear_state,
    humidity_is_warning,
    latest_throughput,
    load_state,
    save_state,
    throughput_requires_closure,
    update_reopen,
)


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

# check weather and if SALT or SAAO IO think it's safe to open
try:
    wx, safety_checks = get_current_conditions()

    # SAAO archives this weather in databases we can't query, so the only record we get to keep is
    # the one written here as the readings go past. Its own try/except: a full disk must never stop
    # the roof from closing. Rows are keyed on each station's clock, so this loop's ~2 s cadence
    # collapses to the station's real one, roughly a row a minute.
    try:
        now = Time.now().isot
        if log_saao_io(Path.home() / "saao_io.csv", wx["SAAO-IO"], now):
            log.debug("Logged a SAAO IO reading.")
        if log_salt(Path.home() / "salt_wx.csv", wx["SALT"], now):
            log.debug("Logged a SALT reading.")
    except Exception as e:
        log.warning(f"Can't log weather conditions: {e}")

    saao_open_ok = False
    salt_open_ok = False

    if wx["SAAO-IO"]["Valid"]:
        if safety_checks["humidity"] and safety_checks["wind"]:
            saao_open_ok = True
            log.info("RH and wind safety checks from SAAO IO passed. Safe to open.")
            wx_message += "SAAO IO says it's ok to open; "
        else:
            log.warning(
                f"Weather conditions unsafe according to SAAO IO: "
                f"Wind={wx['SAAO-IO']['wind']} RH={wx['SAAO-IO']['humidity']}"
            )
    else:
        log.warning("SAAO IO weather data invalid.")

    if wx["SALT"]["Valid"]:
        if wx["SALT"]["Open"]:
            salt_open_ok = True
            log.info("SALT says it's safe to open.")
            wx_message += "SALT says it's ok to open; "
        else:
            log.warning("SALT isn't open.")
    else:
        log.warning("SALT weather data invalid.")

    # final decision: if either station says it's ok, we're ok to be open
    # open_ok = saao_open_ok or salt_open_ok
    open_ok = salt_open_ok  # or saao_open_ok
except Exception as e:
    log.error(f"Can't get current conditions: {e}")
    open_ok = False

# the SHT45 humidity that the dewing hold below may use: None unless the reading is fresh
sht45_humidity = None

try:
    adafruit_measurement = latest_measurement()
    adafruit_humidity = adafruit_measurement.humidity

    now = datetime.now(UTC)
    if measurement_is_stale(adafruit_measurement.timestamp, now=now):
        age_minutes = (now - adafruit_measurement.timestamp).total_seconds() / 60
        log.warning(f"SHT45 measurement is stale: age={age_minutes:.1f} minutes")
        wx_message += f"SHT45 data is {age_minutes:.1f} minutes old and ignored; "
    elif measurement_requires_closure(adafruit_measurement, now=now):
        sht45_humidity = adafruit_humidity
        open_ok = False
        log.warning(f"SHT45 humidity is unsafe: RH={adafruit_humidity:.1f}% is at or above {HUMIDITY_LIMIT:.1f}%")
        wx_message += f"SHT45 RH={adafruit_humidity:.1f}% is too high; "
    elif humidity_is_warning(adafruit_humidity):
        # the prism dews from about here on, well under the closure limit: the throughput check
        # below is what acts on it, this only says so
        sht45_humidity = adafruit_humidity
        log.warning(
            f"SHT45 RH={adafruit_humidity:.1f}% is at or above {DEW_WARNING_HUMIDITY:.0f}%: "
            f"the prism may start dewing"
        )
        wx_message += f"SHT45 RH={adafruit_humidity:.1f}% is in the dewing warning zone; "
    else:
        sht45_humidity = adafruit_humidity
        log.info(f"SHT45 humidity safety check passed: RH={adafruit_humidity:.1f}%")
        wx_message += f"SHT45 RH={adafruit_humidity:.1f}% is safe; "
except (OSError, UnicodeError, ValueError) as e:
    log.warning(f"Can't read SHT45 humidity: {e}")
    wx_message += "SHT45 humidity unavailable and ignored; "

# Dewing protocol: the prism aperture losing its light is the one direct measurement of condensation
# on the optics, and it shows up while both humidity sensors still read under their limits. A
# throughput at or below the closure threshold shuts the roof; it then stays shut until SALT and the
# SHT45 have both read dry for a sustained period, since the humidity limits alone reopened onto a
# still-wet prism on 2026-08-31.
dewing_file = Path.home() / "DEWING"
try:
    dewing = load_state(dewing_file)
    reading = latest_throughput(Path.home() / "scintillation.csv")
    if dewing is None and throughput_requires_closure(reading):
        dewing = DewingState(closed_at=datetime.now(UTC), throughput=reading.value, target=reading.target)
        save_state(dewing, dewing_file)
        log.warning(
            f"Prism throughput {reading.value:.3f} on {reading.target} says the optics are dewing. Closing."
        )

    if dewing is not None:
        salt_humidity = None
        try:
            if wx["SALT"]["Valid"]:
                salt_humidity = float(wx["SALT"]["Rel_Hum"])
        except (KeyError, NameError, TypeError, ValueError):
            pass
        dewing, may_reopen = update_reopen(dewing, salt_humidity, sht45_humidity)
        if may_reopen:
            clear_state(dewing_file)
            log.info(
                f"Both humidity sensors have read {REOPEN_HUMIDITY:.0f}% or below for "
                f"{REOPEN_DRY_PERIOD.total_seconds() / 60:.0f} minutes. Dewing hold lifted."
            )
        else:
            save_state(dewing, dewing_file)
            open_ok = False
            if dewing.dry_since is None:
                progress = "waiting for both sensors to read dry"
            else:
                dry_minutes = (datetime.now(UTC) - dewing.dry_since).total_seconds() / 60
                progress = f"dry for {dry_minutes:.0f} of {REOPEN_DRY_PERIOD.total_seconds() / 60:.0f} minutes"
            log.info(f"Dewing hold since {dewing.closed_at.isoformat(timespec='minutes')}: {progress}")
            wx_message += f"Prism dewed (throughput {dewing.throughput:.2f}), {progress}; "
except Exception as e:
    log.warning(f"Dewing check failed: {e}")

# set the safety limit to nautical twilight, -12 degrees.
# needs to be dark enough for autoguiding to be happy.
# also needs to close early enough to not keep SALT night crew waiting.
if sun_azel.alt > -12 * u.deg:
    open_ok = False
    if sun_azel.alt > 0 * u.deg:
        msg = f"Sun is up: {sun_azel.alt: .1f} above the horizon; "
        log.info(msg)
        wx_message += msg
    else:
        msg = f"Early twilight: sun is at {sun_azel.alt: .1f}; "
        log.info(msg)
        wx_message += msg
else:
    log.info(f"Sun is down: {sun_azel.alt: .1f} below the horizon.")

close_file = Path.home() / "CLOSED"
if close_file.exists():
    with open(close_file, 'r') as fp:
        closed_time = Time(fp.read().strip())
    td = Time.now() - closed_time
    if td < 5 * u.minute:
        open_ok = False
        wx_message += "Recently closed; "
        log.info("Recently closed, keeping closed for now.")
    else:
        close_file.unlink()
        log.info("Removed CLOSED file after being closed for more than 5 minutes.")

stopfile = Path.home() / "STOP"
if stopfile.exists():
    open_ok = False
    log.info("Manual stop forced")
    wx_message += "Manual stop forced"

if open_ok:
    wx_message = "Safe conditions according to either SALT or SAAO IO"
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
        try:
            if mount.park_status == 1:
                log.info("OK to open, but mount is parked. Unparking telescope...")
                mount.unpark()
        except Exception as e:
            log.info(f"Can't unpark mount: {e}")

        log.info(f"Parked status: {mount.park_status}")
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

    if not close_file.exists():
        with open(close_file, 'w') as fp:
            fp.write(Time.now().isot)

    try:
        log.info("Make sure oxwagon close command is sent...")
        o = OxWagon()
        # ox wagon can get into state where drop roof reports both "open" and "moving".
        # this prevents the ox wagon from closing. sending "RESET" clears that up.
        ox_state = o.status()
        if ox_state.get("Drop Roof Moving") and ox_state.get("Drop Roof Opened"):
            log.info("Drop roof reports both moving and open. Sending RESET to clear stuck state...")
            o.command('RESET', debug=False)
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

# this is the status in the format INDI wants
with open(Path.home() / "roof_status.json", 'w') as fp:
    json.dump(roof_status, fp, indent=4)

# this is in a format another part of INDI wants
with open(Path.home() / "ox_wagon_status.txt", 'r') as coords:
    ox_wagon = coords.readline()
    with open(path, 'w') as indistat:
        indistat.truncate()
        indistat.write(ox_wagon)

log.info(f"Ox Wagon status: {ox_wagon.strip()}")

# dump the full status of the ox wagon for displaying on the web interface and for debugging
json.dump(o.status(), open(Path.home() / "ox_wagon_status.json", 'w'), indent=4)

sys.exit(0)
