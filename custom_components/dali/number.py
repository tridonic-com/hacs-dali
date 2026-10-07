"""DALI control gear configuration numbers."""

from collections.abc import Callable
from dataclasses import dataclass
from typing import override

from dali.address import GearShort
from dali.command import Command
from dali.exceptions import DALISequenceError, ResponseError
from dali.gear.general import (
    SetExtendedFadeTime,
    SetMaxLevel,
    SetMinLevel,
    SetSystemFailureLevel,
)

from homeassistant.components.number import (
    NumberDeviceClass,
    NumberEntity,
    NumberEntityDescription,
    NumberMode,
)
from homeassistant.const import EntityCategory, UnitOfTime
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from . import DaliConfigEntry
from .const import DOMAIN
from .coordinator import DaliCoordinator, DaliGearData
from .helpers import (
    EXTENDED_FADE_TIME_STEP,
    MASK_LEVEL,
    MAX_EXTENDED_FADE_TIME,
    MIN_EXTENDED_FADE_TIME,
    encode_extended_fade_time,
    extended_fade_time_seconds,
    set_dtr0_variable,
)

PARALLEL_UPDATES = 1


@dataclass(frozen=True, kw_only=True)
class DaliGearNumberDescription(NumberEntityDescription):
    """Description of a writable DALI control gear configuration variable."""

    command: type[Command]
    value_fn: Callable[[DaliGearData], float | None]
    encode_fn: Callable[[float], int]
    supported_fn: Callable[[DaliGearData], bool] = lambda gear: True


NUMBER_TYPES: tuple[DaliGearNumberDescription, ...] = (
    DaliGearNumberDescription(
        key="min_level",
        translation_key="min_level",
        command=SetMinLevel,
        entity_category=EntityCategory.CONFIG,
        mode=NumberMode.BOX,
        native_min_value=1,
        native_max_value=254,
        native_step=1,
        value_fn=lambda gear: gear.min_level,
        encode_fn=int,
    ),
    DaliGearNumberDescription(
        key="max_level",
        translation_key="max_level",
        command=SetMaxLevel,
        entity_category=EntityCategory.CONFIG,
        mode=NumberMode.BOX,
        native_min_value=1,
        native_max_value=254,
        native_step=1,
        value_fn=lambda gear: gear.max_level,
        encode_fn=int,
    ),
    DaliGearNumberDescription(
        key="system_failure_level",
        translation_key="system_failure_level",
        command=SetSystemFailureLevel,
        entity_category=EntityCategory.CONFIG,
        mode=NumberMode.BOX,
        # 0 switches the lamp off on a bus failure and MASK keeps it where it
        # is, so the range spans the whole byte rather than the dimming range.
        native_min_value=0,
        native_max_value=MASK_LEVEL,
        native_step=1,
        value_fn=lambda gear: gear.system_failure_level,
        encode_fn=int,
    ),
    DaliGearNumberDescription(
        key="extended_fade_time",
        translation_key="extended_fade_time",
        command=SetExtendedFadeTime,
        entity_category=EntityCategory.CONFIG,
        device_class=NumberDeviceClass.DURATION,
        native_unit_of_measurement=UnitOfTime.SECONDS,
        mode=NumberMode.BOX,
        native_min_value=MIN_EXTENDED_FADE_TIME,
        native_max_value=MAX_EXTENDED_FADE_TIME,
        native_step=EXTENDED_FADE_TIME_STEP,
        value_fn=lambda gear: extended_fade_time_seconds(
            gear.extended_fade_time_base, gear.extended_fade_time_multiplier
        ),
        # Only DALI-2 gear implements this; an entity permanently reading
        # unknown is worse than no entity at all.
        supported_fn=lambda gear: gear.extended_fade_time_multiplier is not None,
        encode_fn=encode_extended_fade_time,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: DaliConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the DALI configuration number platform."""
    coordinator = entry.runtime_data
    known: set[tuple[int, str]] = set()

    @callback
    def async_add_numbers() -> None:
        entities: list[NumberEntity] = []
        for address, gear in coordinator.data.items():
            for description in NUMBER_TYPES:
                key = (address, description.key)
                if key in known or not description.supported_fn(gear):
                    continue
                known.add(key)
                entities.append(
                    DaliGearNumber(
                        coordinator, entry.entry_id, entry.title, address, description
                    )
                )
        async_add_entities(entities)

    async_add_numbers()
    entry.async_on_unload(coordinator.async_add_listener(async_add_numbers))


class DaliGearNumber(CoordinatorEntity[DaliCoordinator], NumberEntity):
    """Representation of a writable DALI control gear configuration variable."""

    _attr_has_entity_name = True
    entity_description: DaliGearNumberDescription

    def __init__(
        self,
        coordinator: DaliCoordinator,
        entry_id: str,
        title: str,
        address: int,
        description: DaliGearNumberDescription,
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
    def native_value(self) -> float | None:
        """Return the value the gear currently has stored."""
        gear = self.coordinator.data.get(self._address)
        if gear is None:
            return None
        return self.entity_description.value_fn(gear)

    @override
    async def async_set_native_value(self, value: float) -> None:
        """Write the value to the gear and read back what it stored."""
        try:
            await self.coordinator.driver.send(
                set_dtr0_variable(
                    self.entity_description.command,
                    GearShort(self._address),
                    self.entity_description.encode_fn(value),
                )
            )
        except (OSError, TimeoutError, DALISequenceError, ResponseError) as err:
            raise HomeAssistantError(
                translation_domain=DOMAIN,
                translation_key="communication_error",
            ) from err
        # The gear clamps levels against its physical minimum and the opposing
        # limit, and snaps the extended fade time to a representable step.
        await self.coordinator.async_update_gear_config(self._address)
