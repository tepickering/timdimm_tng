# -*- coding: utf-8 -*-

import astropy.units as u
from astropy.time import Time

#from timdimm_tng.wx.lcogt_weather import get_weather as lcogt_wx
# from timdimm_tng.wx.lcogt_bwc2_weather import get_weather as lcogt_bwc2_wx
# from timdimm_tng.wx.gfz_weather import get_weather as gfz_wx
# from timdimm_tng.wx.monet_weather import parse_monet as monet_wx
from timdimm_tng.wx.salt_weather_xml import parse_salt_xml as salt_wx
from timdimm_tng.wx.saao_io import parse_saao_io as saao_io_wx


__all__ = ["get_current_conditions", "WX_LIMITS"]


# define operational weather limits for timdimm operation. stick with humidity and wind for now
WX_LIMITS = {"humidity": 90, "wind": 45}


def get_current_conditions():
    """
    get the current weather conditions from the various weather stations
    """
    checks = {
        "humidity": False,
        "wind": False,
    }

    # get the current weather conditions from the SAAO IO weather information system
    wx_dict = {}
    wx_dict["SAAO-IO"] = saao_io_wx()

    # check if data is recent
    td = Time(wx_dict["SAAO-IO"]["timestamp"]) - Time.now()
    # hack to avoid messing with timezones for SAAO timestamps
    if abs(td - 120 * u.minute) > 10 * u.minute:
        wx_dict["SAAO-IO"]["Valid"] = False

    if wx_dict["SAAO-IO"]["Valid"]:
        # check against operational limits
        rh = float(wx_dict["SAAO-IO"]["humidity"])
        wind = float(wx_dict["SAAO-IO"]["wind"])
        wind_warn = bool(wx_dict["SAAO-IO"]["wind_warn"])
        humidity_warn = bool(wx_dict["SAAO-IO"]["humidity_warn"])
        checks["humidity"] = (rh < WX_LIMITS["humidity"]) and not humidity_warn
        checks["wind"] = (wind < WX_LIMITS["wind"]) and not wind_warn

    # get the current weather conditions from the SALT weather station
    wx_dict["SALT"] = salt_wx()

    return wx_dict, checks


def main():
    wx_dict, checks = get_current_conditions()

    print("Weather Checks:")
    for k, v in checks.items():
        print(f"\t{k:20s}: {v}")

    for k, v in wx_dict.items():
        print(k)
        for k1, v1 in v.items():
            print(f"\t{k1:20s}: {v1}")


if __name__ == "__main__":
    main()
