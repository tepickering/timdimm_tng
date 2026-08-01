"""
Correct for the boresight misalignment between the guide scope and the main telescope camera.

Pointing is done by plate solving the guide scope, which centers the target in the guide scope
rather than on the main camera. The two are rigidly coupled but not co-aligned, so the target
lands off-center on the main camera by a fixed angle. Because that angle is fixed in the
telescope frame, on a German equatorial it appears on the sky as a pure hour angle offset that
flips sign across a meridian flip and grows as 1/cos(dec) -- classic collimation/cone error.

The correction is applied to the coordinates the align module converges on, which is the only
lever that survives guiding: guiding locks onto the star wherever align left it, so a mount
offset applied after guiding starts just gets pulled back out.
"""

import logging
import logging.handlers
import time
from pathlib import Path

import numpy as np

from astropy.coordinates import Angle
import astropy.units as u


# Main telescope and its camera
FOCAL_LENGTH = 2500 * u.mm
PIXEL_SIZE = 9 * u.um
CHIP_WIDTH = 1608
CHIP_HEIGHT = 1104

# Where a target centered in the guide scope lands on the main camera. Measured 2026-07-31.
STAR_X = 1030
STAR_Y = 940

# Ekos::ISD::Mount::PierSide. PIER_WEST means the OTA is on the west side of the pier, which is
# how it sits when pointing east of the meridian.
PIER_UNKNOWN = -1
PIER_WEST = 0
PIER_EAST = 1

# Ekos::AlignState
ALIGN_IDLE = 0
ALIGN_COMPLETE = 1
ALIGN_FAILED = 2
ALIGN_ABORTED = 3
ALIGN_PROGRESS = 4
ALIGN_SUCCESSFUL = 5
ALIGN_SYNCING = 6
ALIGN_SLEWING = 7
ALIGN_ROTATING = 8
ALIGN_SUSPENDED = 9

# states in which the align module is still converging and will act on a new target
ALIGN_ACTIVE = (ALIGN_PROGRESS, ALIGN_SYNCING, ALIGN_SLEWING, ALIGN_ROTATING)

# align takes several seconds per solve iteration, so a 1 s poll always lands a correction
# before it converges
POLL_INTERVAL = 1.0


def plate_scale():
    """
    Angular size of one main camera pixel
    """
    return Angle(np.arctan(PIXEL_SIZE / FOCAL_LENGTH).to(u.arcsec))


def boresight_separation():
    """
    Angle between the guide scope axis and the center of the main camera
    """
    dx = STAR_X - CHIP_WIDTH / 2
    dy = STAR_Y - CHIP_HEIGHT / 2
    return Angle(np.hypot(dx, dy) * plate_scale())


def ra_offset(dec, pier_side):
    """
    Signed RA offset needed to move the target from the guide scope axis to the center of the
    main camera. Positive is east. The sign follows the pier side and the magnitude grows as
    1/cos(dec). An unknown pier side yields no correction, which leaves the target near the edge
    of the chip rather than risking pushing it off.
    """
    if pier_side == PIER_WEST:
        sign = 1.0
    elif pier_side == PIER_EAST:
        sign = -1.0
    else:
        return Angle(0.0, unit=u.hourangle)

    return Angle(sign * boresight_separation() / np.cos(Angle(dec))).to(u.hourangle)


def corrected_target(ra, dec, pier_side):
    """
    Apply the boresight correction to a target coordinate, returning coordinates that put the
    target on the center of the main camera once the align module has converged on them.
    """
    hours = float(Angle(ra).hour) + float(ra_offset(dec, pier_side).hour)
    return Angle(hours % 24, unit=u.hourangle), Angle(dec)


class BoresightCorrector:
    """
    Decides when to push a corrected target at the align module.

    The align module iterates solve -> slew -> solve until it lands within tolerance of its
    target, so overwriting the target while it is converging is enough to steer it. Feeding it
    a target repeatedly is harmless, but re-correcting a target we already corrected is not, so
    we remember the target we started from and always recompute the correction from that.
    """

    def __init__(self, tolerance=1 * u.arcsec):
        self.tolerance = Angle(tolerance)
        self._base = None
        self._issued = None

    def _matches_issued(self, ra, dec):
        if self._issued is None or self._base is None:
            return False
        tol = float(self.tolerance.deg)
        return abs(ra - self._issued) * 15 < tol and abs(dec - self._base[1]) < tol

    def update(self, align_status, ra, dec, pier_side):
        """
        Given the current align state, its target coordinates and the mount's pier side, return
        the coordinates to hand back to the align module, or None to leave it alone.
        """
        if align_status not in ALIGN_ACTIVE:
            self._base = None
            self._issued = None
            return None

        if pier_side not in (PIER_WEST, PIER_EAST):
            return None

        if self._matches_issued(ra, dec):
            # these are our own coordinates coming back. nothing to do unless the mount flipped
            # underneath us, in which case we recorrect from the target we started with.
            assert self._base is not None
            if pier_side == self._base[2]:
                return None
            base_ra, base_dec, _ = self._base
        else:
            base_ra, base_dec = ra, dec

        corrected_ra, corrected_dec = corrected_target(
            base_ra * u.hourangle, base_dec * u.deg, pier_side
        )
        self._base = (base_ra, base_dec, pier_side)
        self._issued = float(corrected_ra.hour)
        return self._issued, float(corrected_dec.deg)


def main():
    """
    Watch the align module and steer it onto boresight-corrected coordinates.

    Align converges by iterating solve -> slew -> solve, so it is enough to overwrite its target
    while it is still working. We poll rather than subscribe because the correction only has to
    land before align's final convergence check, and polling keeps this decoupled from the
    scheduler's state machine.
    """
    import sdbus

    from timdimm_tng.dbus.align import Align
    from timdimm_tng.dbus.mount import Mount

    log = logging.getLogger("timDIMM")
    log.setLevel(logging.INFO)
    handler = logging.handlers.WatchedFileHandler(Path.home() / "timdimm.log")
    handler.setFormatter(
        logging.Formatter("%(asctime)s - %(name)s - %(levelname)s - %(message)s")
    )
    log.addHandler(handler)

    bus = sdbus.sd_bus_open_user()
    align = Align(bus=bus)
    mount = Mount(bus=bus)
    corrector = BoresightCorrector()

    log.info(
        f"Boresight corrector started; separation is {boresight_separation().to(u.arcmin):.2f}"
    )

    while True:
        try:
            status = int(align.status)
            ra, dec = align.get_target_coords()
            pier_side = int(mount.pier_side)

            correction = corrector.update(status, float(ra), float(dec), pier_side)
            if correction is not None:
                corrected_ra, corrected_dec = correction
                align.set_target_coords(corrected_ra, corrected_dec)
                shift = (corrected_ra - float(ra)) * 3600
                side = "west" if pier_side == PIER_WEST else "east"
                log.info(
                    f"Boresight correction on {side} side of pier: "
                    f"RA {ra:.6f} -> {corrected_ra:.6f} h ({shift:+.1f} s)"
                )
            elif status in ALIGN_ACTIVE and pier_side == PIER_UNKNOWN:
                log.warning("Align is running but pier side is unknown; no correction applied")
        except Exception as e:
            log.warning(f"Boresight corrector could not talk to Ekos: {e}")

        time.sleep(POLL_INTERVAL)
