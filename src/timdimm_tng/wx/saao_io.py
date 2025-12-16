# -*- coding: utf-8 -*-

import json

from urllib.request import urlopen
from urllib.error import URLError


__all__ = ["parse_saao_io"]


def parse_saao_io():
    # read the SAAO IO json page
    SAAO_IO_URL = "https://io.saao.ac.za/IO/current_weather.json"
    io_data = {}
    io_data["Valid"] = False

    try:
        sock = urlopen(SAAO_IO_URL)
        data = sock.read().decode("utf-8")
        io_data = json.loads(data)
        io_data["Valid"] = True
    except URLError:
        e = {}
        e["Valid"] = False
        return e

    return io_data


def main():
    io_data = parse_saao_io()
    if io_data["Valid"]:
        print("------------ SAAO IO Weather Data ------------")
        for key, value in io_data.items():
            print(f"{key}: {value}")
    else:
        print("Failed to retrieve SAAO IO data.")


if __name__ == "__main__":
    main()