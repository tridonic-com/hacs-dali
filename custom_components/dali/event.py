"""DALI-2 pushbutton event entities."""

from typing import override

from dali.device.pushbutton import (
    ButtonFree,
    ButtonPressed,
    ButtonReleased,
    ButtonStuck,
    DoublePress,
    LongPressRepeat,
    LongPressStart,
    LongPressStop,
    ShortPress,
    _PushbuttonEvent,
)

from homeassistant.components.event import EventDeviceClass, EventEntity
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import DaliConfigEntry
from .coordinator import DaliCoordinator

PARALLEL_UPDATES = 0

EVENT_TYPES: dict[type[_PushbuttonEvent], str] = {
    ButtonReleased: "button_released",
    ButtonPressed: "button_pressed",
    ShortPress: "short_press",
    DoublePress: "double_press",
    LongPressStart: "long_press_start",
    LongPressRepeat: "long_press_repeat",
    LongPressStop: "long_press_stop",
    ButtonFree: "button_free",
    ButtonStuck: "button_stuck",
}


async def async_setup_entry(
    hass: HomeAssistant,
    entry: DaliConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up pushbutton event entities."""
    coordinator = entry.runtime_data
    known: set[tuple[int, int]] = set()

    @callback
    def async_add_new_entities() -> None:
        new_instances = [
            (address, instance)
            for address, instance, instance_type in coordinator.device_instances
            if instance_type == 1 and (address, instance) not in known
        ]
        known.update(new_instances)
        async_add_entities(
            DaliPushbuttonEvent(
                coordinator, entry.entry_id, entry.title, address, instance
            )
            for address, instance in new_instances
        )

    async_add_new_entities()
    entry.async_on_unload(coordinator.async_add_listener(async_add_new_entities))


class DaliPushbuttonEvent(EventEntity):
    """Representation of a DALI-2 pushbutton instance."""

    _attr_has_entity_name = True
    _attr_translation_key = "pushbutton"
    _attr_device_class = EventDeviceClass.BUTTON
    _attr_event_types = list(EVENT_TYPES.values())

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
        self._attr_translation_placeholders = {"instance": str(instance)}
        self._attr_unique_id = f"{entry_id}_{address}_{instance}_pushbutton"
        self._attr_device_info = coordinator.device_info(
            entry_id, title, address, input_device=True
        )

    @override
    async def async_added_to_hass(self) -> None:
        """Subscribe to DALI-2 events once the entity is registered."""
        self.async_on_remove(
            self._coordinator.async_add_event_listener(self._handle_event)
        )

    @property
    @override
    def available(self) -> bool:
        """Return whether the interface is available."""
        return self._coordinator.last_update_success

    @callback
    def _handle_event(self, event: object) -> None:
        """Trigger the entity on a matching pushbutton event."""
        if (
            isinstance(event, _PushbuttonEvent)
            and event.short_address is not None
            and (
                event.short_address.address,
                event.instance_number,
            )
            == self._key
            and (event_type := EVENT_TYPES.get(type(event))) is not None
        ):
            self._trigger_event(event_type)
            self.async_write_ha_state()
