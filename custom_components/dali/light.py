"""Support for Tridonic DALI lights."""

from collections.abc import Generator
from typing import Any, override

from dali.address import GearShort
from dali.command import Command, Response
from dali.exceptions import DALISequenceError, ResponseError
from dali.gear.colour import (
    Activate,
    SetTemporaryXCoordinate,
    SetTemporaryYCoordinate,
    tc_kelvin_mirek,
)
from dali.gear.general import DAPC, DTR0, DTR1
from dali.gear.sequences import SetDT8ColourValueTc

from homeassistant.components.light import ColorMode, LightEntity
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from . import DaliConfigEntry
from .const import DEVICE_TYPE_COLOUR, DEVICE_TYPE_LED, DOMAIN
from .coordinator import (
    DaliCoordinator,
    DaliGearData,
    _brightness_to_dali_level,
    _dali_level_to_brightness,
)

PARALLEL_UPDATES = 1


async def async_setup_entry(
    hass: HomeAssistant,
    entry: DaliConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the DALI light platform."""
    coordinator = entry.runtime_data
    known_addresses: set[int] = set()

    def async_add_new_entities() -> None:
        new_addresses = set(coordinator.data) - known_addresses
        known_addresses.update(new_addresses)
        async_add_entities(
            DaliLight(coordinator, entry.entry_id, entry.title, address)
            for address in new_addresses
            if _is_light(coordinator.data[address])
        )

    async_add_new_entities()
    entry.async_on_unload(coordinator.async_add_listener(async_add_new_entities))


def _is_light(gear: DaliGearData) -> bool:
    """Return whether a gear should be exposed as a light.

    Dimmable (DT6) and colour (DT8) gear are always lights. A pure emergency
    (DT1) gear is only a light when it is a maintained type that can be driven
    from the mains; a non-maintained emergency gear has no normal-mode output.
    """
    if DEVICE_TYPE_LED in gear.device_types or DEVICE_TYPE_COLOUR in gear.device_types:
        return True
    return gear.emergency is not None and gear.emergency.controllable


class DaliLight(CoordinatorEntity[DaliCoordinator], LightEntity):
    """Representation of a DALI light."""

    _attr_has_entity_name = True
    _attr_name = None
    _attr_supported_color_modes = {ColorMode.BRIGHTNESS}
    _attr_color_mode = ColorMode.BRIGHTNESS

    def __init__(
        self, coordinator: DaliCoordinator, entry_id: str, title: str, address: int
    ) -> None:
        """Initialize the light."""
        super().__init__(coordinator)
        self._address = address
        self._attr_unique_id = f"{entry_id}_{address}"
        self._attr_device_info = coordinator.device_info(entry_id, title, address)
        gear_data = coordinator.data[address]
        color_modes = {ColorMode.BRIGHTNESS}
        if gear_data.supports_color_temperature:
            color_modes.add(ColorMode.COLOR_TEMP)
            self._attr_min_color_temp_kelvin = tc_kelvin_mirek(
                gear_data.color_temp_max_mired or 500
            )
            self._attr_max_color_temp_kelvin = tc_kelvin_mirek(
                gear_data.color_temp_min_mired or 153
            )
        if gear_data.supports_xy:
            color_modes.add(ColorMode.XY)
        if len(color_modes) > 1:
            color_modes.discard(ColorMode.BRIGHTNESS)
        self._attr_supported_color_modes = color_modes

    @property
    @override
    def available(self) -> bool:
        """Return whether the DALI gear is responding."""
        return super().available and self._address in self.coordinator.data

    @property
    @override
    def is_on(self) -> bool:
        """Return whether the DALI gear is on."""
        return bool(self.coordinator.data[self._address].level)

    @property
    @override
    def brightness(self) -> int:
        """Return the current DALI arc power level."""
        return self.coordinator.data[self._address].level or 0

    @property
    @override
    def color_mode(self) -> ColorMode:
        """Return the currently reported color mode."""
        modes = self._attr_supported_color_modes
        if ColorMode.XY in modes and ColorMode.COLOR_TEMP in modes:
            gear_data = self.coordinator.data[self._address]
            if gear_data.color_type_tc_active is False:
                return ColorMode.XY
            return ColorMode.COLOR_TEMP
        if ColorMode.COLOR_TEMP in modes:
            return ColorMode.COLOR_TEMP
        if ColorMode.XY in modes:
            return ColorMode.XY
        return ColorMode.BRIGHTNESS

    @property
    @override
    def color_temp_kelvin(self) -> int | None:
        """Return the current color temperature."""
        value = self.coordinator.data[self._address].color_temp_mired
        return tc_kelvin_mirek(value) if value else None

    @property
    @override
    def xy_color(self) -> tuple[float, float] | None:
        """Return the current CIE xy color."""
        return self.coordinator.data[self._address].xy_color

    @override
    async def async_turn_on(self, **kwargs: Any) -> None:
        """Turn the light on."""
        try:
            gear_data = self.coordinator.data[self._address]
            if color_temp := kwargs.get("color_temp_kelvin"):
                await self.coordinator.driver.send(
                    SetDT8ColourValueTc(self._address, tc_kelvin_mirek(color_temp))
                )
            if xy_color := kwargs.get("xy_color"):
                await self.coordinator.driver.send(
                    _set_xy_color(GearShort(self._address), xy_color)
                )
            # Only drive the arc level when asked to, or to switch the light on;
            # a colour-only change must not disturb the current brightness.
            optimistic_level: int | None = None
            if "brightness" in kwargs or not gear_data.level:
                brightness = max(1, min(kwargs.get("brightness", 255), 255))
                level = _brightness_to_dali_level(
                    brightness, gear_data.linear_dimming, gear_data.min_level
                )
                await self.coordinator.driver.send(
                    DAPC(GearShort(self._address), level)
                )
                optimistic_level = _dali_level_to_brightness(
                    level, gear_data.linear_dimming, gear_data.min_level
                )
            await self.coordinator.async_update_gear(self._address, optimistic_level)
        except (OSError, TimeoutError, DALISequenceError, ResponseError) as err:
            raise HomeAssistantError(
                translation_domain=DOMAIN,
                translation_key="communication_error",
            ) from err

    @override
    async def async_turn_off(self, **kwargs: Any) -> None:
        """Turn the light off."""
        try:
            await self.coordinator.driver.send(DAPC(GearShort(self._address), 0))
            await self.coordinator.async_update_gear(self._address, 0)
        except (OSError, TimeoutError, DALISequenceError, ResponseError) as err:
            raise HomeAssistantError(
                translation_domain=DOMAIN,
                translation_key="communication_error",
            ) from err


def _set_xy_color(
    address: GearShort, xy_color: tuple[float, float]
) -> Generator[Command, Response | None]:
    """Create the DT8 sequence for setting an xy color."""
    for value, command in zip(
        xy_color, (SetTemporaryXCoordinate, SetTemporaryYCoordinate), strict=True
    ):
        raw_value = round(max(0, min(value, 1)) * 65535).to_bytes(2, "little")
        yield DTR0(raw_value[0])
        yield DTR1(raw_value[1])
        yield command(address)
    yield Activate(address)
