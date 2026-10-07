"""Diagnostics for the Tridonic DALI integration."""

from dataclasses import asdict
from typing import Any

from homeassistant.core import HomeAssistant

from . import DaliConfigEntry


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: DaliConfigEntry
) -> dict[str, Any]:
    """Return diagnostics for a config entry."""
    coordinator = entry.runtime_data
    return {
        "entry_data": dict(entry.data),
        "gears": {
            str(address): asdict(gear) for address, gear in coordinator.data.items()
        },
        "input_devices": {
            f"{address}_{instance}": asdict(data)
            for (address, instance), data in coordinator.input_devices.items()
        },
        "device_instances": [list(item) for item in coordinator.device_instances],
    }
