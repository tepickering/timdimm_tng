# SPDX-FileCopyrightText: Copyright (c) 2020 ladyada for Adafruit Industries
#
# SPDX-License-Identifier: MIT
#
# To monitor on timdimm computer run:
# tio -b 115200 /dev/serial/by-id/usb-Adafruit_Industries_LLC_SHT4x_Trinkey_M0_1D7A4E235359575020312E3512210CFF-if00 

import time
import board
import adafruit_sht4x

i2c = board.I2C()  # uses board.SCL and board.SDA
sht = adafruit_sht4x.SHT4x(i2c)
# overflow issue with sht41, not present with sht45
# print("Found SHT4x with serial number", hex(sht.serial_number))

sht.mode = adafruit_sht4x.Mode.NOHEAT_HIGHPRECISION
print("Current mode is: ", adafruit_sht4x.Mode.string[sht.mode])
print()

while True:
    temperature, relative_humidity = sht.measurements
    print(f"{temperature:0.1f}, {relative_humidity:0.1f}")
    time.sleep(3)

