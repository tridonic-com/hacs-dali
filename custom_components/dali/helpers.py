"""Encoding helpers for the DALI configuration variables.

IEC 62386-102 stores fade time and fade rate as 4-bit codes and the extended
fade time as a base/multiplier pair, none of which are meaningful on their own.
These helpers translate between those encodings and the values the entities
present, and build the DTR0 write sequence shared by both config platforms.
"""

from collections.abc import Generator

from dali.address import GearShort
from dali.command import Command, Response
from dali.gear.general import DTR0

# fadeTime = 0.5 * sqrt(2 ** code) seconds. Code 0 selects the extended fade
# time instead. The values are tabulated rather than computed because IEC
# rounds half up where Python's round() rounds half to even.
FADE_TIME_OPTIONS: dict[int, str] = {
    0: "extended",
    1: "0_7_s",
    2: "1_0_s",
    3: "1_4_s",
    4: "2_0_s",
    5: "2_8_s",
    6: "4_0_s",
    7: "5_7_s",
    8: "8_0_s",
    9: "11_3_s",
    10: "16_0_s",
    11: "22_6_s",
    12: "32_0_s",
    13: "45_3_s",
    14: "64_0_s",
    15: "90_5_s",
}

# fadeRate = 506 / sqrt(2 ** code) steps per second. Code 0 is reserved.
FADE_RATE_OPTIONS: dict[int, str] = {
    1: "357_8_steps_s",
    2: "253_0_steps_s",
    3: "178_9_steps_s",
    4: "126_5_steps_s",
    5: "89_4_steps_s",
    6: "63_3_steps_s",
    7: "44_7_steps_s",
    8: "31_6_steps_s",
    9: "22_4_steps_s",
    10: "15_8_steps_s",
    11: "11_2_steps_s",
    12: "7_9_steps_s",
    13: "5_6_steps_s",
    14: "4_0_steps_s",
    15: "2_8_steps_s",
}

FADE_TIME_CODES: dict[str, int] = {
    option: code for code, option in FADE_TIME_OPTIONS.items()
}
FADE_RATE_CODES: dict[str, int] = {
    option: code for code, option in FADE_RATE_OPTIONS.items()
}

# extendedFadeTime = (base + 1) * unit, where the multiplier selects the unit.
# Multiplier 0 means no fade and 5-7 are reserved.
EXTENDED_FADE_TIME_UNITS_TENTHS: dict[int, int] = {1: 1, 2: 10, 3: 100, 4: 600}
EXTENDED_FADE_TIME_BASE_COUNT = 16
MIN_EXTENDED_FADE_TIME = 0.0
MAX_EXTENDED_FADE_TIME = 960.0
EXTENDED_FADE_TIME_STEP = 0.1

# Level 255 is MASK, which as a system failure level means "keep the current
# level" instead of fading to a stored one. It is the power-up default.
MASK_LEVEL = 255


def extended_fade_time_seconds(
    base: int | None, multiplier: int | None
) -> float | None:
    """Return an extended fade time in seconds, or None when not representable."""
    if base is None or multiplier is None:
        return None
    if multiplier == 0:
        return 0.0
    unit_tenths = EXTENDED_FADE_TIME_UNITS_TENTHS.get(multiplier)
    if unit_tenths is None:
        return None
    return (base + 1) * unit_tenths / 10


def encode_extended_fade_time(seconds: float) -> int:
    """Return the DTR0 byte for an extended fade time in seconds.

    The requested time is snapped to the nearest step of the finest multiplier
    that can still reach it, so a value between two steps lands on the closer
    one rather than always truncating downwards.
    """
    tenths = int(seconds * 10 + 0.5)
    if tenths <= 0:
        return 0
    for multiplier, unit_tenths in EXTENDED_FADE_TIME_UNITS_TENTHS.items():
        if tenths > EXTENDED_FADE_TIME_BASE_COUNT * unit_tenths:
            continue
        # Integer half-up rounding; round() would snap 45 s down to 40 s.
        base = (tenths + unit_tenths // 2) // unit_tenths - 1
        return (multiplier << 4) | max(0, min(base, EXTENDED_FADE_TIME_BASE_COUNT - 1))
    return (4 << 4) | (EXTENDED_FADE_TIME_BASE_COUNT - 1)


def set_dtr0_variable(
    command: type[Command], address: GearShort, value: int
) -> Generator[Command, Response | None]:
    """Create the sequence that writes a DTR0-sourced configuration variable.

    The SET commands carry only the destination address and take their value
    from DTR0, so loading DTR0 and issuing the command have to stay a single
    transaction; a command landing between the two would be stored instead.
    """
    yield DTR0(value)
    yield command(address)
