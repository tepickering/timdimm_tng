from pathlib import Path


def timdimm_stop():
    Path("~/STOP").expanduser().touch()


def timdimm_start():
    Path("~/STOP").expanduser().unlink(missing_ok=True)
