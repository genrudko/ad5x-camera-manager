import os
import sys
import time
import ctypes

DEVICE = sys.argv[1] if len(sys.argv) > 1 else "/dev/video0"
MODE = sys.argv[2] if len(sys.argv) > 2 else "apply"

UVCIOC_CTRL_QUERY = 0xC00C7521

UVC_SET_CUR = 0x01
UVC_GET_CUR = 0x81

XU_UNIT = 4
XU_SELECTOR = 1

I2C_DEV   = 0x10D0
I2C_SLAVE = 0x10D1
I2C_DATA  = 0x10D2
I2C_TRG   = 0x10D7
I2C_SCL   = 0x10D8
I2C_MODE  = 0x10D9

SENSOR_SLAVE = 0x3C


class UvcXuControlQuery(ctypes.Structure):
    _fields_ = [
        ("unit", ctypes.c_uint8),
        ("selector", ctypes.c_uint8),
        ("query", ctypes.c_uint8),
        ("size", ctypes.c_uint16),
        ("data", ctypes.POINTER(ctypes.c_uint8)),
    ]


if ctypes.sizeof(UvcXuControlQuery) != 12:
    raise RuntimeError(
        "Unexpected UvcXuControlQuery size: "
        f"{ctypes.sizeof(UvcXuControlQuery)}"
    )


libc = ctypes.CDLL(None, use_errno=True)

libc.ioctl.argtypes = [
    ctypes.c_int,
    ctypes.c_ulong,
    ctypes.c_void_p,
]

libc.ioctl.restype = ctypes.c_int


fd = os.open(DEVICE, os.O_RDWR)


def xu(query, payload):
    buf = (ctypes.c_uint8 * len(payload))(*payload)

    q = UvcXuControlQuery(
        XU_UNIT,
        XU_SELECTOR,
        query,
        len(payload),
        ctypes.cast(
            buf,
            ctypes.POINTER(ctypes.c_uint8)
        ),
    )

    rc = libc.ioctl(
        fd,
        UVCIOC_CTRL_QUERY,
        ctypes.byref(q),
    )

    if rc < 0:
        e = ctypes.get_errno()
        raise OSError(e, os.strerror(e))

    return bytes(buf)


def asic_write(addr, value):
    xu(
        UVC_SET_CUR,
        [
            addr & 0xFF,
            (addr >> 8) & 0xFF,
            value & 0xFF,
            0x00,
        ],
    )


def asic_read(addr):
    xu(
        UVC_SET_CUR,
        [
            addr & 0xFF,
            (addr >> 8) & 0xFF,
            0x00,
            0xFF,
        ],
    )

    data = xu(
        UVC_GET_CUR,
        [
            addr & 0xFF,
            (addr >> 8) & 0xFF,
            0x00,
            0x00,
        ],
    )

    return data[2]


def wait_i2c():
    status = 0

    for _ in range(15):
        status = asic_read(I2C_DEV)

        if status & 0x04:
            break

        time.sleep(0.001)

    if (status & 0x0C) != 0x04:
        raise RuntimeError(
            f"I2C failed: status=0x{status:02X}"
        )


def sensor_write(addr, value=0, data_bytes=1):
    if data_bytes not in (0, 1, 2):
        raise ValueError("invalid data_bytes")

    asic_write(I2C_MODE, 0x01)
    asic_write(I2C_SCL, 0x01)

    speed = asic_read(I2C_DEV)

    base = 0x81 if (speed & 0x01) else 0x80

    asic_write(
        I2C_DEV,
        base | ((2 + data_bytes) << 4)
    )

    asic_write(I2C_SLAVE, SENSOR_SLAVE)

    payload = [
        (addr >> 8) & 0xFF,
        addr & 0xFF,
    ]

    if data_bytes == 1:
        payload.append(value & 0xFF)

    elif data_bytes == 2:
        payload.extend([
            (value >> 8) & 0xFF,
            value & 0xFF,
        ])

    while len(payload) < 5:
        payload.append(0)

    for i in range(5):
        asic_write(
            I2C_DATA + i,
            payload[i]
        )

    asic_write(I2C_TRG, 0x10)

    wait_i2c()


def sensor_read2(addr):
    # Sonix SDK sequence:
    # dummy write of 16-bit sensor address.
    sensor_write(addr, 0, 0)

    asic_write(I2C_MODE, 0x01)
    asic_write(I2C_SCL, 0x01)

    speed = asic_read(I2C_DEV)

    base = 0x83 if (speed & 0x01) else 0x82

    asic_write(
        I2C_DEV,
        base | (2 << 4)
    )

    asic_write(
        I2C_SLAVE,
        SENSOR_SLAVE
    )

    for i in range(5):
        asic_write(
            I2C_DATA + i,
            0
        )

    asic_write(I2C_TRG, 0x10)

    wait_i2c()

    data = [
        asic_read(I2C_DATA + i)
        for i in range(5)
    ]

    return (
        (data[3] << 8)
        | data[4]
    )


def sensor_read1(addr):
    return (
        sensor_read2(addr) >> 8
    ) & 0xFF


def get_state():
    orient = sensor_read2(0x3820)

    return {
        "pid": sensor_read2(0x300A),
        "out_x": sensor_read2(0x3808),
        "out_y": sensor_read2(0x380A),
        "inc": sensor_read2(0x3814),
        "r3820": (orient >> 8) & 0xFF,
        "r3821": orient & 0xFF,
        "r4514": sensor_read1(0x4514),
    }


def validate(s):
    # Orientation bits 0x3820/0x3821 are sensor timing controls, not a
    # QXGA-only feature.  The previous helper deliberately required QXGA
    # because that was the only physically validated mode at the time.
    # Physical acceptance now needs resolution changes, so keep the strong
    # sensor identity check while preserving whatever scaling/binning mode
    # the camera firmware selected.
    if s["pid"] != 0x3660:
        raise RuntimeError(
            f"not OV3660: PID=0x{s['pid']:04X}"
        )

    if not (1 <= s["out_x"] <= 0x0FFF and 1 <= s["out_y"] <= 0x0FFF):
        raise RuntimeError(
            f"invalid sensor output size {s['out_x']}x{s['out_y']}"
        )


def show(s, title):
    print(title)
    print(
        f"PID=0x{s['pid']:04X} "
        f"SIZE={s['out_x']}x{s['out_y']} "
        f"INC=0x{s['inc']:04X} "
        f"3820=0x{s['r3820']:02X} "
        f"3821=0x{s['r3821']:02X} "
        f"4514=0x{s['r4514']:02X}"
    )


try:
    before = get_state()
    validate(before)

    if MODE == "status":
        show(
            before,
            "OV3660 orientation status:"
        )
        sys.exit(0)

    if MODE != "apply":
        raise RuntimeError(
            "mode must be apply or status"
        )

    #
    # Verified physical orientation for this module.  For the camera's
    # normal firmware modes, clearing vertical-flip bits and enabling
    # horizontal-mirror bits produces the correct image for the physical
    # upside-down mount.  Preserve every unrelated timing/binning bit.
    # 0x4514=0xBB is valid for the mirror path both with and without
    # binning; the active resolution/scaling is intentionally left alone.
    #
    target20 = before["r3820"] & ~0x06
    target21 = before["r3821"] | 0x06
    target4514 = 0xBB

    if (
        before["r3820"] == target20
        and before["r3821"] == target21
        and before["r4514"] == target4514
    ):
        show(
            before,
            "OV3660 orientation already correct:"
        )
        sys.exit(0)

    sensor_write(
        0x3820,
        target20,
        1
    )

    sensor_write(
        0x3821,
        target21,
        1
    )

    sensor_write(
        0x4514,
        target4514,
        1
    )

    time.sleep(0.15)

    after = get_state()
    validate(after)

    if (
        after["r3820"] != target20
        or after["r3821"] != target21
        or after["r4514"] != target4514
    ):
        raise RuntimeError(
            "orientation readback mismatch"
        )

    print(
        "OV3660 orientation applied: "
        f"3820 0x{before['r3820']:02X}"
        f"->0x{after['r3820']:02X}, "
        f"3821 0x{before['r3821']:02X}"
        f"->0x{after['r3821']:02X}, "
        f"4514 0x{before['r4514']:02X}"
        f"->0x{after['r4514']:02X}"
    )

finally:
    os.close(fd)
