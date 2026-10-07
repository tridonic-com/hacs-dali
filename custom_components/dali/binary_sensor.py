"""DALI-2 occupancy binary sensors."""

from collections.abc import Callable
from dataclasses import dataclass
from typing import override

from dali.device.occupancy import OccupancyEvent

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
    BinarySensorEntityDescription,
)
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from . import DaliConfigEntry
from .const import DEVICE_TYPE_EMERGENCY
from .coordinator import DaliCoordinator, DaliEmergencyData

PARALLEL_UPDATES = 0


@dataclass(frozen=True, kw_only=True)
class DaliEmergencyBinarySensorDescription(BinarySensorEntityDescription):
    """Description of a DT1 emergency status/failure bit."""

    value_fn: Callable[[DaliEmergencyData], bool | None]


def _bit(byte: int | None, mask: int) -> bool | None:
    """Return whether a status-byte bit is set, or None if the byte is absent."""
    if byte is None:
        return None
    return bool(byte & mask)


EMERGENCY_BINARY_SENSOR_TYPES: tuple[DaliEmergencyBinarySensorDescription, ...] = (
    DaliEmergencyBinarySensorDescription(
        key="inhibit_mode",
        translation_key="inhibit_mode",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda data: _bit(data.status, 0b00000001),
    ),
    DaliEmergencyBinarySensorDescription(
        key="function_test_done",
        translation_key="function_test_done",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda data: _bit(data.status, 0b00000010),
    ),
    DaliEmergencyBinarySensorDescription(
        key="duration_test_done",
        translation_key="duration_test_done",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda data: _bit(data.status, 0b00000100),
    ),
    DaliEmergencyBinarySensorDescription(
        key="battery_fully_charged",
        translation_key="battery_fully_charged",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda data: _bit(data.status, 0b00001000),
    ),
    DaliEmergencyBinarySensorDescription(
        key="function_test_pending",
        translation_key="function_test_pending",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda data: _bit(data.status, 0b00010000),
    ),
    DaliEmergencyBinarySensorDescription(
        key="duration_test_pending",
        translation_key="duration_test_pending",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda data: _bit(data.status, 0b00100000),
    ),
    DaliEmergencyBinarySensorDescription(
        key="identification_active",
        translation_key="identification_active",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda data: _bit(data.status, 0b01000000),
    ),
    DaliEmergencyBinarySensorDescription(
        key="hardwired_inhibit_active",
        translation_key="hardwired_inhibit_active",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda data: _bit(data.mode, 0b01000000),
    ),
    DaliEmergencyBinarySensorDescription(
        key="hardwired_switch_on",
        translation_key="hardwired_switch_on",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda data: _bit(data.mode, 0b10000000),
    ),
    DaliEmergencyBinarySensorDescription(
        key="circuit_failure",
        translation_key="circuit_failure",
        device_class=BinarySensorDeviceClass.PROBLEM,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda data: _bit(data.failure_status, 0b00000001),
    ),
    DaliEmergencyBinarySensorDescription(
        key="battery_duration_failure",
        translation_key="battery_duration_failure",
        device_class=BinarySensorDeviceClass.PROBLEM,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda data: _bit(data.failure_status, 0b00000010),
    ),
    DaliEmergencyBinarySensorDescription(
        key="battery_failure",
        translation_key="battery_failure",
        device_class=BinarySensorDeviceClass.PROBLEM,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda data: _bit(data.failure_status, 0b00000100),
    ),
    DaliEmergencyBinarySensorDescription(
        key="emergency_lamp_failure",
        translation_key="emergency_lamp_failure",
        device_class=BinarySensorDeviceClass.PROBLEM,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda data: _bit(data.failure_status, 0b00001000),
    ),
    DaliEmergencyBinarySensorDescription(
        key="function_test_max_delay_exceeded",
        translation_key="function_test_max_delay_exceeded",
        device_class=BinarySensorDeviceClass.PROBLEM,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda data: _bit(data.failure_status, 0b00010000),
    ),
    DaliEmergencyBinarySensorDescription(
        key="duration_test_max_delay_exceeded",
        translation_key="duration_test_max_delay_exceeded",
        device_class=BinarySensorDeviceClass.PROBLEM,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda data: _bit(data.failure_status, 0b00100000),
    ),
    DaliEmergencyBinarySensorDescription(
        key="function_test_failed",
        translation_key="function_test_failed",
        device_class=BinarySensorDeviceClass.PROBLEM,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda data: _bit(data.failure_status, 0b01000000),
    ),
    DaliEmergencyBinarySensorDescription(
        key="duration_test_failed",
        translation_key="duration_test_failed",
        device_class=BinarySensorDeviceClass.PROBLEM,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda data: _bit(data.failure_status, 0b10000000),
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: DaliConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up occupancy entities."""
    coordinator = entry.runtime_data
    async_add_entities(
        DaliOccupancy(coordinator, entry.entry_id, entry.title, address, instance)
        for address, instance, instance_type in coordinator.device_instances
        if instance_type == 3
    )

    known_emergency: set[int] = set()

    @callback
    def async_add_emergency_binary_sensors() -> None:
        entities: list[BinarySensorEntity] = []
        for address, gear in coordinator.data.items():
            if address in known_emergency:
                continue
            if DEVICE_TYPE_EMERGENCY not in gear.device_types:
                continue
            known_emergency.add(address)
            entities.extend(
                DaliEmergencyBinarySensor(
                    coordinator, entry.entry_id, entry.title, address, description
                )
                for description in EMERGENCY_BINARY_SENSOR_TYPES
            )
        async_add_entities(entities)

    async_add_emergency_binary_sensors()
    entry.async_on_unload(
        coordinator.async_add_listener(async_add_emergency_binary_sensors)
    )


class DaliOccupancy(BinarySensorEntity):
    """Representation of a DALI-2 occupancy instance."""

    _attr_has_entity_name = True
    _attr_device_class = BinarySensorDeviceClass.OCCUPANCY

    def __init__(
        self,
        coordinator: DaliCoordinator,
        entry_id: str,
        title: str,
        address: int,
        instance: int,
    ) -> None:
        """Initialize the entity."""
        self._coordinator = coordinator
        self._key = (address, instance)
        self._attr_unique_id = f"{entry_id}_{address}_{instance}_occupancy"
        self._attr_device_info = coordinator.device_info(
            entry_id, title, address, input_device=True
        )
        coordinator.async_add_event_listener(self._handle_event)

    @property
    @override
    def available(self) -> bool:
        """Return whether the interface is available."""
        return self._coordinator.last_update_success

    @property
    @override
    def is_on(self) -> bool | None:
        """Return the last occupancy state."""
        event = self._coordinator.event_data.get(self._key)
        return event.event_data.occupied if isinstance(event, OccupancyEvent) else None

    @callback
    def _handle_event(self, event: object) -> None:
        """Handle an occupancy event."""
        if (
            isinstance(event, OccupancyEvent)
            and event.short_address is not None
            and (
                event.short_address.address,
                event.instance_number,
            )
            == self._key
        ):
            self.async_write_ha_state()


class DaliEmergencyBinarySensor(CoordinatorEntity[DaliCoordinator], BinarySensorEntity):
    """Representation of one DT1 emergency status or failure bit."""

    _attr_has_entity_name = True
    entity_description: DaliEmergencyBinarySensorDescription

    def __init__(
        self,
        coordinator: DaliCoordinator,
        entry_id: str,
        title: str,
        address: int,
        description: DaliEmergencyBinarySensorDescription,
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
        """Return whether the gear is responding with emergency data."""
        gear = self.coordinator.data.get(self._address)
        return super().available and gear is not None and gear.emergency is not None

    @property
    @override
    def is_on(self) -> bool | None:
        """Return whether the described status/failure bit is set."""
        gear = self.coordinator.data.get(self._address)
        if gear is None or gear.emergency is None:
            return None
        return self.entity_description.value_fn(gear.emergency)
