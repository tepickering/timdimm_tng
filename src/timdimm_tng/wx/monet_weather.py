import ssl
import json
import datetime

from urllib.request import urlopen

from timdimm_tng.wx.utils import dewpoint


__all__ = ["parse_monet"]


def parse_monet():
    """
    Grab the current weather conditions from the MONET weather station
    via their web API
    """
    monet_wx = {}

    try:
        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        page = urlopen(
            "https://weather.monet.suth.saao.ac.za/api/sensors/", context=ctx
        )
        monet_data = json.loads(page.read().decode())
    except Exception as e:
        monet_wx["Valid"] = False
        monet_wx["Error"] = e
        return monet_wx

    monet_good = True
    # MONET provides a list of dicts, one for each sensor. Go thru and collect
    # the ones from MONET's weather station.
    for sensor in monet_data:
        if sensor["station_name"] == "MONET":
            monet_wx[sensor["type_code"]] = sensor["value"]
            if sensor["good"] is not None:
                monet_good = monet_good and sensor["good"]

    monet_wx["Valid"] = True
    monet_wx["Open"] = monet_good
    monet_wx["TimeStamp_SAST"] = datetime.datetime.utcnow() + datetime.timedelta(
        hours=2
    )
    if monet_wx.pop("rain"):
        monet_wx["SkyCon"] = "RAIN"
    else:
        monet_wx["SkyCon"] = "DRY"

    monet_wx["Wind_speed"] = monet_wx.pop("windspeed")
    monet_wx["Wind_dir"] = monet_wx.pop("winddir")
    monet_wx["Temp"] = monet_wx.pop("temp")
    monet_wx["Rel_Hum"] = monet_wx.pop("humid")
    monet_wx["Bar_Press"] = monet_wx.pop("press")
    try:
        monet_wx["DewTemp"] = dewpoint(monet_wx["Temp"], monet_wx["Rel_Hum"])
    except Exception as e:
        print(f"Error calculating dewpoint: {e}")
        monet_wx["DewTemp"] = "N/A"

    return monet_wx


def main():
    monet = parse_monet()

    if monet["Valid"]:
        print("")
        print("------------ MONET Weather Data ------------")
        print("TimeStamp (SAST) : ", monet["TimeStamp_SAST"])
        print("Sky Condition    : ", monet["SkyCon"])
        print("Wind Speed (km/h): ", monet["Wind_speed"])
        print("Wind Direction   : ", monet["Wind_dir"])
        print("Temperature      : ", monet["Temp"])
        print("Relative Humidity: ", monet["Rel_Hum"], "%")
        try:
            print("T - T(dew)       : ", float(monet["Temp"]) - float(monet["DewTemp"]))
        except Exception as e:
            print(f"Error calculating T - T(dew): {e}")
            print("T - T(dew)       :  N/A")
        print("Dew Point        : ", monet["DewTemp"])
        print("Barometric Pres. : ", monet["Bar_Press"])
        print("Open?            : ", monet["Open"])
        print("\n")

    else:
        print(
            f'Connection is down or information from MONET is invalid: {monet["Error"]}'
        )


if __name__ == "__main__":
    main()
