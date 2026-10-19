"""Diagnostics for the Tridonic DALI integration."""

from dataclasses import asdict
from typing import Any

from dali.command import BitmapResponse

from homeassistant.core import HomeAssistant

from . import DaliConfigEntry


def _serialize(value: Any) -> Any:
    """Convert python-dali status responses into JSON-serializable data."""
    if isinstance(value, BitmapResponse):
        return value.status
    if isinstance(value, dict):
        return {key: _serialize(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_serialize(item) for item in value]
    return value


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: DaliConfigEntry
) -> dict[str, Any]:
    """Return diagnostics for a config entry."""
    coordinator = entry.runtime_data
    return {
        "entry_data": dict(entry.data),
        "gears": {
            str(address): _serialize(asdict(gear))
            for address, gear in coordinator.data.items()
        },
        "input_devices": {
            f"{address}_{instance}": _serialize(asdict(data))
            for (address, instance), data in coordinator.input_devices.items()
        },
        "device_instances": [list(item) for item in coordinator.device_instances],
    }
