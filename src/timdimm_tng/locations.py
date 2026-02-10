from astropy.coordinates import EarthLocation
import astropy.units as u


__all__ = ["MMTO", "SAAO"]


MMTO = EarthLocation.from_geodetic("-110:53:04.4", "31:41:19.6", 2600 * u.m)
SAAO = EarthLocation.from_geodetic("20:48:38.4", "-32:22:33.6", 1798 * u.m)
