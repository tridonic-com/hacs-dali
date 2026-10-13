"""Constants for the Tridonic DALI integration."""

DOMAIN = "dali"

CONF_BUS_POWER = "bus_power"

# IEC 62386 control-gear device types the integration handles.
DEVICE_TYPE_EMERGENCY = 1
DEVICE_TYPE_LED = 6
DEVICE_TYPE_COLOUR = 8
SUPPORTED_GEAR_DEVICE_TYPES = (
    DEVICE_TYPE_LED,
    DEVICE_TYPE_COLOUR,
    DEVICE_TYPE_EMERGENCY,
)

# IEC 62386 control-gear device types not yet supported by the integration.
DEVICE_TYPE_FLUORESCENT = 0
DEVICE_TYPE_HID = 2
DEVICE_TYPE_HALOGEN = 3
DEVICE_TYPE_INCANDESCENT = 4
DEVICE_TYPE_DC = 5
DEVICE_TYPE_SWITCHING = 7

# IEC 62386 control-device instance types.
INSTANCE_TYPE_PUSH_BUTTON = 1
INSTANCE_TYPE_ABSOLUTE_INPUT = 2
INSTANCE_TYPE_OCCUPANCY = 3
INSTANCE_TYPE_LIGHT_SENSOR = 4
INSTANCE_TYPE_GENERAL_SENSOR = 6

# Human-readable names for each control-gear device type. The IEC 62386 part
# specifying a device type DTn is part 2(01+n) (e.g. DT6 → IEC 62386-207).
GEAR_DEVICE_TYPE_NAMES: dict[int, str] = {
    DEVICE_TYPE_FLUORESCENT: "Fluorescent lamp",
    DEVICE_TYPE_EMERGENCY: "Self-contained emergency lighting",
    DEVICE_TYPE_HID: "HID lamp",
    DEVICE_TYPE_HALOGEN: "Low-voltage halogen lamp",
    DEVICE_TYPE_INCANDESCENT: "Incandescent lamp dimmer",
    DEVICE_TYPE_DC: "DC-controlled dimmer",
    DEVICE_TYPE_LED: "LED module",
    DEVICE_TYPE_SWITCHING: "Switching function",
    DEVICE_TYPE_COLOUR: "Colour control",
}

# Human-readable names for each control-device instance type. The IEC 62386
# part specifying an instance type n is part 3(00+n) (e.g. type 4 → 62386-304).
DEVICE_INSTANCE_TYPE_NAMES: dict[int, str] = {
    INSTANCE_TYPE_PUSH_BUTTON: "Push button",
    INSTANCE_TYPE_ABSOLUTE_INPUT: "Absolute input device",
    INSTANCE_TYPE_OCCUPANCY: "Occupancy sensor",
    INSTANCE_TYPE_LIGHT_SENSOR: "Light sensor",
    INSTANCE_TYPE_GENERAL_SENSOR: "General purpose sensor",
}

ISSUE_UNADDRESSED_GEAR = "unaddressed_gear"
ISSUE_UNADDRESSED_CONTROLDEVICE = "unaddressed_controldevice"
ISSUE_BUS_VOLTAGE_ERROR = "bus_voltage_error"
ISSUE_BUS_OVERLOAD = "bus_overload"

# Registry-identifier infixes. Control gear and control devices have
# independent DALI short-address spaces, so the kind is encoded to keep a
# same-numbered gear and control device as distinct registry devices.
GEAR_ID_INFIX = "gear"
CONTROL_DEVICE_ID_INFIX = "controldevice"


def registry_identifier(entry_id: str, address: int, *, input_device: bool) -> str:
    """Return the device-registry identifier for a DALI gear or control device."""
    infix = CONTROL_DEVICE_ID_INFIX if input_device else GEAR_ID_INFIX
    return f"{entry_id}_{infix}_{address}"


def unaddressed_gear_issue_id(entry_id: str) -> str:
    """Return the repair issue ID for unaddressed gear on a DALI bus."""
    return f"{ISSUE_UNADDRESSED_GEAR}_{entry_id}"


def unaddressed_control_device_issue_id(entry_id: str) -> str:
    """Return the repair issue ID for unaddressed control devices on a DALI bus."""
    return f"{ISSUE_UNADDRESSED_CONTROLDEVICE}_{entry_id}"


def bus_voltage_error_issue_id(entry_id: str) -> str:
    """Return the repair issue ID for an unpowered DALI bus."""
    return f"{ISSUE_BUS_VOLTAGE_ERROR}_{entry_id}"


def bus_overload_issue_id(entry_id: str) -> str:
    """Return the repair issue ID for an overloaded or undersized bus supply."""
    return f"{ISSUE_BUS_OVERLOAD}_{entry_id}"
