# -*- coding: utf-8 -*-

import tkinter as tk
import os
import time
from pathlib import Path


def run(program, *args):
    pid = os.fork()
    if not pid:
        os.execvp(program, (program,) + args)
    return pid


def park(b, pid):
    b.config(state=tk.DISABLED)
    print("\nParking timdimm telescope....\n")
    os.system("./park")
    b.config(text="Initialize")
    quit.config(state=tk.NORMAL)
    main.config(state=tk.DISABLED)
    b.config(state=tk.NORMAL)
    b.config(command=lambda c=b: init(c))


def init(b):
    print("\nInitializing mount....\n")
    pid = run("./init")
    quit.config(state=tk.DISABLED)
    time.sleep(60)
    main.config(state=tk.NORMAL)
    b.config(text="Park")
    b.config(command=lambda but=b, p=pid: park(but, p))
    print("READY  TO  START  SEEING  MEASUREMENTS\n")
    time.sleep(5)


def kill_kstars(b, pid):
    print("\nKilling KStars process #%d\n" % pid)
    os.system("kill -9 %d" % pid)
    time.sleep(10)
    os.system("killall kstars")
    b.config(relief=tk.RAISED)
    b.config(text="KStars")
    b.config(command=lambda c=b: kstars(c))


def kstars(b):
    pid = run("kstars")
    b.config(relief=tk.SUNKEN)
    b.config(text="Kill KStars")
    b.config(command=lambda but=b, p=pid: kill_kstars(but, p))


def open_oxwagon(b):
    print("Opening Ox Wagon")
    os.system("oxwagon OPEN 3600")


def close_oxwagon(b):
    print("Closing Ox Wagon")
    os.system("oxwagon CLOSE")


def main():
    root = tk.Tk()
    root.title("timDIMM")
    root.geometry("200x300-0-0")

    frame = tk.Frame(root)
    frame.pack()

    kstars_button = tk.Button(frame, text="KStars")
    kstars_button.pack(padx=10, pady=5, fill=tk.X)
    kstars_button.config(command=lambda b=kstars_button: kstars(b))

    initpark = tk.Button(frame, text="Initialize")
    initpark.pack(padx=10, pady=5, fill=tk.X)
    initpark.config(command=lambda b=initpark: init(b))

    wagon = tk.Button(frame, text="Open Ox Wagon", width=180)
    wagon.pack(padx=10, pady=5, expand=True, fill=tk.X)
    wagon.config(command=lambda b=wagon: open_oxwagon(b))

    wagon = tk.Button(frame, text="Close Ox Wagon", width=180)
    wagon.pack(padx=10, pady=5, expand=True, fill=tk.X)
    wagon.config(command=lambda b=wagon: close_oxwagon(b))

    quit = tk.Button(frame, text="QUIT", fg="red", command=frame.quit)
    quit.pack(pady=20, padx=10, fill=tk.BOTH)

    root.mainloop()


def timdimm_stop():
    Path("~/STOP").expanduser().touch()


def timdimm_start():
    Path("~/STOP").expanduser().unlink(missing_ok=True)
