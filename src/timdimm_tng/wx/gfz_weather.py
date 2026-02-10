# -*- coding: utf-8 -*-

from urllib.request import urlopen
from urllib.error import URLError
import datetime
from bs4 import BeautifulSoup

from timdimm_tng.wx.utils import dewpoint


__all__ = ["get_weather"]


def get_weather():
    # ****************************************************************************************
    # Open up the GFZ weather pages and parse the html code from relevant weather info

    d = {}

    try:
        page = urlopen("http://sg1a.suth.saao.ac.za/tmp/grav-sg37.htm")

    except URLError:
        d["Valid"] = False
        return d

    soup = BeautifulSoup(page, features="html.parser")

    text = soup.table.findAllNext(string=True)
    if text[23] != "hPa":
        print("Error with GFZ weather page info.")
        raise
    else:
        Time = text[31].strip()[11:]
        Hours = int(Time[:2])
        Minutes = int(Time[:5][3:])
        Seconds = int(Time[6:])

        DateNow = text[31].strip()[:10]
        TempDate = DateNow.split("-")
        Year = int(TempDate[0])
        Month = int(TempDate[1])
        Day = int(TempDate[2])

        TimeStamp_UTC = datetime.datetime(Year, Month, Day, Hours, Minutes, Seconds)
        d["TimeStamp_SAST"] = TimeStamp_UTC + datetime.timedelta(hours=2)

        # print(text[37])
        d["Bar_Press"] = float(text[37].strip())

    try:
        page = urlopen("http://sg1a.suth.saao.ac.za/tmp/wetter-0.htm")

    except URLError:
        d["Valid"] = False
        return d

    soup = BeautifulSoup(page, features="html.parser")

    text = soup.table.findAllNext(string=True)

    # Check if the GFZ website is populating the headers correctly.
    if text[18] != "deg_C":
        Temp = text[43].strip()
        Rel_Hum = text[45].strip()
    else:
        Temp = text[34].strip()
        Rel_Hum = text[36].strip()

    try:
        page = urlopen("http://sg1a.suth.saao.ac.za/tmp/wetter-1.htm")
    except URLError:
        d["Valid"] = False
        return d

    soup = BeautifulSoup(page, features="html.parser")

    text = soup.table.findAllNext(string=True)

    # Check if the GFZ website is populating the headers correctly.
    if text[18] != "m/s":
        d["Wind_dir"] = float(text[24].strip())
        d["Wind_sp"] = round(float(text[26].strip()) * 3.6, 1)
        SkyCon = text[28].strip()
    else:
        d["Wind_dir"] = float(text[28].strip())
        d["Wind_speed"] = round(float(text[30].strip()) * 3.6, 1)
        SkyCon = text[34].strip()

    if (SkyCon == "-0.0") or (SkyCon == "0.0"):
        d["SkyCon"] = "DRY"
    else:
        d["SkyCon"] = "RAIN"

    Temp = float(Temp)
    Rel_Hum = float(Rel_Hum)

    d["Temp"] = Temp
    d["Rel_Hum"] = Rel_Hum
    d["DewTemp"] = dewpoint(Temp, Rel_Hum)
    d["Valid"] = True

    return d


def main():
    GFZ = get_weather()

    if GFZ["Valid"]:
        print()
        print("------------ GFZ Weather Data -------------")
        print("TimeStamp (SAST) : ", GFZ["TimeStamp_SAST"])
        print("Sky Condition    : ", GFZ["SkyCon"])
        print("Wind Speed (km/h): ", GFZ["Wind_speed"])
        print("Wind Direction   : ", GFZ["Wind_dir"])
        print("Temperature      : ", GFZ["Temp"])
        print("Relative Humidity: ", GFZ["Rel_Hum"], "%")
        print("T - T(dew)       : ", float(GFZ["Temp"]) - float(GFZ["DewTemp"]))
        print("Barometric Press : ", GFZ["Bar_Press"])
        print("\n")
    else:
        print("No connection to the GFZ site")


if __name__ == "__main__":
    main()
