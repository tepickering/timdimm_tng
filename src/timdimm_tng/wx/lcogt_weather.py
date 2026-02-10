# -*- coding: utf-8 -*-

from urllib.request import urlopen
from urllib.error import URLError
import datetime


__all__ = ["get_weather"]


def open_page():
    """
    open the LCOGT simple weather page
    """
    try:
        page = urlopen("http://196.21.94.19/simple.html")
        info_string = page.readlines()[0].strip()
        page.close()

    except URLError:
        return False, "None"

    return True, info_string.decode("utf-8")


def is_data(info_string):
    """
    split the string into a datetime and data section
    """
    datetime = info_string.split(",")[0]
    data = info_string.split(",")[4:]

    return datetime, data


def get_lcogt_data():
    """
    get the data from the website, but poll the website until we get valid data
    three tries to get the corrected data, otherwise return a False
    """
    state, info_string = open_page()
    if state is True:
        datetime, data = is_data(info_string)
    else:
        return False, None, None

    return state, datetime, data


def get_weather():
    d = {}

    state, LCOGT_datetime, data = get_lcogt_data()

    if state is False:
        d["Valid"] = False
        return d
    else:
        DateNow = LCOGT_datetime.split()[0]
        Year = int(DateNow.split("-")[0])
        Month = int(DateNow.split("-")[1])
        Day = int(DateNow.split("-")[2])
        Time = LCOGT_datetime.split()[1]
        Hours = int(Time.split(":")[0])
        Minutes = int(Time.split(":")[1])
        Seconds = int(Time.split(":")[2])
        d["TimeStamp_SAST"] = datetime.datetime(
            Year, Month, Day, Hours, Minutes, Seconds
        )

        # the LCOGT time is in UT, have to add two hours to the sensor time
        d["TimeStamp_SAST"] = d["TimeStamp_SAST"] + datetime.timedelta(hours=2)

        d["Temp"] = round(float(data[1]), 1)
        d["Wind_speed"] = round(float(data[3]), 0) * 3.6  # from m/s to km/h
        d["Wind_dir"] = round(float(data[5]), 0)
        d["Rel_Hum"] = round(float(data[7]), 0)
        d["DewTemp"] = round(float(data[9]), 1)
        d["Bar_Press"] = round(
            float(data[13].strip()) * 1.3332239, 0
        )  # from mmhg to mbar
        Wet = data[15]

        if Wet == "TRUE":
            d["SkyCon"] = "RAIN"
        else:
            d["SkyCon"] = "DRY"

        d["Valid"] = True

        return d


def main():
    LCOGT = get_weather()

    print("")
    print("------------ LCOGT Weather Data ------------")
    print("TimeStamp (SAST) : ", LCOGT["TimeStamp_SAST"])
    print("Sky Condition    : ", LCOGT["SkyCon"])
    print("Wind Speed (km/h): ", LCOGT["Wind_speed"])
    print("Wind Direction   : ", LCOGT["Wind_dir"])
    print("Temperature      : ", LCOGT["Temp"])
    print("Relative Humidity: ", LCOGT["Rel_Hum"], "%")
    print("T - T(dew)       : ", LCOGT["Temp"] - LCOGT["DewTemp"])
    print("Pressure         : ", LCOGT["Bar_Press"])
    print("\n")


if __name__ == "__main__":
    main()
