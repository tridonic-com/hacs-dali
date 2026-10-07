"""Data update coordinator for the Tridonic DALI integration."""

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import asdict, dataclass, replace
from datetime import timedelta
import logging
import math
from typing import Any, override

from dali.address import (
    DeviceBroadcast,
    DeviceShort,
    GearBroadcast,
    GearShort,
    InstanceNumber,
)
from dali.device.general import (
    DTR0,
    DTR1,
    DTR2,
    EnableInstance,
    EventScheme,
    QueryMissingShortAddress as QueryMissingDeviceShortAddress,
    QueryResolution,
    SetEventFilter,
    SetEventScheme,
)
from dali.device.general_sensor import (
    InstanceEventFilter,
    MeasurementVariable,
    QueryMeasurementVariable,
)
from dali.device.sequences import Commissioning as CommissionDevices
from dali.driver.serial import DriverLubaRs232
from dali.exceptions import (
    DALISequenceError,
    MemoryLocationNotImplemented,
    ResponseError,
)
from dali.gear.colour import (
    QueryColourStatus,
    QueryColourTypeFeatures,
    QueryColourValueDTR,
)
from dali.gear.general import (
    QueryActualLevel,
    QueryControlGearPresent,
    QueryExtendedFadeTime,
    QueryFadeTimeFadeRate,
    QueryMaxLevel,
    QueryMinLevel,
    QueryMissingShortAddress,
    QuerySystemFailureLevel,
)
from dali.gear.led import QueryDimmingCurve
from dali.gear.sequences import QueryDT8ColourValue, QueryEmergencyInformation
from dali.memory import emergency, info
from dali.sequences import Commissioning, QueryDeviceTypes, progress

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import device_registry as dr, issue_registry as ir
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.storage import Store
from homeassistant.helpers.typing import UNDEFINED
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .const import (
    DEVICE_INSTANCE_TYPE_NAMES,
    DEVICE_TYPE_COLOUR,
    DEVICE_TYPE_EMERGENCY,
    DEVICE_TYPE_LED,
    DOMAIN,
    GEAR_DEVICE_TYPE_NAMES,
    ISSUE_UNADDRESSED_CONTROLDEVICE,
    ISSUE_UNADDRESSED_GEAR,
    SUPPORTED_GEAR_DEVICE_TYPES,
    registry_identifier,
    unaddressed_control_device_issue_id,
    unaddressed_gear_issue_id,
)
from .helpers import MASK_LEVEL

SCAN_INTERVAL = timedelta(seconds=30)
FULL_SCAN_INTERVAL = timedelta(minutes=5)
LOGGER = logging.getLogger(__name__)

# Identification metadata is static per device, so it is persisted and restored
# across restarts to avoid re-reading whole memory banks byte by byte each time.
STORAGE_VERSION = 2
METADATA_SAVE_DELAY = 10

# Tridonic's GTIN prefix. Their firmware version bytes carry a build number
# where IEC 62386-102 has a plain minor version.
TRIDONIC_GTIN_PREFIX = "9006210"

# Sensor metadata is read once and cached, so a single corrupted-but-parseable
# response skews every later measurement. Confirm each value with repeated reads.
METADATA_QUERY_ATTEMPTS = 3
# Widest input-value resolution IEC 62386-306 defines, in bits.
MAX_SENSOR_RESOLUTION = 32


@dataclass(frozen=True, slots=True)
class DaliDeviceData:
    """Identification data shared by DALI gears and input devices."""

    gtin: int | None = None
    identification_number: int | None = None
    serial_no: str | None = None
    batch_no: str | None = None
    firmware_version: str | None = None
    hardware_version: str | None = None


@dataclass(frozen=True, slots=True)
class DaliEmergencyData:
    """Status and measurement data for one DT1 (IEC 62386-202) emergency gear.

    The four status bytes are kept raw so entities can expose individual bits;
    the measurement values are plain integers as reported by the gear (None
    where the gear answers MASK or does not answer). The remaining fields are
    the memory-bank-208 diagnostics.
    """

    mode: int | None = None
    features: int | None = None
    failure_status: int | None = None
    status: int | None = None
    battery_charge: int | None = None
    emergency_level: int | None = None
    duration_test_result: int | None = None
    lamp_emergency_time: int | None = None
    lamp_total_operation_time: int | None = None
    rated_duration: int | None = None
    control_gear_temperature: int | None = None
    control_gear_max_reference_temperature: int | None = None
    min_control_gear_temperature_total: int | None = None
    max_control_gear_temperature_total: int | None = None
    average_power_during_charging: float | None = None
    average_power_during_maintenance: float | None = None
    battery_recharge_time: int | None = None
    function_test_time: int | None = None
    battery_failure_counter: int | None = None
    lamp_emergency_time_total: int | None = None
    lamp_emergency_time_current_battery: int | None = None
    battery_connected_time_total: int | None = None
    emergency_mode_counter_total: int | None = None
    rest_mode_counter: int | None = None
    start_function_test_counter: int | None = None
    start_duration_test_counter_total: int | None = None
    function_test_failed_counter_total: int | None = None
    duration_test_failed_counter_total: int | None = None

    @property
    def controllable(self) -> bool:
        """Return whether the gear can be driven as a normal (maintained) light.

        The features byte reports the gear type; a maintained or switched-
        maintained gear keeps the lamp lit from the mains and so behaves as a
        dimmable light, whereas a non-maintained gear only lights in emergency.
        """
        return self.features is not None and bool(self.features & 0b110)


@dataclass(frozen=True, slots=True)
class DaliGearConfig:
    """Writable IEC 62386-102 configuration variables of one control gear.

    These change only when written, so they are read on the full bus scan and
    cached in between rather than queried on every poll.
    """

    min_level: int = 1
    max_level: int | None = None
    system_failure_level: int | None = None
    fade_time: int | None = None
    fade_rate: int | None = None
    extended_fade_time_base: int | None = None
    extended_fade_time_multiplier: int | None = None


@dataclass(frozen=True, slots=True)
class DaliGearData(DaliDeviceData):
    """State and identification data for one DALI control gear."""

    level: int | None = None
    min_level: int = 1
    max_level: int | None = None
    system_failure_level: int | None = None
    fade_time: int | None = None
    fade_rate: int | None = None
    extended_fade_time_base: int | None = None
    extended_fade_time_multiplier: int | None = None
    linear_dimming: bool = False
    device_types: tuple[int, ...] = ()
    supports_color_temperature: bool = False
    supports_xy: bool = False
    color_type_tc_active: bool | None = None
    color_temp_mired: int | None = None
    color_temp_min_mired: int | None = None
    color_temp_max_mired: int | None = None
    xy_color: tuple[float, float] | None = None
    emergency: DaliEmergencyData | None = None


@dataclass(frozen=True, slots=True)
class DaliGeneralSensorData(DaliDeviceData):
    """State and identification data for one Part 306 general sensor."""

    quantity_name: int | None = None
    unit_of_measurement: int | None = None
    resolution: int | None = None
    magnitude: int | None = None
    input_signal_signed: bool | None = None


class DaliMetadataStore(Store[dict[str, Any]]):
    """Store for the cached memory bank 0 identification data."""

    @override
    async def _async_migrate_func(
        self,
        old_major_version: int,
        old_minor_version: int,
        old_data: dict[str, Any],
    ) -> dict[str, Any]:
        """Discard a cache written by an earlier decoding of memory bank 0.

        The bank is static, so the entries are simply dropped and read again
        rather than converted; the deferred enrichment picks them up in the
        background on the next start.
        """
        return {}


class DaliCoordinator(DataUpdateCoordinator[dict[int, DaliGearData]]):
    """Coordinate DALI gear discovery and state updates."""

    config_entry: ConfigEntry

    def __init__(
        self,
        hass: HomeAssistant,
        driver: DriverLubaRs232,
        config_entry: ConfigEntry,
    ) -> None:
        """Initialize the coordinator."""
        super().__init__(
            hass,
            logger=LOGGER,
            name=DOMAIN,
            config_entry=config_entry,
            update_interval=SCAN_INTERVAL,
        )
        self.driver = driver
        self._last_full_scan: float | None = None
        self._discovered = False
        self._initial_refresh = True
        self._metadata: dict[int, DaliDeviceData] = {}
        self._device_metadata: dict[int, DaliDeviceData] = {}
        self._gear_config: dict[int, DaliGearConfig] = {}
        self.input_devices: dict[tuple[int, int], DaliGeneralSensorData] = {}
        self._configured_instances: set[tuple[int, int]] = set()
        self._store: Store[dict[str, Any]] = DaliMetadataStore(
            hass, STORAGE_VERSION, f"{DOMAIN}.{config_entry.entry_id}_metadata"
        )
        self._event_listeners: set[Callable[[object], None]] = set()
        self._event_task: asyncio.Task | None = None
        self.event_data: dict[tuple[int, int], object] = {}

    async def async_load_metadata_cache(self) -> None:
        """Restore identification metadata persisted from earlier sessions.

        Memory-bank identification data is static per device, so reading it back
        from storage lets the initial refresh skip the slow byte-by-byte bank
        reads whenever a device has been seen before.
        """
        stored = await self._store.async_load()
        if not stored:
            return
        for address, values in stored.get("gear", {}).items():
            self._metadata[int(address)] = DaliDeviceData(**values)
        for address, values in stored.get("device", {}).items():
            self._device_metadata[int(address)] = DaliDeviceData(**values)
        for key, values in stored.get("sensor", {}).items():
            address, instance = (int(part) for part in key.split(":"))
            self.input_devices[(address, instance)] = DaliGeneralSensorData(**values)

    def _persist_metadata(self) -> None:
        """Schedule a debounced save of the identification metadata caches."""
        self._store.async_delay_save(self._metadata_snapshot, METADATA_SAVE_DELAY)

    @callback
    def _metadata_snapshot(self) -> dict[str, Any]:
        """Return the identification caches in a JSON-serializable form."""
        return {
            "gear": {
                str(address): asdict(metadata)
                for address, metadata in self._metadata.items()
            },
            "device": {
                str(address): asdict(metadata)
                for address, metadata in self._device_metadata.items()
            },
            "sensor": {
                f"{address}:{instance}": asdict(data)
                for (address, instance), data in self.input_devices.items()
            },
        }

    def _apply_device_metadata(
        self, address: int, metadata: DaliDeviceData, *, input_device: bool
    ) -> None:
        """Push freshly read identification data onto an existing registry device.

        Gear and control-device entities are created from the fast initial scan
        before identification data has been read, so the registry entry is
        updated in place once the deferred memory-bank read completes.
        """
        device_registry = dr.async_get(self.hass)
        device = device_registry.async_get_device_by_identifier(
            (
                DOMAIN,
                registry_identifier(
                    self.config_entry.entry_id, address, input_device=input_device
                ),
            ),
            self.config_entry.entry_id,
        )
        if device is None or metadata == DaliDeviceData():
            return
        device_registry.async_update_device(
            device.id,
            model_id=str(metadata.gtin) if metadata.gtin is not None else UNDEFINED,
            serial_number=(
                metadata.serial_no if metadata.serial_no is not None else UNDEFINED
            ),
            sw_version=(
                metadata.firmware_version
                if metadata.firmware_version is not None
                else UNDEFINED
            ),
            hw_version=(
                metadata.hardware_version
                if metadata.hardware_version is not None
                else UNDEFINED
            ),
        )

    @property
    def device_instances(self) -> tuple[tuple[int, int, int], ...]:
        """Return discovered device instance address/type tuples."""
        return tuple(
            (getattr(address, "address", address), instance, instance_type)
            for (
                address,
                instance,
            ), instance_type in self.driver.dev_inst_map.mapping.items()
        )

    def async_add_event_listener(
        self, listener: Callable[[object], None]
    ) -> Callable[[], None]:
        """Subscribe to DALI-2 input device events."""
        self._event_listeners.add(listener)

        def remove_listener() -> None:
            self._event_listeners.discard(listener)

        return remove_listener

    def start_event_listener(self) -> None:
        """Start consuming DALI-2 events from the driver."""
        self._event_task = asyncio.create_task(self._async_event_listener())

    async def _async_event_listener(self) -> None:
        queue = self.driver.new_dali_rx_queue()
        while True:
            event = await queue.get()
            if not hasattr(event, "short_address"):
                continue
            address = event.short_address
            if address is not None and event.instance_number is not None:
                key = (address.address, event.instance_number)
                self.event_data[key] = event
            for listener in tuple(self._event_listeners):
                # A faulty listener must not kill the shared event task and
                # silently stop delivery to every other entity.
                try:
                    listener(event)
                except Exception:
                    LOGGER.exception("Unhandled error in DALI event listener")

    async def async_update_gear(
        self, address: int, optimistic_level: int | None = None
    ) -> None:
        """Refresh a single gear and notify entities, without a full bus scan.

        ``optimistic_level`` overrides the queried brightness with the value a
        just-sent level settles to. A DALI gear reaches a commanded level over
        its configured fade time, so an immediate ``QueryActualLevel`` reads a
        mid-fade value; the override shows the target at once and the periodic
        scan reconciles it.
        """
        gear = await self._query_gear(address)
        data = dict(self.data or {})
        if gear is None:
            data.pop(address, None)
        elif optimistic_level is not None:
            data[address] = replace(gear, level=optimistic_level)
        else:
            data[address] = gear
        self.async_set_updated_data(data)

    async def async_update_gear_config(self, address: int) -> None:
        """Re-read a gear's configuration variables after a write.

        The gear arbitrates what it stores — it clamps levels against its
        physical minimum and the opposing limit, and snaps an extended fade
        time to a representable step — so the written value is dropped from
        the cache and read back rather than assumed.
        """
        self._gear_config.pop(address, None)
        await self.async_update_gear(address)

    async def _query_gear(
        self, address: int, *, fast: bool = False, refresh_config: bool = False
    ) -> DaliGearData | None:
        """Return a gear's state and metadata, or None when absent.

        A known gear is queried again after a miss so a single dropped DALI
        response does not flip a light to unavailable. ``fast`` skips the slow
        memory-bank reads (identification data and emergency diagnostics) so
        the initial refresh does not block setup; they are filled in later.
        ``refresh_config`` re-reads the cached configuration variables.
        """
        gear = await self._query_gear_once(
            address, fast=fast, refresh_config=refresh_config
        )
        if gear is None and self.data and address in self.data:
            gear = await self._query_gear_once(
                address, fast=fast, refresh_config=refresh_config
            )
        return gear

    async def _query_gear_once(
        self, address: int, *, fast: bool = False, refresh_config: bool = False
    ) -> DaliGearData | None:
        """Return a gear's state and metadata, or None when absent."""
        gear_address = GearShort(address)
        try:
            present = await self.driver.send(QueryControlGearPresent(gear_address))
            if present is None or not present.value:
                return None
            device_types = tuple(
                device_type
                for device_type in await self.driver.send(
                    QueryDeviceTypes(gear_address)
                )
                if device_type in SUPPORTED_GEAR_DEVICE_TYPES
            )
            if not device_types:
                return None
            level = await self.driver.send(QueryActualLevel(gear_address))
            config = self._gear_config.get(address)
            if config is None or refresh_config:
                config = await self._query_gear_config(gear_address)
                self._gear_config[address] = config
            linear_dimming = False
            if DEVICE_TYPE_LED in device_types:
                curve = await self.driver.send(QueryDimmingCurve(gear_address))
                linear_dimming = (
                    curve is not None
                    and curve.raw_value is not None
                    and curve.raw_value.as_integer == 1
                )
            supports_color_temperature = False
            supports_xy = False
            color_type_tc_active = None
            color_temp_mired = None
            color_temp_min_mired = None
            color_temp_max_mired = None
            xy_color = None
            if DEVICE_TYPE_COLOUR in device_types:
                features = await self.driver.send(QueryColourTypeFeatures(gear_address))
                if features.raw_value is not None and not features.raw_value.error:
                    supports_color_temperature = features.Tc_capable
                    supports_xy = features.xy_capable
                if supports_color_temperature and supports_xy:
                    status = await self.driver.send(QueryColourStatus(gear_address))
                    if status.raw_value is not None and not status.raw_value.error:
                        color_type_tc_active = (
                            status.colour_type_colour_temperature_Tc_active == 1
                        )
                if supports_color_temperature:
                    color_temp_mired = await self.driver.send(
                        QueryDT8ColourValue(
                            gear_address, QueryColourValueDTR.ColourTemperatureTC
                        )
                    )
                    # The gear only accepts values within its configured Tc
                    # limits; fall back to the physical limits when unset.
                    color_temp_min_mired = await self.driver.send(
                        QueryDT8ColourValue(
                            gear_address,
                            QueryColourValueDTR.ColourTemperatureTcCoolest,
                        )
                    )
                    if color_temp_min_mired is None:
                        color_temp_min_mired = await self.driver.send(
                            QueryDT8ColourValue(
                                gear_address,
                                QueryColourValueDTR.ColourTemperatureTcPhysicalCoolest,
                            )
                        )
                    color_temp_max_mired = await self.driver.send(
                        QueryDT8ColourValue(
                            gear_address,
                            QueryColourValueDTR.ColourTemperatureTcWarmest,
                        )
                    )
                    if color_temp_max_mired is None:
                        color_temp_max_mired = await self.driver.send(
                            QueryDT8ColourValue(
                                gear_address,
                                QueryColourValueDTR.ColourTemperatureTcPhysicalWarmest,
                            )
                        )
                if supports_xy:
                    x = await self.driver.send(
                        QueryDT8ColourValue(
                            gear_address, QueryColourValueDTR.XCoordinate
                        )
                    )
                    y = await self.driver.send(
                        QueryDT8ColourValue(
                            gear_address, QueryColourValueDTR.YCoordinate
                        )
                    )
                    if isinstance(x, int) and isinstance(y, int):
                        xy_color = (x / 65535, y / 65535)
            emergency_data = None
            if DEVICE_TYPE_EMERGENCY in device_types:
                emergency_data = await self._query_emergency(gear_address, fast=fast)
        except (OSError, TimeoutError) as err:
            raise UpdateFailed(
                translation_domain=DOMAIN,
                translation_key="update_failed",
            ) from err
        except DALISequenceError:
            return None

        metadata = self._metadata.get(address)
        if metadata is None and not fast:
            metadata = await self._query_metadata(gear_address)
            self._metadata[address] = metadata
            self._apply_device_metadata(address, metadata, input_device=False)
            self._persist_metadata()
        if metadata is None:
            metadata = DaliDeviceData()

        return DaliGearData(
            level=_dali_level_to_brightness(
                _response_value(level), linear_dimming, config.min_level
            ),
            min_level=config.min_level,
            max_level=config.max_level,
            system_failure_level=config.system_failure_level,
            fade_time=config.fade_time,
            fade_rate=config.fade_rate,
            extended_fade_time_base=config.extended_fade_time_base,
            extended_fade_time_multiplier=config.extended_fade_time_multiplier,
            linear_dimming=linear_dimming,
            device_types=device_types,
            supports_color_temperature=supports_color_temperature,
            supports_xy=supports_xy,
            color_type_tc_active=color_type_tc_active,
            color_temp_mired=color_temp_mired,
            color_temp_min_mired=color_temp_min_mired,
            color_temp_max_mired=color_temp_max_mired,
            xy_color=xy_color,
            emergency=emergency_data,
            gtin=metadata.gtin,
            identification_number=metadata.identification_number,
            serial_no=metadata.serial_no,
            batch_no=metadata.batch_no,
            firmware_version=metadata.firmware_version,
            hardware_version=metadata.hardware_version,
        )

    async def _query_gear_config(self, gear_address: GearShort) -> DaliGearConfig:
        """Read the IEC 62386-102 configuration variables of one control gear."""
        min_level = _response_value(await self.driver.send(QueryMinLevel(gear_address)))
        if min_level is None or not 1 <= min_level <= 254:
            min_level = 1
        max_level = _response_value(await self.driver.send(QueryMaxLevel(gear_address)))
        if max_level is not None and not 1 <= max_level <= 254:
            max_level = None
        # Every byte is a valid system failure level, so unlike the dimming
        # limits there is no out-of-range answer to reject.
        system_failure_level = _level_or_mask(
            await self.driver.send(QuerySystemFailureLevel(gear_address))
        )
        # The library's .fade_time/.fade_rate properties read their nibbles out
        # of a framing-error frame too, so decode from the checked value.
        fade = _response_value(
            await self.driver.send(QueryFadeTimeFadeRate(gear_address))
        )
        base, multiplier = _extended_fade_time(
            await self.driver.send(QueryExtendedFadeTime(gear_address))
        )
        return DaliGearConfig(
            min_level=min_level,
            max_level=max_level,
            system_failure_level=system_failure_level,
            fade_time=None if fade is None else (fade >> 4) & 0x0F,
            fade_rate=None if fade is None else fade & 0x0F,
            extended_fade_time_base=base,
            extended_fade_time_multiplier=multiplier,
        )

    async def _query_emergency(
        self, gear_address: GearShort, *, fast: bool = False
    ) -> DaliEmergencyData:
        """Read DT1 (IEC 62386-202) status, measurements and MB208 diagnostics.

        The four status bytes and the measurement values come from a single
        ``QueryEmergencyInformation`` transaction; the slower memory-bank-208
        diagnostics are read separately and a bank a gear does not implement
        simply leaves those fields unset. ``fast`` skips the memory-bank-208
        read entirely so the initial refresh is not held up by it; the periodic
        refresh fills the diagnostics in afterwards.
        """
        info_ = await self.driver.send(QueryEmergencyInformation(gear_address))
        memory: dict[type, Any] = {}
        if not fast:
            try:
                memory = await self.driver.send(
                    emergency.BANK_208.read_all(gear_address)
                )
            except DALISequenceError, MemoryLocationNotImplemented, ResponseError:
                memory = {}

        return DaliEmergencyData(
            mode=info_.emergency_mode,
            features=info_.emergency_features,
            failure_status=info_.emergency_failure_status,
            status=info_.emergency_status,
            battery_charge=info_.battery_charge,
            emergency_level=info_.emergency_level,
            duration_test_result=info_.duration_test_result,
            lamp_emergency_time=info_.lamp_emergency_time,
            lamp_total_operation_time=info_.lamp_total_operation_time,
            rated_duration=info_.rated_duration,
            control_gear_temperature=memory.get(emergency.ControlGearTemperature),
            control_gear_max_reference_temperature=memory.get(
                emergency.ControlGearMaxReferenceTemperature
            ),
            min_control_gear_temperature_total=memory.get(
                emergency.MinControlGearTemperatureTotal
            ),
            max_control_gear_temperature_total=memory.get(
                emergency.MaxControlGearTemperatureTotal
            ),
            average_power_during_charging=memory.get(
                emergency.AveragePowerDuringCharging
            ),
            average_power_during_maintenance=memory.get(
                emergency.AveragePowerDuringMaintenance
            ),
            battery_recharge_time=memory.get(emergency.BatteryRechargeTime),
            function_test_time=memory.get(emergency.FunctionTestTime),
            battery_failure_counter=memory.get(emergency.BatteryFailureCounter),
            lamp_emergency_time_total=memory.get(emergency.LampEmergencyTimeTotal),
            lamp_emergency_time_current_battery=memory.get(
                emergency.LampEmergencyTimeCurrentBattery
            ),
            battery_connected_time_total=memory.get(
                emergency.BatteryConnectedTimeTotal
            ),
            emergency_mode_counter_total=memory.get(
                emergency.EmergencyModeCounterTotal
            ),
            rest_mode_counter=memory.get(emergency.RestModeCounter),
            start_function_test_counter=memory.get(emergency.StartFunctionTestCounter),
            start_duration_test_counter_total=memory.get(
                emergency.StartDurationTestCounterTotal
            ),
            function_test_failed_counter_total=memory.get(
                emergency.FunctionTestFailedCounterTotal
            ),
            duration_test_failed_counter_total=memory.get(
                emergency.DurationTestFailedCounterTotal
            ),
        )

    async def _query_metadata(self, address: GearShort | DeviceShort) -> DaliDeviceData:
        """Read optional identification data from memory bank 0."""
        try:
            values = await self.driver.send(info.BANK_0.read_all(address))
        except DALISequenceError, MemoryLocationNotImplemented, ResponseError:
            return DaliDeviceData()

        gtin = values.get(info.GTIN)
        identification_number = values.get(info.IdentificationNumber)
        serial_no, batch_no = _serial_and_batch_number(identification_number)
        return DaliDeviceData(
            gtin=gtin,
            identification_number=identification_number,
            serial_no=serial_no,
            batch_no=batch_no,
            firmware_version=_firmware_version(values.get(info.FirmwareVersion), gtin),
            hardware_version=values.get(info.HardwareVersion),
        )

    async def _query_general_sensor(
        self, address: DeviceShort, instance: int
    ) -> DaliGeneralSensorData:
        """Return metadata for a Part 306 general sensor instance."""
        instance_address = InstanceNumber(instance)
        metadata = self._device_metadata.get(address.address)
        if metadata is None:
            metadata = await self._query_metadata(address)
            self._device_metadata[address.address] = metadata

        try:
            resolution = await self._query_stable_value(
                lambda: self.driver.send(QueryResolution(address, instance_address)),
                valid_range=(1, MAX_SENSOR_RESOLUTION),
            )
            input_signal_signed = await self._query_stable_value(
                lambda: self._query_measurement_variable(
                    address, instance_address, MeasurementVariable.INPUT_SIGNAL_SIGNED
                )
            )
            unit_of_measurement = await self._query_stable_value(
                lambda: self._query_measurement_variable(
                    address, instance_address, MeasurementVariable.UNIT_OF_MEASUREMENT
                )
            )
            quantity_name = await self._query_stable_value(
                lambda: self._query_measurement_variable(
                    address, instance_address, MeasurementVariable.QUANTITY_NAME
                )
            )
            magnitude = await self._query_stable_value(
                lambda: self._query_measurement_variable(
                    address, instance_address, MeasurementVariable.MAGNITUDE
                )
            )
        except (OSError, TimeoutError) as err:
            raise UpdateFailed(
                translation_domain=DOMAIN,
                translation_key="update_failed",
            ) from err

        return DaliGeneralSensorData(
            quantity_name=quantity_name,
            unit_of_measurement=unit_of_measurement,
            resolution=resolution,
            magnitude=magnitude,
            input_signal_signed=bool(input_signal_signed)
            if input_signal_signed is not None
            else None,
            gtin=metadata.gtin,
            identification_number=metadata.identification_number,
            serial_no=metadata.serial_no,
            batch_no=metadata.batch_no,
            firmware_version=metadata.firmware_version,
            hardware_version=metadata.hardware_version,
        )

    async def _query_measurement_variable(
        self,
        address: DeviceShort,
        instance: InstanceNumber,
        variable: MeasurementVariable,
    ) -> object:
        """Query a Part 306 measurement variable."""
        await self.driver.send(DTR0(variable))
        return await self.driver.send(QueryMeasurementVariable(address, instance))

    async def _query_stable_value(
        self,
        query: Callable[[], Awaitable[object]],
        *,
        valid_range: tuple[int, int] | None = None,
    ) -> int | None:
        """Return a DALI value confirmed by two consecutive, in-range reads.

        A single corrupted DALI frame can still parse as a valid number; cached
        once as sensor metadata it silently skews every later measurement (seen
        in practice as a temperature reading stuck roughly 290 C too high until
        the next restart). Require two consecutive reads to agree so a one-off
        bus error is rejected rather than latched. When ``valid_range`` is given
        the value must also be present and within it, so an out-of-range reading
        can never be confirmed.
        """
        previous: int | None = None
        have_previous = False
        for _ in range(METADATA_QUERY_ATTEMPTS):
            value = _response_value(await query())
            if valid_range is not None and (
                value is None or not valid_range[0] <= value <= valid_range[1]
            ):
                have_previous = False
                continue
            if have_previous and value == previous:
                return value
            previous = value
            have_previous = True
        raise UpdateFailed(
            translation_domain=DOMAIN,
            translation_key="update_failed",
        )

    async def _configure_general_sensor_events(
        self, address: DeviceShort, instance: InstanceNumber
    ) -> None:
        """Make a Part 306 instance report measured values self-addressed.

        A general-sensor instance may emit events under the "Instance" scheme,
        whose frames carry no short address, so a measured value cannot be tied
        to a device. Switching to the Device/Instance scheme makes every event
        carry the short address the entities are keyed by, and the instance and
        measured-value filter are (re-)enabled so reports are generated.
        """
        try:
            await self.driver.send(EnableInstance(address, instance))
            await self.driver.send(DTR0(EventScheme.device_instance))
            await self.driver.send(SetEventScheme(address, instance))
            await self.driver.send(DTR2(0))
            await self.driver.send(DTR1(0))
            await self.driver.send(DTR0(InstanceEventFilter.measured_value))
            await self.driver.send(SetEventFilter(address, instance))
        except (OSError, TimeoutError) as err:
            raise UpdateFailed(
                translation_domain=DOMAIN,
                translation_key="update_failed",
            ) from err

    async def async_discover_control_devices(self, *, fast: bool = False) -> None:
        """Enumerate control devices and configure their event reporting.

        Runs the quiescent autodiscover scan, then reads identification data
        and enables measured-value reporting for any new Part 306 instance.
        autodiscover only adds to the instance map, so this folds in a device
        missed at connect or added since the last run. It silences input
        devices for the duration of the scan, so it runs at startup, on demand,
        and after commissioning rather than on the periodic bus poll. ``fast``
        defers the control-device identification reads so the initial refresh is
        not held up; sensor metadata is still read as it defines the entity.
        """
        try:
            await self.driver.send(self.driver.dev_inst_map.autodiscover())
        except (OSError, TimeoutError) as err:
            raise UpdateFailed(
                translation_domain=DOMAIN,
                translation_key="update_failed",
            ) from err
        except DALISequenceError:
            LOGGER.debug("Control-device autodiscover failed; retrying later")
            return
        for address, _instance in self.driver.dev_inst_map.mapping:
            address_int = getattr(address, "address", address)
            if address_int not in self._device_metadata and not fast:
                metadata = await self._query_metadata(
                    address
                    if isinstance(address, DeviceShort)
                    else DeviceShort(address)
                )
                self._device_metadata[address_int] = metadata
                self._apply_device_metadata(address_int, metadata, input_device=True)
                self._persist_metadata()
        for address, instance, instance_type in self.device_instances:
            if instance_type != 6:
                continue
            key = (address, instance)
            device_short = DeviceShort(address)
            instance_number = InstanceNumber(instance)
            if key not in self.input_devices:
                self.input_devices[key] = await self._query_general_sensor(
                    device_short, instance
                )
                self._persist_metadata()
            if key not in self._configured_instances:
                await self._configure_general_sensor_events(
                    device_short, instance_number
                )
                self._configured_instances.add(key)
        self.async_update_listeners()

    @override
    async def _async_update_data(self) -> dict[int, DaliGearData]:
        """Refresh known gear, scanning the whole bus periodically.

        Every cycle re-queries the gear already known so lights track external
        changes, but the full 64-address scan and the unaddressed-device checks
        only run every ``FULL_SCAN_INTERVAL`` to keep bus traffic low. Control
        devices are enumerated once at startup and otherwise on demand, so the
        periodic poll never puts the bus quiescent and silences input devices.
        The configuration variables are re-read on the full scan too, as they
        only change when written, here or by another controller on the bus.
        """
        fast = self._initial_refresh
        now = self.hass.loop.time()
        full_scan = (
            self._last_full_scan is None
            or now - self._last_full_scan >= FULL_SCAN_INTERVAL.total_seconds()
        )
        addresses = range(64) if full_scan else tuple(self.data or ())
        data: dict[int, DaliGearData] = {}
        for address in addresses:
            gear = await self._query_gear(address, fast=fast, refresh_config=full_scan)
            if gear is not None:
                data[address] = gear
        if not full_scan:
            return data
        self._last_full_scan = now
        # A re-addressed gear must not inherit the previous occupant's config.
        self._gear_config = {
            address: config
            for address, config in self._gear_config.items()
            if address in data
        }
        if not self._discovered:
            await self.async_discover_control_devices(fast=fast)
            self._discovered = True
        self._update_unaddressed_gear_issue(await self._has_unaddressed_gear())
        self._update_unaddressed_control_device_issue(
            await self._has_unaddressed_control_devices()
        )
        self._initial_refresh = False
        return data

    async def async_enrich_deferred_data(self) -> None:
        """Read the identification and diagnostics data deferred past setup.

        The initial refresh skips the slow memory-bank reads so setup completes
        quickly. This runs once afterwards to read identification metadata for
        every discovered gear and control device, update their registry entries,
        and trigger a normal refresh that fills in the emergency diagnostics.
        """
        try:
            for address in list(self.data or {}):
                if address not in self._metadata:
                    metadata = await self._query_metadata(GearShort(address))
                    self._metadata[address] = metadata
                    self._apply_device_metadata(address, metadata, input_device=False)
            device_addresses = {
                address for address, _instance, _type in self.device_instances
            }
            for address in device_addresses:
                if address not in self._device_metadata:
                    metadata = await self._query_metadata(DeviceShort(address))
                    self._device_metadata[address] = metadata
                    self._apply_device_metadata(address, metadata, input_device=True)
        except OSError, TimeoutError:
            # A transport error here only delays enrichment; the periodic
            # refresh reads any still-missing metadata and diagnostics.
            LOGGER.debug("Deferred DALI metadata read failed; retrying on next poll")
        self._persist_metadata()
        await self.async_refresh()

    async def _has_unaddressed_gear(self) -> bool:
        """Return whether any control gear on the bus lacks a short address."""
        try:
            response = await self.driver.send(QueryMissingShortAddress(GearBroadcast()))
        except (OSError, TimeoutError) as err:
            raise UpdateFailed(
                translation_domain=DOMAIN,
                translation_key="update_failed",
            ) from err
        return response is not None and bool(response.value)

    async def _has_unaddressed_control_devices(self) -> bool:
        """Return whether any control device on the bus lacks a short address."""
        try:
            response = await self.driver.send(
                QueryMissingDeviceShortAddress(DeviceBroadcast())
            )
        except (OSError, TimeoutError) as err:
            raise UpdateFailed(
                translation_domain=DOMAIN,
                translation_key="update_failed",
            ) from err
        return response is not None and bool(response.value)

    def _update_unaddressed_gear_issue(self, unaddressed: bool) -> None:
        """Create or remove the repair issue for unaddressed control gear."""
        issue_id = unaddressed_gear_issue_id(self.config_entry.entry_id)
        if not unaddressed:
            ir.async_delete_issue(self.hass, DOMAIN, issue_id)
            return
        ir.async_create_issue(
            self.hass,
            DOMAIN,
            issue_id,
            data={"entry_id": self.config_entry.entry_id},
            is_fixable=True,
            severity=ir.IssueSeverity.WARNING,
            translation_key=ISSUE_UNADDRESSED_GEAR,
            translation_placeholders={"title": self.config_entry.title},
        )

    def _update_unaddressed_control_device_issue(self, unaddressed: bool) -> None:
        """Create or remove the repair issue for unaddressed control devices."""
        issue_id = unaddressed_control_device_issue_id(self.config_entry.entry_id)
        if not unaddressed:
            ir.async_delete_issue(self.hass, DOMAIN, issue_id)
            return
        ir.async_create_issue(
            self.hass,
            DOMAIN,
            issue_id,
            data={"entry_id": self.config_entry.entry_id},
            is_fixable=True,
            severity=ir.IssueSeverity.WARNING,
            translation_key=ISSUE_UNADDRESSED_CONTROLDEVICE,
            translation_placeholders={"title": self.config_entry.title},
        )

    async def async_assign_gear_short_addresses(self) -> bool:
        """Address unaddressed control gear and return whether any remain unaddressed."""
        await self.driver.send(
            Commissioning(readdress=False), progress=_log_commissioning_progress
        )
        unaddressed = await self._has_unaddressed_gear()
        # Force a full bus scan so newly addressed gear is discovered at once.
        self._last_full_scan = None
        await self.async_refresh()
        return unaddressed

    async def async_assign_control_device_short_addresses(self) -> bool:
        """Address unaddressed control devices; return whether any remain unaddressed."""
        await self.driver.send(
            CommissionDevices(readdress=False), progress=_log_commissioning_progress
        )
        # Newly addressed devices only surface as entities once re-enumerated into
        # the instance map; discovery is additive, so it folds them in.
        await self.async_discover_control_devices()
        unaddressed = await self._has_unaddressed_control_devices()
        # Force a full bus scan so newly addressed devices are discovered at once.
        self._last_full_scan = None
        await self.async_refresh()
        return unaddressed

    def close(self) -> None:
        """Close the serial transport."""
        if self._event_task:
            self._event_task.cancel()
        if transport := getattr(self.driver, "_transport", None):
            transport.close()

    def device_data(
        self, address: int, *, input_device: bool = False
    ) -> DaliDeviceData:
        """Return the memory bank 0 data held for a gear or control device.

        A gear and a control device can share a numeric address, so each kind
        prefers its own cache and falls back to the other's for bus units that
        implement both.
        """
        if input_device:
            data = self._device_metadata.get(address) or self.data.get(address)
        else:
            data = self.data.get(address) or self._device_metadata.get(address)
        return data if data is not None else DaliDeviceData()

    def device_info(
        self, entry_id: str, title: str, address: int, *, input_device: bool = False
    ) -> DeviceInfo:
        """Return shared device information for a DALI gear or input device.

        DALI control gear (lights) and control devices (sensors, buttons) have
        independent short-address spaces, so a gear and a device can share a
        numeric address while being distinct on the bus. The registry identifier
        therefore encodes the kind to keep them separate devices.
        """
        data = self.device_data(address, input_device=input_device)
        kind = "sensor" if input_device else "gear"
        if input_device:
            model = self._control_device_model(address)
        else:
            model = _gear_model(
                data.device_types if isinstance(data, DaliGearData) else ()
            )
        return DeviceInfo(
            identifiers={
                (
                    DOMAIN,
                    registry_identifier(entry_id, address, input_device=input_device),
                )
            },
            name=f"{self._interface_label(title)}/{address} ({kind})",
            model=model,
            model_id=str(data.gtin) if data.gtin is not None else None,
            serial_number=data.serial_no,
            sw_version=data.firmware_version,
            hw_version=data.hardware_version,
        )

    def _control_device_model(self, address: int) -> str:
        """Return a model string naming a control device's instance-type parts.

        A control device can host several instances of different types, so the
        model lists each discovered instance type with the IEC 62386-3xx part
        that specifies it.
        """
        instance_types = sorted(
            {
                instance_type
                for addr, _instance, instance_type in self.device_instances
                if addr == address
            }
        )
        labels = [
            _instance_type_label(instance_type) for instance_type in instance_types
        ]
        if not labels:
            return "DALI control device"
        return "DALI control device – " + ", ".join(labels)

    def hub_device_info(self, entry_id: str, title: str) -> DeviceInfo:
        """Return device information for the DALI interface itself."""
        return DeviceInfo(
            identifiers={(DOMAIN, entry_id)},
            name=self._interface_label(title),
            manufacturer="Lunatone",
            model="USB-DALI2 interface",
        )

    def _interface_label(self, title: str) -> str:
        """Return a short interface label from the entry's USB identity.

        The config-entry title is the full human-readable serial-port string,
        which is too long for a device name. The USB unique ID is a structured
        ``vid:pid_serial_manufacturer_description`` field, so a compact
        ``model_serial`` label is derived from it, falling back to the title
        for non-USB interfaces that have no unique ID.
        """
        unique_id = self.config_entry.unique_id
        if unique_id:
            parts = unique_id.split("_", 3)
            if len(parts) == 4:
                _vid_pid, serial, _manufacturer, description = parts
                if serial:
                    model = description.replace(" ", "_")
                    return f"{model}_{serial}" if model else serial
        return title


def _gear_model(device_types: tuple[int, ...]) -> str:
    """Return a model string naming a control gear's device-type parts."""
    if not device_types:
        return "DALI control gear"
    labels = [_gear_type_label(device_type) for device_type in device_types]
    return "DALI control gear – " + ", ".join(labels)


def _gear_type_label(device_type: int) -> str:
    """Return a label for one control-gear device type and its IEC part."""
    name = GEAR_DEVICE_TYPE_NAMES.get(device_type, f"Device type {device_type}")
    return f"{name} (DT{device_type}, IEC 62386-{201 + device_type})"


def _instance_type_label(instance_type: int) -> str:
    """Return a label for one control-device instance type and its IEC part."""
    name = DEVICE_INSTANCE_TYPE_NAMES.get(
        instance_type, f"Instance type {instance_type}"
    )
    return f"{name} (IEC 62386-{300 + instance_type})"


def _dali_level_to_brightness(
    level: object, linear_dimming: bool, min_level: int
) -> int | None:
    """Convert a DALI arc-power level to Home Assistant brightness."""
    if not isinstance(level, int) or level >= 255:
        return None
    if level <= 0:
        return 0
    if level <= min_level:
        return 1
    if linear_dimming:
        return round(1 + (level - min_level) * 254 / (254 - min_level))
    return round(255 * 10 ** (((level - 254) * 3) / 253))


def _brightness_to_dali_level(
    brightness: int, linear_dimming: bool, min_level: int
) -> int:
    """Convert Home Assistant brightness (1-255) to a DALI arc-power level.

    The DALI level axis is coarser than the 1-255 brightness axis, so rounding
    each direction independently makes a set level read back as a different
    brightness and the UI slider jumps. The level is therefore snapped to the
    one that ``_dali_level_to_brightness`` maps back closest to the requested
    brightness, keeping set-then-read stable wherever a matching level exists.
    """
    if linear_dimming:
        analytic = min_level + (brightness - 1) * (254 - min_level) / 254
    elif brightness < 255:
        analytic = 254 + 253 * math.log10(brightness / 255) / 3
    else:
        analytic = 254
    base = max(min_level, min(round(analytic), 254))
    candidates = range(max(min_level, base - 2), min(254, base + 2) + 1)
    return min(
        candidates,
        key=lambda level: (
            abs(
                (_dali_level_to_brightness(level, linear_dimming, min_level) or 0)
                - brightness
            ),
            abs(level - base),
        ),
    )


def _response_value(response: object) -> int | None:
    """Return a numeric response value."""
    value = getattr(response, "value", None)
    return value if isinstance(value, int) else None


def _serial_and_batch_number(
    identification_number: object,
) -> tuple[str | None, str | None]:
    """Split a bus unit's identification number into serial and batch number.

    The eight bytes of the memory bank 0 identification number carry the serial
    number in the low three and the batch number in the high five, each written
    out least significant byte first.
    """
    if not isinstance(identification_number, int):
        return None, None
    raw = identification_number.to_bytes(8, "little")
    return (
        "".join(f"{byte:02X}" for byte in raw[0:3]),
        "".join(f"{byte:02X}" for byte in raw[3:8]),
    )


def _firmware_version(version: object, gtin: object) -> str | None:
    """Return the firmware version, in Tridonic's format on Tridonic units.

    The library renders the two version bytes as "<first>.<second>", but on
    Tridonic gear the first byte packs the major and minor version the way IEC
    62386-102 packs a single-byte version, and the second byte is the build
    number, giving "<major>.<minor>-<build>".
    """
    if not isinstance(version, str):
        return None
    if not isinstance(gtin, int) or not str(gtin).startswith(TRIDONIC_GTIN_PREFIX):
        return version
    first, _, second = version.partition(".")
    if not first.isdigit() or not second.isdigit():
        return version
    packed = int(first)
    return f"{packed >> 2}.{packed & 0x03}-{second}"


def _level_or_mask(response: object) -> int | None:
    """Return a level response, keeping the gear's MASK answer as a level.

    ``NumericResponseMask`` reports 255 as the string ``"MASK"``, which is a
    real stored value meaning "keep the current level", not an unreadable one,
    so it must not be discarded the way ``_response_value`` discards it.
    """
    value = getattr(response, "value", None)
    if value == "MASK":
        return MASK_LEVEL
    return value if isinstance(value, int) else None


def _extended_fade_time(response: object) -> tuple[int | None, int | None]:
    """Return the extended fade time base and multiplier of a response.

    ``QueryExtendedFadeTime`` answers with a bare ``Response``, whose ``value``
    raises on a framing error rather than reporting it, so the backward frame
    is inspected directly.
    """
    raw = getattr(response, "raw_value", None)
    if raw is None or raw.error:
        return None, None
    byte = raw.as_integer
    return byte & 0x0F, (byte >> 4) & 0x07


def _log_commissioning_progress(update: str | progress) -> None:
    """Log progress messages from the commissioning sequence."""
    message = update if isinstance(update, str) else update.message
    if message:
        LOGGER.debug("Commissioning: %s", message)
