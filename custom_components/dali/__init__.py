"""The Tridonic DALI integration."""

from dali.driver.serial import DriverLubaRs232
from dali.exceptions import TransmissionError

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_DEVICE, Platform
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryNotReady
from homeassistant.helpers import issue_registry as ir
from homeassistant.helpers.device_registry import AnyDeviceEntry
from homeassistant.helpers.storage import Store

from .const import (
    CONF_BUS_POWER,
    CONTROL_DEVICE_ID_INFIX,
    DOMAIN,
    GEAR_ID_INFIX,
    unaddressed_gear_issue_id,
)
from .coordinator import (
    STORAGE_VERSION,
    DaliCoordinator,
    clear_bus_voltage_issues,
    raise_bus_voltage_issue,
)

PLATFORMS: list[Platform] = [
    Platform.BINARY_SENSOR,
    Platform.BUTTON,
    Platform.EVENT,
    Platform.LIGHT,
    Platform.NUMBER,
    Platform.SELECT,
    Platform.SENSOR,
]


type DaliConfigEntry = ConfigEntry[DaliCoordinator]


async def async_setup_entry(hass: HomeAssistant, entry: DaliConfigEntry) -> bool:
    """Set up Tridonic DALI from a config entry."""
    driver = DriverLubaRs232(
        uri=f"luba232:{entry.data[CONF_DEVICE]}",
        bus_power=entry.data.get(CONF_BUS_POWER, False),
    )
    try:
        await driver.connect(scan_dev_inst=True)
    except TransmissionError as err:
        if transport := getattr(driver, "_transport", None):
            transport.close()
        raise_bus_voltage_issue(hass, entry, err)
        raise ConfigEntryNotReady(
            translation_domain=DOMAIN,
            translation_key="cannot_connect",
        ) from err
    except (OSError, TimeoutError) as err:
        if transport := getattr(driver, "_transport", None):
            transport.close()
        raise ConfigEntryNotReady(
            translation_domain=DOMAIN,
            translation_key="cannot_connect",
        ) from err
    clear_bus_voltage_issues(hass, entry.entry_id)
    coordinator = DaliCoordinator(hass, driver, entry)
    await coordinator.async_load_metadata_cache()
    try:
        await coordinator.async_config_entry_first_refresh()
    except Exception:
        coordinator.close()
        raise
    entry.runtime_data = coordinator
    coordinator.start_event_listener()

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    # The initial refresh skips the slow memory-bank reads to keep setup fast;
    # read the deferred identification and diagnostics data in the background.
    entry.async_create_background_task(
        hass, coordinator.async_enrich_deferred_data(), "dali_metadata_enrich"
    )

    return True


async def async_unload_entry(hass: HomeAssistant, entry: DaliConfigEntry) -> bool:
    """Unload a config entry."""
    unloaded = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unloaded:
        entry.runtime_data.close()
    return unloaded


async def async_remove_entry(hass: HomeAssistant, entry: DaliConfigEntry) -> None:
    """Remove repair issues and cached metadata of a removed config entry."""
    ir.async_delete_issue(hass, DOMAIN, unaddressed_gear_issue_id(entry.entry_id))
    clear_bus_voltage_issues(hass, entry.entry_id)
    await Store(
        hass, STORAGE_VERSION, f"{DOMAIN}.{entry.entry_id}_metadata"
    ).async_remove()


async def async_remove_config_entry_device(
    hass: HomeAssistant, entry: DaliConfigEntry, device_entry: AnyDeviceEntry
) -> bool:
    """Allow removing a device only when its address no longer responds."""
    coordinator = entry.runtime_data
    gear_addresses = set(coordinator.data)
    device_addresses = {
        address for address, _instance, _type in coordinator.device_instances
    }
    gear_prefix = f"{entry.entry_id}_{GEAR_ID_INFIX}_"
    device_prefix = f"{entry.entry_id}_{CONTROL_DEVICE_ID_INFIX}_"
    for domain, identifier in device_entry.identifiers:
        if domain != DOMAIN:
            continue
        if identifier.startswith(device_prefix):
            address = identifier.removeprefix(device_prefix)
            active = device_addresses
        else:
            address = identifier.removeprefix(gear_prefix)
            active = gear_addresses
        if address.isdigit() and int(address) in active:
            return False
    return True
