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
from .coordinator import DaliCoordinator, DaliDiagnosticsData, DaliEmergencyData

PARALLEL_UPDATES = 0


@dataclass(frozen=True, kw_only=True)
class DaliEmergencyBinarySensorDescription(BinarySensorEntityDescription):
    """Description of a DT1 emergency status/failure bit."""

    value_fn: Callable[[DaliEmergencyData], bool | None]


def _status_bit(
    select: Callable[[DaliEmergencyData], object | None], attr: str
) -> Callable[[DaliEmergencyData], bool | None]:
    """Build a value_fn returning one decoded status bit.

    ``select`` picks the decoded status byte off the emergency data; the result
    is None when the gear did not answer that byte.
    """

    def value_fn(data: DaliEmergencyData) -> bool | None:
        byte = select(data)
        return getattr(byte, attr) if byte is not None else None

    return value_fn


EMERGENCY_BINARY_SENSOR_TYPES: tuple[DaliEmergencyBinarySensorDescription, ...] = (
    DaliEmergencyBinarySensorDescription(
        key="inhibit_mode",
        translation_key="inhibit_mode",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=_status_bit(lambda data: data.status, "inhibit_mode"),
    ),
    DaliEmergencyBinarySensorDescription(
        key="function_test_done",
        translation_key="function_test_done",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=_status_bit(
            lambda data: data.status, "function_test_done_and_result_valid"
        ),
    ),
    DaliEmergencyBinarySensorDescription(
        key="duration_test_done",
        translation_key="duration_test_done",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=_status_bit(
            lambda data: data.status, "duration_test_done_and_result_valid"
        ),
    ),
    DaliEmergencyBinarySensorDescription(
        key="battery_fully_charged",
        translation_key="battery_fully_charged",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=_status_bit(lambda data: data.status, "battery_fully_charged"),
    ),
    DaliEmergencyBinarySensorDescription(
        key="function_test_pending",
        translation_key="function_test_pending",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=_status_bit(lambda data: data.status, "function_test_pending"),
    ),
    DaliEmergencyBinarySensorDescription(
        key="duration_test_pending",
        translation_key="duration_test_pending",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=_status_bit(lambda data: data.status, "duration_test_pending"),
    ),
    DaliEmergencyBinarySensorDescription(
        key="identification_active",
        translation_key="identification_active",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=_status_bit(lambda data: data.status, "identification_active"),
    ),
    DaliEmergencyBinarySensorDescription(
        key="hardwired_inhibit_active",
        translation_key="hardwired_inhibit_active",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=_status_bit(lambda data: data.mode, "hardwired_inhibit_active"),
    ),
    DaliEmergencyBinarySensorDescription(
        key="hardwired_switch_on",
        translation_key="hardwired_switch_on",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=_status_bit(lambda data: data.mode, "hardwired_switch_on"),
    ),
    DaliEmergencyBinarySensorDescription(
        key="circuit_failure",
        translation_key="circuit_failure",
        device_class=BinarySensorDeviceClass.PROBLEM,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=_status_bit(lambda data: data.failure_status, "circuit_failure"),
    ),
    DaliEmergencyBinarySensorDescription(
        key="battery_duration_failure",
        translation_key="battery_duration_failure",
        device_class=BinarySensorDeviceClass.PROBLEM,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=_status_bit(
            lambda data: data.failure_status, "battery_duration_failure"
        ),
    ),
    DaliEmergencyBinarySensorDescription(
        key="battery_failure",
        translation_key="battery_failure",
        device_class=BinarySensorDeviceClass.PROBLEM,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=_status_bit(lambda data: data.failure_status, "battery_failure"),
    ),
    DaliEmergencyBinarySensorDescription(
        key="emergency_lamp_failure",
        translation_key="emergency_lamp_failure",
        device_class=BinarySensorDeviceClass.PROBLEM,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=_status_bit(
            lambda data: data.failure_status, "emergency_lamp_failure"
        ),
    ),
    DaliEmergencyBinarySensorDescription(
        key="function_test_max_delay_exceeded",
        translation_key="function_test_max_delay_exceeded",
        device_class=BinarySensorDeviceClass.PROBLEM,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=_status_bit(
            lambda data: data.failure_status, "function_test_max_delay_exceeded"
        ),
    ),
    DaliEmergencyBinarySensorDescription(
        key="duration_test_max_delay_exceeded",
        translation_key="duration_test_max_delay_exceeded",
        device_class=BinarySensorDeviceClass.PROBLEM,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=_status_bit(
            lambda data: data.failure_status, "duration_test_max_delay_exceeded"
        ),
    ),
    DaliEmergencyBinarySensorDescription(
        key="function_test_failed",
        translation_key="function_test_failed",
        device_class=BinarySensorDeviceClass.PROBLEM,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=_status_bit(lambda data: data.failure_status, "function_test_failed"),
    ),
    DaliEmergencyBinarySensorDescription(
        key="duration_test_failed",
        translation_key="duration_test_failed",
        device_class=BinarySensorDeviceClass.PROBLEM,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=_status_bit(lambda data: data.failure_status, "duration_test_failed"),
    ),
)


@dataclass(frozen=True, kw_only=True)
class DaliGearDiagnosticBinarySensorDescription(BinarySensorEntityDescription):
    """Description of a memory bank 205 or 206 failure condition."""

    value_fn: Callable[[DaliDiagnosticsData], bool | None]


GEAR_DIAGNOSTIC_BINARY_SENSOR_TYPES: tuple[
    DaliGearDiagnosticBinarySensorDescription, ...
] = (
    DaliGearDiagnosticBinarySensorDescription(
        key="control_gear_overall_failure",
        translation_key="control_gear_overall_failure",
        device_class=BinarySensorDeviceClass.PROBLEM,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda data: data.control_gear_overall_failure,
    ),
    DaliGearDiagnosticBinarySensorDescription(
        key="control_gear_undervoltage",
        translation_key="control_gear_undervoltage",
        device_class=BinarySensorDeviceClass.PROBLEM,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda data: data.control_gear_undervoltage,
    ),
    DaliGearDiagnosticBinarySensorDescription(
        key="control_gear_overvoltage",
        translation_key="control_gear_overvoltage",
        device_class=BinarySensorDeviceClass.PROBLEM,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda data: data.control_gear_overvoltage,
    ),
    DaliGearDiagnosticBinarySensorDescription(
        key="control_gear_output_power_limitation",
        translation_key="control_gear_output_power_limitation",
        device_class=BinarySensorDeviceClass.PROBLEM,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda data: data.control_gear_output_power_limitation,
    ),
    DaliGearDiagnosticBinarySensorDescription(
        key="control_gear_thermal_derating",
        translation_key="control_gear_thermal_derating",
        device_class=BinarySensorDeviceClass.PROBLEM,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda data: data.control_gear_thermal_derating,
    ),
    DaliGearDiagnosticBinarySensorDescription(
        key="control_gear_thermal_shutdown",
        translation_key="control_gear_thermal_shutdown",
        device_class=BinarySensorDeviceClass.PROBLEM,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda data: data.control_gear_thermal_shutdown,
    ),
    DaliGearDiagnosticBinarySensorDescription(
        key="light_source_overall_failure",
        translation_key="light_source_overall_failure",
        device_class=BinarySensorDeviceClass.PROBLEM,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda data: data.light_source_overall_failure,
    ),
    DaliGearDiagnosticBinarySensorDescription(
        key="light_source_short_circuit",
        translation_key="light_source_short_circuit",
        device_class=BinarySensorDeviceClass.PROBLEM,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda data: data.light_source_short_circuit,
    ),
    DaliGearDiagnosticBinarySensorDescription(
        key="light_source_open_circuit",
        translation_key="light_source_open_circuit",
        device_class=BinarySensorDeviceClass.PROBLEM,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda data: data.light_source_open_circuit,
    ),
    DaliGearDiagnosticBinarySensorDescription(
        key="light_source_thermal_derating",
        translation_key="light_source_thermal_derating",
        device_class=BinarySensorDeviceClass.PROBLEM,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda data: data.light_source_thermal_derating,
    ),
    DaliGearDiagnosticBinarySensorDescription(
        key="light_source_thermal_shutdown",
        translation_key="light_source_thermal_shutdown",
        device_class=BinarySensorDeviceClass.PROBLEM,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda data: data.light_source_thermal_shutdown,
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

    known_diagnostics: set[int] = set()

    @callback
    def async_add_gear_diagnostic_binary_sensors() -> None:
        entities: list[BinarySensorEntity] = []
        for address, gear in coordinator.data.items():
            if gear.diagnostics is None or address in known_diagnostics:
                continue
            known_diagnostics.add(address)
            entities.extend(
                DaliGearDiagnosticBinarySensor(
                    coordinator, entry.entry_id, entry.title, address, description
                )
                for description in GEAR_DIAGNOSTIC_BINARY_SENSOR_TYPES
            )
        async_add_entities(entities)

    async_add_gear_diagnostic_binary_sensors()
    entry.async_on_unload(
        coordinator.async_add_listener(async_add_gear_diagnostic_binary_sensors)
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


class DaliGearDiagnosticBinarySensor(
    CoordinatorEntity[DaliCoordinator], BinarySensorEntity
):
    """Representation of one memory bank 205 or 206 failure condition.

    The gear latches each condition until it clears, so these report what the
    gear last observed rather than what the last read happened to catch.
    """

    _attr_has_entity_name = True
    entity_description: DaliGearDiagnosticBinarySensorDescription

    def __init__(
        self,
        coordinator: DaliCoordinator,
        entry_id: str,
        title: str,
        address: int,
        description: DaliGearDiagnosticBinarySensorDescription,
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
        """Return whether the diagnostics memory banks have been read."""
        gear = self.coordinator.data.get(self._address)
        return super().available and gear is not None and gear.diagnostics is not None

    @property
    @override
    def is_on(self) -> bool | None:
        """Return whether the described failure condition is present."""
        gear = self.coordinator.data.get(self._address)
        if gear is None or gear.diagnostics is None:
            return None
        return self.entity_description.value_fn(gear.diagnostics)
