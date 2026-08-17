#!/usr/bin/env python

import sys
import json
import time
import os

from pathlib import Path
import logging
import logging.handlers

import numpy as np

from astropy.time import Time, TimezoneInfo
import astropy.units as u
from photutils.aperture import ApertureStats

from timdimm_tng.indi import INDI_Camera
from timdimm_tng.ser import load_ser_file
from timdimm_tng.analyze_cube import (
    DIMM_IMAGE_SHAPE,
    MIN_CADENCE_HZ,
    find_apertures,
    analyze_dimm_cube,
)
from timdimm_tng.scintillation import ensure_header, format_row, scintillation_stats


log = logging.getLogger("timDIMM")
log.setLevel(logging.INFO)

handler = logging.handlers.WatchedFileHandler(Path.home() / "timdimm.log")
formatter = logging.Formatter("%(asctime)s - %(name)s - %(levelname)s - %(message)s")
handler.setFormatter(formatter)
log.addHandler(handler)

log.info("Running post-capture script to collect seeing data...")

# grab the pointing status
with open(Path.home() / "pointing_status.json", 'r') as fp:
    pointing_status = json.load(fp)

# open and configure the camera
cam = INDI_Camera("ZWO CCD ASI432MM")
cam.ser_mode()

# need to toggle video stream on and off to get camera out of a "stuck" state
# it can get into, apparently. when in the state, the record_frames/record_duration
# methods will generate INDI warnings saying "recording device is busy". toggling
# video stream in kstars cleared it and these INDI commands perform the same function.
cam.set_prop("CCD_VIDEO_STREAM", "STREAM_ON", value="On")
time.sleep(2)
cam.set_prop("CCD_VIDEO_STREAM", "STREAM_OFF", value="On")
time.sleep(1)

# grab a short full-frame cube
cam.stream_exposure(0.005)
cam.set_ROI(0, 0, 1608, 1104)
cam.record_frames(10, savedir="/home/timdimm", filename="find_boxes.ser")
time.sleep(3)
aperture_data = load_ser_file("/home/timdimm/find_boxes.ser")
aperture_image = np.mean(aperture_data['data'], axis=0)
aps = find_apertures(aperture_image, threshold=35, brightest=2)
ap_stats = ApertureStats(aperture_image, aps[0])
centroids = ap_stats.centroid
if len(centroids) != 2:
    log.warning("Failed to find two apertures.")
    sys.exit(0)

x, y = np.mean(ap_stats.centroid, axis=0)

# center apertures in a 400x400 ROI and grab a 15 second cube
if ap_stats.max.min() < 1500:
    exptime = 0.002
else:
    exptime = 0.001

cam.stream_exposure(exptime)
left = max(1, int(x - 200))
top = max(1, int(y - 200))
left = min(left, 1608 - 400)
top = min(top, 1104 - 400)
cam.set_ROI(left, top, 400, 400)
time.sleep(3)
cam.record_duration(15, savedir="/home/timdimm", filename="seeing.ser")
time.sleep(17)
log.info(f"ROI: X=[{left}:{left+400}], Y=[{top}:{top+400}]; exptime: {exptime}")

try:
    seeing_data = analyze_dimm_cube("/home/timdimm/seeing.ser", airmass=pointing_status['airmass'])
except Exception as e:
    log.error(f"Seeing analysis failed: {e}")
    os.system("mv ~/seeing.ser ~/last_bad_seeing.ser")
    sys.exit(0)

# one timestamp, shared by both files, so scintillation.csv joins seeing.csv on it exactly
now = Time.now().isot
target = pointing_status['target']

# written outside the seeing quality gate below: a dewing prism is what this measures, and it is
# also what makes the seeing analysis fail, so gating on the seeing row would lose exactly the
# measurements we want
try:
    scint = scintillation_stats(seeing_data)
    scint_file = Path.home() / "scintillation.csv"
    # rotates the file aside if its header predates a column change, rather than appending rows
    # the header no longer describes
    ensure_header(scint_file)
    with open(scint_file, 'a') as fp:
        fp.write(format_row(scint, now, target, exptime, pointing_status['airmass']))
    log.info(
        f"Throughput: {scint['throughput']:.3f}; scint index: {scint['scint_index_raw']:.3f}; "
        f"tau_motion: {scint['tau_motion_ms']:.2f} ms; kept {scint['n_kept']}/{scint['n_frames']}"
    )
except Exception as e:
    log.error(f"Scintillation analysis failed: {e}")

# The lower bound matters as much as the upper one. A degenerate cube used to yield a baseline of
# exactly zero and so a seeing of exactly 0.00, which passed `< 10.0` and was written as real data:
# seeing.csv holds 357 such rows between 2024-10 and 2026-07. analyze_dimm_cube now refuses those
# cubes outright, but nothing downstream should accept a sub-arcsecond-floor seeing regardless.
MIN_SEEING = 0.1  # arcsec; the site has never delivered better than ~0.5

# ...and a seeing bound alone does not separate them. The 12 surviving sub-arcsecond values in the
# archive all come from slow, small test cubes, whose baseline scatter is not image motion at all.
# `seeing_valid` rejects those on configuration, before their number is ever compared to a bound.
# The scintillation row above is written regardless: throughput does not care about the cadence.
if not seeing_data['seeing_valid']:
    # A production cube arriving here is a hardware alert, not a routine skip: the camera should
    # always be 400x400 well above 200 Hz, and a slow one means it came up on a USB 2.x bus.
    log.warning(
        f"Not logging seeing: cube is {seeing_data['image_shape']} at "
        f"{seeing_data['cadence_hz']:.1f} Hz, not {DIMM_IMAGE_SHAPE} at the "
        f"{MIN_CADENCE_HZ:.0f} Hz minimum seeing needs. Check the camera's USB connection."
    )
    # moved aside like every other rejected cube: the next exposure records to this same fixed
    # filename, so leaving it here throws away the one cube that shows what the camera was doing
    os.system("mv ~/seeing.ser ~/last_bad_seeing.ser")
elif np.isfinite(seeing_data['seeing'].value) and MIN_SEEING < seeing_data['seeing'].value < 10.0:
    log.info(f"Seeing: {seeing_data['seeing']:.2f}; N bad: {seeing_data['N_bad']}")
    if seeing_data['N_bad'] < 50:
        csv_file = Path.home() / "seeing.csv"
        if not csv_file.exists():
            with open(csv_file, 'w') as fp:
                fp.write("time,target,seeing,airmass,azimuth,exptime\n")

        with open(csv_file, 'a') as fp:
            z = pointing_status['airmass']
            azimuth = pointing_status['az']
            seeing = seeing_data['seeing'].value
            fp.write(
                f"{now},{target},{seeing:.3f},{z:.3f},{azimuth:.1f},{exptime}\n"
            )

        with open(Path.home() / "seeing.txt", 'w') as f:
            print(f"{seeing_data['seeing'].value:.2f}", file=f)
            tobs = seeing_data['frame_times'][-1].to_datetime(
                timezone=TimezoneInfo(2 * u.hour)
            ).isoformat(timespec='seconds')
            print(tobs, file=f)

        # os.system("scp -q /home/timdimm/seeing.txt massdimm@seeing.suth.saao.ac.za:~/timDIMM/.")
        os.system("mv ~/seeing.ser ~/last_good_seeing.ser")
    else:
        log.warning("Too many bad frames in seeing data.")
        os.system("mv ~/seeing.ser ~/last_bad_seeing.ser")

else:
    log.warning("Analysis of seeing data failed.")
    os.system("mv ~/seeing.ser ~/last_bad_seeing.ser")

sys.exit(0)
