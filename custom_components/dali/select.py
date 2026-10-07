"""DALI control gear fade selects."""

from collections.abc import Callable
from dataclasses import dataclass
from typing import override

from dali.address import GearShort
from dali.command import Command
from dali.exceptions import DALISequenceError, ResponseError
from dali.gear.general import SetFadeRate, SetFadeTime

from homeassistant.components.select import SelectEntity, SelectEntityDescription
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from . import DaliConfigEntry
from .const import DOMAIN
from .coordinator import DaliCoordinator, DaliGearData
from .helpers import (
    FADE_RATE_CODES,
    FADE_RATE_OPTIONS,
    FADE_TIME_CODES,
    FADE_TIME_OPTIONS,
    set_dtr0_variable,
)

PARALLEL_UPDATES = 1


@dataclass(frozen=True, kw_only=True)
class DaliGearSelectDescription(SelectEntityDescription):
    """Description of a DALI control gear fade setting."""

    command: type[Command]
    value_fn: Callable[[DaliGearData], int | None]
    option_for_code: dict[int, str]
    code_for_option: dict[str, int]


SELECT_TYPES: tuple[DaliGearSelectDescription, ...] = (
    DaliGearSelectDescription(
        key="fade_time",
        translation_key="fade_time",
        command=SetFadeTime,
        entity_category=EntityCategory.CONFIG,
        options=list(FADE_TIME_OPTIONS.values()),
        option_for_code=FADE_TIME_OPTIONS,
        code_for_option=FADE_TIME_CODES,
        value_fn=lambda gear: gear.fade_time,
    ),
    DaliGearSelectDescription(
        key="fade_rate",
        translation_key="fade_rate",
        command=SetFadeRate,
        entity_category=EntityCategory.CONFIG,
        options=list(FADE_RATE_OPTIONS.values()),
        option_for_code=FADE_RATE_OPTIONS,
        code_for_option=FADE_RATE_CODES,
        value_fn=lambda gear: gear.fade_rate,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: DaliConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the DALI fade select platform."""
    coordinator = entry.runtime_data
    known: set[int] = set()

    @callback
    def async_add_selects() -> None:
        new_addresses = set(coordinator.data) - known
        known.update(new_addresses)
        async_add_entities(
            DaliGearSelect(
                coordinator, entry.entry_id, entry.title, address, description
            )
            for address in new_addresses
            for description in SELECT_TYPES
        )

    async_add_selects()
    entry.async_on_unload(coordinator.async_add_listener(async_add_selects))


class DaliGearSelect(CoordinatorEntity[DaliCoordinator], SelectEntity):
    """Representation of a DALI control gear fade setting."""

    _attr_has_entity_name = True
    entity_description: DaliGearSelectDescription

    def __init__(
        self,
        coordinator: DaliCoordinator,
        entry_id: str,
        title: str,
        address: int,
        description: DaliGearSelectDescription,
    ) -> None:
        """Initialize the entity."""
        super().__init__(coordinator)
        self.entity_description = description
        self._address = address
        self._attr_unique_id = f"{entry_id}_{address}_{description.key}"
        self._attr_device_info = coordinator.device_info(entry_id, title, address)

    @property
    @override
    def available(self) -> bool:
        """Return whether the DALI gear is responding."""
        return super().available and self._address in self.coordinator.data

    @property
    @override
    def current_option(self) -> str | None:
        """Return the fade setting the gear currently has stored.

        A gear can answer with a reserved code, or not answer at all, which
        reads as unknown rather than being reported as an error.
        """
        gear = self.coordinator.data.get(self._address)
        if gear is None:
            return None
        code = self.entity_description.value_fn(gear)
        if code is None:
            return None
        return self.entity_description.option_for_code.get(code)

    @override
    async def async_select_option(self, option: str) -> None:
        """Write the fade setting to the gear and read back what it stored."""
        try:
            await self.coordinator.driver.send(
                set_dtr0_variable(
                    self.entity_description.command,
                    GearShort(self._address),
                    self.entity_description.code_for_option[option],
                )
            )
        except (OSError, TimeoutError, DALISequenceError, ResponseError) as err:
            raise HomeAssistantError(
                translation_domain=DOMAIN,
                translation_key="communication_error",
            ) from err
        await self.coordinator.async_update_gear_config(self._address)
