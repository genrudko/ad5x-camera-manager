#!/usr/bin/env python3
"""Creality Nebula / CCX2F3298 day-night controller for AD5X.

Physically verified on the AD5X + Z-Mod MIPS32 environment:
- UVC Extension Unit: 6
- Selector: 16
- Control length: 60 bytes
- byte 0: 0=DAY, 1=NIGHT, 2=AUTO
- UVCIOC_CTRL_QUERY: 0xc00c7521 on the printer's 32-bit MIPS userspace

The helper is intentionally short-lived so any native ioctl failure is isolated
from the long-running Camera Manager daemon.
"""

from __future__ import annotations

import argparse
import ctypes
import os
import sys

UVCIOC_CTRL_QUERY = 0xC00C7521
UVC_SET_CUR = 0x01
UVC_GET_CUR = 0x81
UNIT = 6
SELECTOR = 16
CONTROL_SIZE = 60

DAY = 0
NIGHT = 1
AUTO = 2
NAMES = {DAY: "DAY", NIGHT: "NIGHT", AUTO: "AUTO"}
VALUES = {"day": DAY, "night": NIGHT, "auto": AUTO}


class UvcXuControlQuery(ctypes.Structure):
    _fields_ = [
        ("unit", ctypes.c_uint8),
        ("selector", ctypes.c_uint8),
        ("query", ctypes.c_uint8),
        ("size", ctypes.c_uint16),
        ("data", ctypes.POINTER(ctypes.c_uint8)),
    ]


libc = ctypes.CDLL(None, use_errno=True)
libc.ioctl.argtypes = [ctypes.c_int, ctypes.c_ulong, ctypes.c_void_p]
libc.ioctl.restype = ctypes.c_int


def ioctl_query(fd: int, query: int, data: ctypes.Array[ctypes.c_uint8]) -> None:
    q = UvcXuControlQuery(
        unit=UNIT,
        selector=SELECTOR,
        query=query,
        size=CONTROL_SIZE,
        data=ctypes.cast(data, ctypes.POINTER(ctypes.c_uint8)),
    )
    rc = libc.ioctl(fd, UVCIOC_CTRL_QUERY, ctypes.byref(q))
    if rc != 0:
        err = ctypes.get_errno()
        raise OSError(err, os.strerror(err))


def read_mode(fd: int) -> int:
    data = (ctypes.c_uint8 * CONTROL_SIZE)()
    ioctl_query(fd, UVC_GET_CUR, data)
    value = int(data[0])
    if value not in NAMES:
        raise RuntimeError(f"unexpected day/night value: {value}")
    return value


def write_mode(fd: int, value: int) -> None:
    # Preserve every vendor-control byte except the verified day/night selector.
    data = (ctypes.c_uint8 * CONTROL_SIZE)()
    ioctl_query(fd, UVC_GET_CUR, data)
    data[0] = value
    ioctl_query(fd, UVC_SET_CUR, data)


def mode_name(value: int) -> str:
    return NAMES.get(value, f"UNKNOWN({value})")


def set_and_verify(fd: int, value: int) -> tuple[int, int]:
    before = read_mode(fd)
    if before != value:
        write_mode(fd, value)
    after = read_mode(fd)
    if after != value:
        raise RuntimeError(
            f"readback verification failed: requested={mode_name(value)} "
            f"actual={mode_name(after)}"
        )
    return before, after


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("device")
    parser.add_argument("command", choices=("day", "night", "auto", "status", "ensure-day"))
    args = parser.parse_args()

    if ctypes.sizeof(ctypes.c_void_p) != 4 or ctypes.sizeof(UvcXuControlQuery) != 12:
        raise RuntimeError(
            "Nebula XU helper requires the verified 32-bit AD5X userspace "
            f"(pointer={ctypes.sizeof(ctypes.c_void_p)}, query={ctypes.sizeof(UvcXuControlQuery)})"
        )

    fd = os.open(args.device, os.O_RDWR | getattr(os, "O_NONBLOCK", 0))
    try:
        before = read_mode(fd)

        if args.command == "status":
            print(mode_name(before))
            return 0

        if args.command == "ensure-day":
            if before == DAY:
                print("DAY")
                return 0
            _, after = set_and_verify(fd, DAY)
            print(f"forced DAY (previous: {mode_name(before)})")
            return 0 if after == DAY else 2

        target = VALUES[args.command]
        _, after = set_and_verify(fd, target)
        print(
            f"{mode_name(after)}"
            if before == after
            else f"{mode_name(before)} -> {mode_name(after)}"
        )
        return 0
    finally:
        os.close(fd)


if __name__ == "__main__":
    raise SystemExit(main())
