"""
the OxWagon class implements the most important features required to control
the ox wagon enclosure.
"""

import serial
import io
import argparse
import time

from datetime import datetime


__all__ = ["OxWagon"]


def hex2bin(str):
    """
    take a hexadecimal number as a string and convert it to a binary string
    """
    bin = [
        "0000",
        "0001",
        "0010",
        "0011",
        "0100",
        "0101",
        "0110",
        "0111",
        "1000",
        "1001",
        "1010",
        "1011",
        "1100",
        "1101",
        "1110",
        "1111",
    ]
    aa = ""
    for i in range(len(str)):
        aa += bin[int(str[i], base=16)]
    return aa


def checksum(str):
    """
    twos complement checksum as used by the ox wagon PLC
    """
    command = str[1:len(str) - 4]
    sum = 0
    for i in range(0, len(command), 2):
        byte = command[i] + command[i + 1]
        sum = sum + int(byte, base=16)
    neg = ~sum & 0xFF
    return neg + 1


class OxWagon:
    # set a 2 minute power outage delay
    pwr_delay = "0120"
    # set a 10 minute watchdog timer delay
    watch_delay = "0600"

    # cache the state when status() is queried
    state = {}

    # dict of most commonly used commands:
    # the last bit in CLOSE was changed from 0 to 2
    # to keep the scope on when the ox wagon is closed
    commands = {
        "RESET": "2C008000",
        "OPEN": "10428C02",
        "CLOSE": "14218000",
        "MONITOR": "14228C00",
        "SCOPE": "00000002",
        "LIGHT": "00000001",
        "OFF": "00000000",
        "CLOSE_SCOPE_ON": "14218002",
        "CLOSE_SCOPE_OFF": "14218000",
        "RESET_SCOPE_ON": "2C008002",
        "RESET_SCOPE_OFF": "2C008000",
    }

    # bit map for the first 16-bit register used to monitor status
    reg_106e_map = [
        "Manual Close Drop Roof",
        "Manual Open Drop Roof",
        "Manual Close Slide Roof",
        "Manual Open Slide Roof",
        "Forced Rain Closure",
        "Raining",
        False,
        "Drop Roof Slowdown",
        "Drop Roof Moving",
        "Drop Roof Opened",
        "Drop Roof Closed",
        "Remote Enabled",
        "Slide Roof Slowdown",
        "Slide Roof Moving",
        "Slide Roof Fully Opened",
        "Slide Roof Closed",
    ]

    # bit map for the second register
    reg_106f_map = [
        "Watchdog Tripped",
        "Drop Roof Inverter Fault",
        "Slide roof Inverter Fault",
        False,
        False,
        "Telescope Powered On",
        "Closed due to Power Failure",
        False,
        False,
        "Emergency Stop",
        "Power Failure",
        "Proximity Close Drop Roof",
        "Proximity Open Drop Roof",
        "Proximity Close Slide Roof",
        "Proximity Open Slide Roof",
        "Lights On",
    ]

    # this may need to change for new computer
    def __init__(self, port="/dev/ttyUSB0", retry_limit=10):
        """
        we use the pyserial package, https://pyserial.readthedocs.io/, to
        implement RS232 communication. beware, the port may change if the
        USB-RS232 cable is ever movedto a different port
        """
        retries = 0
        while retries < retry_limit:
            try:
                self.ser = serial.Serial(
                    port,
                    9600,
                    bytesize=7,
                    parity=serial.PARITY_EVEN,
                    timeout=1,
                    exclusive=True,
                )
                break
            except Exception as e:
                retries += 1
                time.sleep(0.5)
                if retries >= retry_limit:
                    raise e

        # use this trick to make sure the CR-LF conversions are
        # handled correctly
        self._buf = io.BufferedRWPair(self.ser, self.ser)
        self.sio = io.TextIOWrapper(self._buf, newline="\r\n")
        self.sio.flush()
        self.status()

    def close_port(self):
        """Close the I/O wrappers and serial port in the correct order.

        Detach the TextIOWrapper first so it won't flush during GC,
        then close the BufferedRWPair while the serial port is still
        open (so its flush succeeds), which also closes the port.
        """
        try:
            if hasattr(self, 'sio') and not self.sio.closed:
                self.sio.detach()
        except Exception:
            pass
        try:
            if hasattr(self, '_buf') and not self._buf.closed:
                self._buf.close()
        except Exception:
            pass
        try:
            if hasattr(self, 'ser') and self.ser.is_open:
                self.ser.close()
        except Exception:
            pass

    def __del__(self):
        self.close_port()

    def command(self, cmd, debug=True):
        """
        take a hexadecimal string, build a command out of it by tacking
        on the delay parameters, and calculating the checksum.
        """
        now = datetime.now()
        with open("/home/timdimm/ox.log", "a") as fout:
            fout.write(f"Running {cmd} at {str(now)}\n")

        cmd_header = ":01101064000408"
        if cmd in self.commands:
            cmd = cmd_header + self.commands[cmd] + self.watch_delay + self.pwr_delay
        else:
            return False

        if debug:
            print(cmd)

        # use ox wagon compatible checksum
        sum = checksum(cmd + "0000")
        to_send = "%s%x\n" % (cmd, sum)
        to_send = to_send.upper()

        self.sio.write(str(to_send))
        self.sio.flush()

        resp = self.sio.readline()

        if debug:
            print(resp)

        return resp

    def open(self, delay=3600):
        """
        use pre-defined command to open the ox wagon completely
        """
        print(f"Opening for {delay} seconds")

        self.watch_delay = str(delay).zfill(4)
        self.command("OPEN")

    def monitor(self):
        """
        use pre-defined command to open the ox wagon slide roof only
        """
        self.command("MONITOR")

    def close(self):
        """
        use pre-defined command to close the ox wagon
        """
        self.command("CLOSE")

    def reset(self):
        """
        use pre-defined command to reset the ox wagon controller and
        clear forced closure bits
        """
        self.command("RESET")

    def scope(self):
        """
        use pre-defined command to turn on power to telescope
        """
        self.command("SCOPE")

    def close_scope_on(self):
        """
        use pre-defined command to close the ox wagon
        """
        self.command("CLOSE_SCOPE_ON")

    def close_scope_off(self):
        """
        use pre-defined command to close the ox wagon
        """
        self.command("CLOSE_SCOPE_OFF")

    def reset_scope_on(self):
        """
        use pre-defined command to reset the ox wagon controller and
        clear forced closure bits
        """
        self.command("RESET_SCOPE_ON")

    def reset_scope_off(self):
        """
        use pre-defined command to reset the ox wagon controller and
        clear forced closure bits
        """
        self.command("RESET_SCOPE_OFF")

    def light_on(self):
        """
        use pre-defined command to reset the ox wagon controller and
        clear forced closure bits
        """
        self.command("LIGHT")

    def status(self):
        """
        send pre-defined command to query status and parse response into
        dict that is cached into state{} and also returned to caller.
        """
        self.sio.write(str(":0103106E000579\n"))
        self.sio.flush()

        resp = self.sio.readline()

        # use hex2bin from binutils.py
        reg_106e = hex2bin(resp[7:11])
        reg_106f = hex2bin(resp[11:15])

        # use bit maps and parse into dict of boolean values
        for i in range(16):
            if self.reg_106e_map[i]:
                if reg_106e[i] == "1":
                    self.state[self.reg_106e_map[i]] = True
                else:
                    self.state[self.reg_106e_map[i]] = False
        for i in range(16):
            if self.reg_106f_map[i]:
                if reg_106f[i] == "1":
                    self.state[self.reg_106f_map[i]] = True
                else:
                    self.state[self.reg_106f_map[i]] = False

        return self.state


# handle running this as a standalone script.
def main():
    parser = argparse.ArgumentParser(
        description="Utility for controlling the ox wagon enclosure"
    )

    parser.add_argument(
        "cmd",
        default="status",
        choices=["open", "close", "reset", "status"],
        type=str.lower,
        help="Command to send to ox wagon controller",
    )

    parser.add_argument(
        "extra_args", nargs="*", help="Extra arguments for ox wagon commands"
    )

    parser.add_argument(
        "-p",
        "--port",
        required=False,
        default="/dev/ttyUSB0",
        help="Serial port for ox wagon controller",
    )

    args = parser.parse_args()

    o = OxWagon(port=args.port)

    command = args.cmd.lower()

    if command == "status":
        state = o.status()
        for k, v in state.items():
            print("%30s : \t %s" % (k, v))
    else:
        extra_args = ", ".join(args.extra_args)
        eval("o.%s(%s)" % (command, extra_args))
