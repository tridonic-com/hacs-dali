"""DALI-2 illuminance sensors."""

from collections.abc import Callable
from dataclasses import dataclass
from typing import override

from dali.device.general_sensor import (
    GeneralSensorEvent,
    QuantityName,
    UnitOfMeasurement,
)
from dali.device.light import LightEvent

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.const import (
    PERCENTAGE,
    EntityCategory,
    UnitOfElectricCurrent,
    UnitOfElectricPotential,
    UnitOfEnergy,
    UnitOfFrequency,
    UnitOfPower,
    UnitOfPressure,
    UnitOfRatio,
    UnitOfSoundPressure,
    UnitOfTemperature,
    UnitOfTime,
)
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from . import DaliConfigEntry
from .const import DEVICE_TYPE_EMERGENCY
from .coordinator import (
    DaliCoordinator,
    DaliDeviceData,
    DaliDiagnosticsData,
    DaliEmergencyData,
    DaliGearData,
    DaliGeneralSensorData,
    DaliLuminaireData,
    DaliMaintenanceData,
)

PARALLEL_UPDATES = 0

# Luminous flux, which Home Assistant has no unit constant for.
UNIT_LUMEN = "lm"

EMERGENCY_MODE_OPTIONS = [
    "normal",
    "inhibit",
    "emergency",
    "extended_emergency",
    "rest",
    "function_test",
    "duration_test",
]


def _emergency_mode(data: DaliEmergencyData) -> str | None:
    """Return the current operating mode as a single enum option.

    Only one of the mode bits should be set at a time; where several are, the
    most operationally significant is reported. Inhibit is held in the status
    byte rather than the mode byte, so it is derived when normal mode is active.
    """
    mode = data.mode
    if mode is None:
        return None
    if mode.emergency_mode:
        return "emergency"
    if mode.extended_emergency_mode:
        return "extended_emergency"
    if mode.rest_mode:
        return "rest"
    if mode.function_test:
        return "function_test"
    if mode.duration_test:
        return "duration_test"
    if data.status is not None and data.status.inhibit_mode:
        return "inhibit"
    return "normal"


def _battery_charge(data: DaliEmergencyData) -> int | None:
    """Scale the 0-254 battery charge level to a percentage."""
    if data.battery_charge is None:
        return None
    return round(data.battery_charge * 100 / 254)


@dataclass(frozen=True, kw_only=True)
class DaliPart306SensorDescription(SensorEntityDescription):
    """Description of a Part 306 general sensor."""

    quantity_name: QuantityName


DALI_PART306_SENSOR_TYPES: dict[int, DaliPart306SensorDescription] = {
    QuantityName.TEMPERATURE: DaliPart306SensorDescription(
        key="temperature",
        translation_key="temperature",
        quantity_name=QuantityName.TEMPERATURE,
        device_class=SensorDeviceClass.TEMPERATURE,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        state_class=SensorStateClass.MEASUREMENT,
    ),
    QuantityName.RELATIVE_HUMIDITY: DaliPart306SensorDescription(
        key="relative_humidity",
        translation_key="relative_humidity",
        quantity_name=QuantityName.RELATIVE_HUMIDITY,
        device_class=SensorDeviceClass.HUMIDITY,
        native_unit_of_measurement=UnitOfRatio.PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
    ),
    QuantityName.PRESSURE: DaliPart306SensorDescription(
        key="pressure",
        translation_key="pressure",
        quantity_name=QuantityName.PRESSURE,
        device_class=SensorDeviceClass.ATMOSPHERIC_PRESSURE,
        native_unit_of_measurement=UnitOfPressure.PA,
        state_class=SensorStateClass.MEASUREMENT,
    ),
    QuantityName.CO2: DaliPart306SensorDescription(
        key="co2",
        translation_key="co2",
        quantity_name=QuantityName.CO2,
        device_class=SensorDeviceClass.CO2,
        native_unit_of_measurement=UnitOfRatio.PARTS_PER_MILLION,
        state_class=SensorStateClass.MEASUREMENT,
    ),
    QuantityName.VOC: DaliPart306SensorDescription(
        key="voc",
        translation_key="voc",
        quantity_name=QuantityName.VOC,
        native_unit_of_measurement=UnitOfRatio.PARTS_PER_MILLION,
        state_class=SensorStateClass.MEASUREMENT,
    ),
    QuantityName.AIR_QUALITY_INDEX: DaliPart306SensorDescription(
        key="air_quality_index",
        translation_key="air_quality_index",
        quantity_name=QuantityName.AIR_QUALITY_INDEX,
        device_class=SensorDeviceClass.AQI,
        state_class=SensorStateClass.MEASUREMENT,
    ),
    QuantityName.SOUND_PRESSURE_LEVEL: DaliPart306SensorDescription(
        key="sound_pressure",
        translation_key="sound_pressure",
        quantity_name=QuantityName.SOUND_PRESSURE_LEVEL,
        device_class=SensorDeviceClass.SOUND_PRESSURE,
        native_unit_of_measurement=UnitOfSoundPressure.WEIGHTED_DECIBEL_A,
        state_class=SensorStateClass.MEASUREMENT,
    ),
}


@dataclass(frozen=True, kw_only=True)
class DaliIdentificationSensorDescription(SensorEntityDescription):
    """Description of a memory bank 0 identification value."""

    value_fn: Callable[[DaliDeviceData], str | int | None]


IDENTIFICATION_SENSOR_TYPES: tuple[DaliIdentificationSensorDescription, ...] = (
    DaliIdentificationSensorDescription(
        key="identification_number",
        translation_key="identification_number",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda data: data.identification_number,
    ),
)


@dataclass(frozen=True, kw_only=True)
class DaliEmergencySensorDescription(SensorEntityDescription):
    """Description of a DT1 emergency sensor."""

    value_fn: Callable[[DaliEmergencyData], int | float | str | None]


EMERGENCY_SENSOR_TYPES: tuple[DaliEmergencySensorDescription, ...] = (
    DaliEmergencySensorDescription(
        key="emergency_mode",
        translation_key="emergency_mode",
        device_class=SensorDeviceClass.ENUM,
        options=EMERGENCY_MODE_OPTIONS,
        value_fn=_emergency_mode,
    ),
    DaliEmergencySensorDescription(
        key="battery_charge",
        device_class=SensorDeviceClass.BATTERY,
        native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=_battery_charge,
    ),
    DaliEmergencySensorDescription(
        key="emergency_level",
        translation_key="emergency_level",
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda data: data.emergency_level,
    ),
    DaliEmergencySensorDescription(
        key="duration_test_result",
        translation_key="duration_test_result",
        device_class=SensorDeviceClass.DURATION,
        native_unit_of_measurement=UnitOfTime.MINUTES,
        # The gear reports the result in 2-minute units.
        value_fn=lambda data: (
            data.duration_test_result * 2
            if data.duration_test_result is not None
            else None
        ),
    ),
    DaliEmergencySensorDescription(
        key="rated_duration",
        translation_key="rated_duration",
        device_class=SensorDeviceClass.DURATION,
        native_unit_of_measurement=UnitOfTime.MINUTES,
        # The gear reports the rated duration in 2-minute units.
        value_fn=lambda data: (
            data.rated_duration * 2 if data.rated_duration is not None else None
        ),
    ),
    DaliEmergencySensorDescription(
        key="lamp_emergency_time",
        translation_key="lamp_emergency_time",
        device_class=SensorDeviceClass.DURATION,
        native_unit_of_measurement=UnitOfTime.HOURS,
        state_class=SensorStateClass.TOTAL_INCREASING,
        value_fn=lambda data: data.lamp_emergency_time,
    ),
    DaliEmergencySensorDescription(
        key="lamp_total_operation_time",
        translation_key="lamp_total_operation_time",
        device_class=SensorDeviceClass.DURATION,
        native_unit_of_measurement=UnitOfTime.HOURS,
        state_class=SensorStateClass.TOTAL_INCREASING,
        # The gear reports total operation time in 4-hour units.
        value_fn=lambda data: (
            data.lamp_total_operation_time * 4
            if data.lamp_total_operation_time is not None
            else None
        ),
    ),
    DaliEmergencySensorDescription(
        key="control_gear_temperature",
        translation_key="control_gear_temperature",
        device_class=SensorDeviceClass.TEMPERATURE,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda data: data.control_gear_temperature,
    ),
    DaliEmergencySensorDescription(
        key="control_gear_max_reference_temperature",
        translation_key="control_gear_max_reference_temperature",
        device_class=SensorDeviceClass.TEMPERATURE,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        value_fn=lambda data: data.control_gear_max_reference_temperature,
    ),
    DaliEmergencySensorDescription(
        key="min_control_gear_temperature_total",
        translation_key="min_control_gear_temperature_total",
        device_class=SensorDeviceClass.TEMPERATURE,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        value_fn=lambda data: data.min_control_gear_temperature_total,
    ),
    DaliEmergencySensorDescription(
        key="max_control_gear_temperature_total",
        translation_key="max_control_gear_temperature_total",
        device_class=SensorDeviceClass.TEMPERATURE,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        value_fn=lambda data: data.max_control_gear_temperature_total,
    ),
    DaliEmergencySensorDescription(
        key="average_power_during_charging",
        translation_key="average_power_during_charging",
        device_class=SensorDeviceClass.POWER,
        native_unit_of_measurement=UnitOfPower.WATT,
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        value_fn=lambda data: data.average_power_during_charging,
    ),
    DaliEmergencySensorDescription(
        key="average_power_during_maintenance",
        translation_key="average_power_during_maintenance",
        device_class=SensorDeviceClass.POWER,
        native_unit_of_measurement=UnitOfPower.WATT,
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        value_fn=lambda data: data.average_power_during_maintenance,
    ),
    DaliEmergencySensorDescription(
        key="battery_recharge_time",
        translation_key="battery_recharge_time",
        device_class=SensorDeviceClass.DURATION,
        native_unit_of_measurement=UnitOfTime.MINUTES,
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        value_fn=lambda data: data.battery_recharge_time,
    ),
    DaliEmergencySensorDescription(
        key="function_test_time",
        translation_key="function_test_time",
        device_class=SensorDeviceClass.DURATION,
        native_unit_of_measurement=UnitOfTime.SECONDS,
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        value_fn=lambda data: data.function_test_time,
    ),
    DaliEmergencySensorDescription(
        key="battery_failure_counter",
        translation_key="battery_failure_counter",
        state_class=SensorStateClass.TOTAL_INCREASING,
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        value_fn=lambda data: data.battery_failure_counter,
    ),
    DaliEmergencySensorDescription(
        key="lamp_emergency_time_total",
        translation_key="lamp_emergency_time_total",
        device_class=SensorDeviceClass.DURATION,
        native_unit_of_measurement=UnitOfTime.MINUTES,
        state_class=SensorStateClass.TOTAL_INCREASING,
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        value_fn=lambda data: data.lamp_emergency_time_total,
    ),
    DaliEmergencySensorDescription(
        key="lamp_emergency_time_current_battery",
        translation_key="lamp_emergency_time_current_battery",
        device_class=SensorDeviceClass.DURATION,
        native_unit_of_measurement=UnitOfTime.MINUTES,
        state_class=SensorStateClass.TOTAL_INCREASING,
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        value_fn=lambda data: data.lamp_emergency_time_current_battery,
    ),
    DaliEmergencySensorDescription(
        key="battery_connected_time_total",
        translation_key="battery_connected_time_total",
        device_class=SensorDeviceClass.DURATION,
        native_unit_of_measurement=UnitOfTime.DAYS,
        state_class=SensorStateClass.TOTAL_INCREASING,
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        value_fn=lambda data: data.battery_connected_time_total,
    ),
    DaliEmergencySensorDescription(
        key="emergency_mode_counter_total",
        translation_key="emergency_mode_counter_total",
        state_class=SensorStateClass.TOTAL_INCREASING,
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        value_fn=lambda data: data.emergency_mode_counter_total,
    ),
    DaliEmergencySensorDescription(
        key="rest_mode_counter",
        translation_key="rest_mode_counter",
        state_class=SensorStateClass.TOTAL_INCREASING,
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        value_fn=lambda data: data.rest_mode_counter,
    ),
    DaliEmergencySensorDescription(
        key="start_function_test_counter",
        translation_key="start_function_test_counter",
        state_class=SensorStateClass.TOTAL_INCREASING,
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        value_fn=lambda data: data.start_function_test_counter,
    ),
    DaliEmergencySensorDescription(
        key="start_duration_test_counter_total",
        translation_key="start_duration_test_counter_total",
        state_class=SensorStateClass.TOTAL_INCREASING,
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        value_fn=lambda data: data.start_duration_test_counter_total,
    ),
    DaliEmergencySensorDescription(
        key="function_test_failed_counter_total",
        translation_key="function_test_failed_counter_total",
        state_class=SensorStateClass.TOTAL_INCREASING,
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        value_fn=lambda data: data.function_test_failed_counter_total,
    ),
    DaliEmergencySensorDescription(
        key="duration_test_failed_counter_total",
        translation_key="duration_test_failed_counter_total",
        state_class=SensorStateClass.TOTAL_INCREASING,
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        value_fn=lambda data: data.duration_test_failed_counter_total,
    ),
)

# The decoded light distribution types of IEC 62386-102 section 9.10.7, keyed
# by the display string python-dali turns the raw value into.
LIGHT_DISTRIBUTION_TYPES = {
    "not specified": "not_specified",
    "Type I": "type_i",
    "Type II": "type_ii",
    "Type III": "type_iii",
    "Type IV": "type_iv",
    "Type V": "type_v",
    "reserved": "reserved",
}


def _light_distribution_type(data: DaliLuminaireData) -> str | None:
    """Return the light distribution type as a translatable option."""
    if data.light_distribution_type is None:
        return None
    return LIGHT_DISTRIBUTION_TYPES.get(data.light_distribution_type)


@dataclass(frozen=True, kw_only=True)
class DaliLuminaireSensorDescription(SensorEntityDescription):
    """Description of a memory bank 1 luminaire value."""

    value_fn: Callable[[DaliLuminaireData], int | str | None]


LUMINAIRE_SENSOR_TYPES: tuple[DaliLuminaireSensorDescription, ...] = (
    DaliLuminaireSensorDescription(
        key="manufacturer_gtin",
        translation_key="manufacturer_gtin",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda data: data.manufacturer_gtin,
    ),
    DaliLuminaireSensorDescription(
        key="luminaire_id",
        translation_key="luminaire_id",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda data: data.luminaire_id,
    ),
    DaliLuminaireSensorDescription(
        key="luminaire_identification",
        translation_key="luminaire_identification",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda data: data.luminaire_identification or None,
    ),
    DaliLuminaireSensorDescription(
        key="luminaire_color",
        translation_key="luminaire_color",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda data: data.luminaire_color or None,
    ),
    DaliLuminaireSensorDescription(
        key="year_of_manufacture",
        translation_key="year_of_manufacture",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda data: data.year_of_manufacture,
    ),
    DaliLuminaireSensorDescription(
        key="week_of_manufacture",
        translation_key="week_of_manufacture",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda data: data.week_of_manufacture,
    ),
    DaliLuminaireSensorDescription(
        key="input_power_nominal",
        translation_key="input_power_nominal",
        device_class=SensorDeviceClass.POWER,
        native_unit_of_measurement=UnitOfPower.WATT,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda data: data.input_power_nominal,
    ),
    DaliLuminaireSensorDescription(
        key="input_power_minimum_dim",
        translation_key="input_power_minimum_dim",
        device_class=SensorDeviceClass.POWER,
        native_unit_of_measurement=UnitOfPower.WATT,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda data: data.input_power_minimum_dim,
    ),
    DaliLuminaireSensorDescription(
        key="mains_voltage_minimum",
        translation_key="mains_voltage_minimum",
        device_class=SensorDeviceClass.VOLTAGE,
        native_unit_of_measurement=UnitOfElectricPotential.VOLT,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda data: data.mains_voltage_minimum,
    ),
    DaliLuminaireSensorDescription(
        key="mains_voltage_maximum",
        translation_key="mains_voltage_maximum",
        device_class=SensorDeviceClass.VOLTAGE,
        native_unit_of_measurement=UnitOfElectricPotential.VOLT,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda data: data.mains_voltage_maximum,
    ),
    DaliLuminaireSensorDescription(
        key="light_output_nominal",
        translation_key="light_output_nominal",
        native_unit_of_measurement=UNIT_LUMEN,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda data: data.light_output_nominal,
    ),
    DaliLuminaireSensorDescription(
        key="cri",
        translation_key="cri",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda data: data.cri,
    ),
    DaliLuminaireSensorDescription(
        key="cct",
        translation_key="cct",
        # Kelvin without a device class: this is the nominal correlated colour
        # temperature of the light source, not a temperature reading, so it
        # must not be converted into the user's temperature unit.
        native_unit_of_measurement=UnitOfTemperature.KELVIN,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda data: data.cct,
    ),
    DaliLuminaireSensorDescription(
        key="light_distribution_type",
        translation_key="light_distribution_type",
        device_class=SensorDeviceClass.ENUM,
        options=list(LIGHT_DISTRIBUTION_TYPES.values()),
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=_light_distribution_type,
    ),
)


@dataclass(frozen=True, kw_only=True)
class DaliMaintenanceSensorDescription(SensorEntityDescription):
    """Description of a memory bank 207 rated-life value."""

    value_fn: Callable[[DaliMaintenanceData], int | None]


MAINTENANCE_SENSOR_TYPES: tuple[DaliMaintenanceSensorDescription, ...] = (
    DaliMaintenanceSensorDescription(
        key="rated_median_useful_life",
        translation_key="rated_median_useful_life",
        device_class=SensorDeviceClass.DURATION,
        native_unit_of_measurement=UnitOfTime.HOURS,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda data: data.rated_median_useful_life,
    ),
    DaliMaintenanceSensorDescription(
        key="rated_median_useful_light_source_starts",
        translation_key="rated_median_useful_light_source_starts",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda data: data.rated_median_useful_light_source_starts,
    ),
    DaliMaintenanceSensorDescription(
        key="control_gear_reference_temperature",
        translation_key="control_gear_reference_temperature",
        device_class=SensorDeviceClass.TEMPERATURE,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda data: data.control_gear_reference_temperature,
    ),
)


@dataclass(frozen=True, kw_only=True)
class DaliGearDiagnosticSensorDescription(SensorEntityDescription):
    """Description of a memory bank 205 or 206 diagnostics measurement."""

    value_fn: Callable[[DaliDiagnosticsData], int | float | None]


GEAR_DIAGNOSTIC_SENSOR_TYPES: tuple[DaliGearDiagnosticSensorDescription, ...] = (
    DaliGearDiagnosticSensorDescription(
        key="control_gear_operating_time",
        translation_key="control_gear_operating_time",
        device_class=SensorDeviceClass.DURATION,
        native_unit_of_measurement=UnitOfTime.SECONDS,
        state_class=SensorStateClass.TOTAL_INCREASING,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda data: data.control_gear_operating_time,
    ),
    DaliGearDiagnosticSensorDescription(
        key="control_gear_start_counter",
        translation_key="control_gear_start_counter",
        state_class=SensorStateClass.TOTAL_INCREASING,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda data: data.control_gear_start_counter,
    ),
    DaliGearDiagnosticSensorDescription(
        key="control_gear_external_supply_voltage",
        translation_key="control_gear_external_supply_voltage",
        device_class=SensorDeviceClass.VOLTAGE,
        native_unit_of_measurement=UnitOfElectricPotential.VOLT,
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda data: data.control_gear_external_supply_voltage,
    ),
    DaliGearDiagnosticSensorDescription(
        key="control_gear_supply_frequency",
        translation_key="control_gear_supply_frequency",
        device_class=SensorDeviceClass.FREQUENCY,
        native_unit_of_measurement=UnitOfFrequency.HERTZ,
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda data: data.control_gear_supply_frequency,
    ),
    DaliGearDiagnosticSensorDescription(
        key="control_gear_power_factor",
        device_class=SensorDeviceClass.POWER_FACTOR,
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda data: data.control_gear_power_factor,
    ),
    DaliGearDiagnosticSensorDescription(
        key="control_gear_internal_temperature",
        translation_key="control_gear_internal_temperature",
        device_class=SensorDeviceClass.TEMPERATURE,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda data: data.control_gear_internal_temperature,
    ),
    DaliGearDiagnosticSensorDescription(
        key="control_gear_output_current_percent",
        translation_key="control_gear_output_current_percent",
        native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda data: data.control_gear_output_current_percent,
    ),
    DaliGearDiagnosticSensorDescription(
        key="light_source_on_time",
        translation_key="light_source_on_time",
        device_class=SensorDeviceClass.DURATION,
        native_unit_of_measurement=UnitOfTime.SECONDS,
        state_class=SensorStateClass.TOTAL_INCREASING,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda data: data.light_source_on_time,
    ),
    DaliGearDiagnosticSensorDescription(
        key="light_source_on_time_resettable",
        translation_key="light_source_on_time_resettable",
        device_class=SensorDeviceClass.DURATION,
        native_unit_of_measurement=UnitOfTime.SECONDS,
        state_class=SensorStateClass.TOTAL_INCREASING,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda data: data.light_source_on_time_resettable,
    ),
    DaliGearDiagnosticSensorDescription(
        key="light_source_start_counter",
        translation_key="light_source_start_counter",
        state_class=SensorStateClass.TOTAL_INCREASING,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda data: data.light_source_start_counter,
    ),
    DaliGearDiagnosticSensorDescription(
        key="light_source_start_counter_resettable",
        translation_key="light_source_start_counter_resettable",
        state_class=SensorStateClass.TOTAL_INCREASING,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda data: data.light_source_start_counter_resettable,
    ),
    DaliGearDiagnosticSensorDescription(
        key="light_source_voltage",
        translation_key="light_source_voltage",
        device_class=SensorDeviceClass.VOLTAGE,
        native_unit_of_measurement=UnitOfElectricPotential.VOLT,
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda data: data.light_source_voltage,
    ),
    DaliGearDiagnosticSensorDescription(
        key="light_source_current",
        translation_key="light_source_current",
        device_class=SensorDeviceClass.CURRENT,
        native_unit_of_measurement=UnitOfElectricCurrent.AMPERE,
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda data: data.light_source_current,
    ),
    DaliGearDiagnosticSensorDescription(
        key="light_source_temperature",
        translation_key="light_source_temperature",
        device_class=SensorDeviceClass.TEMPERATURE,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda data: data.light_source_temperature,
    ),
)

ACTIVE_ENERGY_SENSOR = SensorEntityDescription(
    key="active_energy",
    translation_key="active_energy",
    device_class=SensorDeviceClass.ENERGY,
    native_unit_of_measurement=UnitOfEnergy.WATT_HOUR,
    state_class=SensorStateClass.TOTAL_INCREASING,
    entity_category=EntityCategory.DIAGNOSTIC,
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: DaliConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up illuminance entities."""
    coordinator = entry.runtime_data
    known: set[tuple[int, int]] = set()
    known_emergency: set[int] = set()

    @callback
    def async_add_emergency_sensors() -> None:
        entities: list[SensorEntity] = []
        for address, gear in coordinator.data.items():
            if address in known_emergency:
                continue
            if DEVICE_TYPE_EMERGENCY not in gear.device_types:
                continue
            known_emergency.add(address)
            entities.extend(
                DaliEmergencySensor(
                    coordinator, entry.entry_id, entry.title, address, description
                )
                for description in EMERGENCY_SENSOR_TYPES
            )
        async_add_entities(entities)

    async_add_emergency_sensors()
    entry.async_on_unload(coordinator.async_add_listener(async_add_emergency_sensors))

    @callback
    def async_add_new_entities() -> None:
        entities: list[SensorEntity] = []
        for address, instance, instance_type in coordinator.device_instances:
            key = (address, instance)
            if key in known:
                continue
            if instance_type == 4:
                entities.append(
                    DaliIlluminance(
                        coordinator, entry.entry_id, entry.title, address, instance
                    )
                )
            elif instance_type == 6 and key in coordinator.input_devices:
                entities.append(
                    DaliPart306Sensor(
                        coordinator, entry.entry_id, entry.title, address, instance
                    )
                )
            else:
                continue
            known.add(key)
        async_add_entities(entities)

    async_add_new_entities()
    entry.async_on_unload(coordinator.async_add_listener(async_add_new_entities))

    known_identification_gear: set[int] = set()
    known_identification_devices: set[int] = set()

    @callback
    def async_add_identification_sensors() -> None:
        entities: list[SensorEntity] = []
        for address in set(coordinator.data) - known_identification_gear:
            known_identification_gear.add(address)
            entities.append(
                DaliAddressSensor(coordinator, entry.entry_id, entry.title, address)
            )
            entities.extend(
                DaliIdentificationSensor(
                    coordinator, entry.entry_id, entry.title, address, description
                )
                for description in IDENTIFICATION_SENSOR_TYPES
            )
        device_addresses = {
            address for address, _instance, _type in coordinator.device_instances
        }
        for address in device_addresses - known_identification_devices:
            known_identification_devices.add(address)
            entities.append(
                DaliAddressSensor(
                    coordinator,
                    entry.entry_id,
                    entry.title,
                    address,
                    input_device=True,
                )
            )
            entities.extend(
                DaliIdentificationSensor(
                    coordinator,
                    entry.entry_id,
                    entry.title,
                    address,
                    description,
                    input_device=True,
                )
                for description in IDENTIFICATION_SENSOR_TYPES
            )
        async_add_entities(entities)

    async_add_identification_sensors()
    entry.async_on_unload(
        coordinator.async_add_listener(async_add_identification_sensors)
    )

    known_luminaire: set[int] = set()
    known_maintenance: set[int] = set()
    known_diagnostics: set[int] = set()
    known_energy: set[int] = set()

    @callback
    def async_add_memory_bank_sensors() -> None:
        entities: list[SensorEntity] = []
        for address, gear in coordinator.data.items():
            if gear.luminaire is not None and address not in known_luminaire:
                known_luminaire.add(address)
                entities.extend(
                    DaliLuminaireSensor(
                        coordinator, entry.entry_id, entry.title, address, description
                    )
                    for description in LUMINAIRE_SENSOR_TYPES
                )
            if gear.maintenance is not None and address not in known_maintenance:
                known_maintenance.add(address)
                entities.extend(
                    DaliMaintenanceSensor(
                        coordinator, entry.entry_id, entry.title, address, description
                    )
                    for description in MAINTENANCE_SENSOR_TYPES
                )
            if gear.diagnostics is not None and address not in known_diagnostics:
                known_diagnostics.add(address)
                entities.extend(
                    DaliGearDiagnosticSensor(
                        coordinator, entry.entry_id, entry.title, address, description
                    )
                    for description in GEAR_DIAGNOSTIC_SENSOR_TYPES
                )
            if gear.active_energy is not None and address not in known_energy:
                known_energy.add(address)
                entities.append(
                    DaliEnergySensor(
                        coordinator,
                        entry.entry_id,
                        entry.title,
                        address,
                        ACTIVE_ENERGY_SENSOR,
                    )
                )
        async_add_entities(entities)

    async_add_memory_bank_sensors()
    entry.async_on_unload(coordinator.async_add_listener(async_add_memory_bank_sensors))


class DaliIlluminance(SensorEntity):
    """Representation of a DALI-2 relative illuminance instance."""

    _attr_has_entity_name = True
    _attr_translation_key = "illuminance"
    _attr_state_class = SensorStateClass.MEASUREMENT

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
        self._attr_unique_id = f"{entry_id}_{address}_{instance}_illuminance"
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

    @property
    @override
    def native_value(self) -> int | None:
        """Return the relative illuminance value."""
        event = self._coordinator.event_data.get(self._key)
        return event.illuminance if isinstance(event, LightEvent) else None

    @callback
    def _handle_event(self, event: object) -> None:
        """Handle an illuminance event."""
        if (
            isinstance(event, LightEvent)
            and event.short_address is not None
            and (
                event.short_address.address,
                event.instance_number,
            )
            == self._key
        ):
            self.async_write_ha_state()


class DaliPart306Sensor(SensorEntity):
    """Representation of a DALI-2 Part 306 general sensor instance."""

    _attr_has_entity_name = True

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
        self._data = coordinator.input_devices[self._key]
        description = _description_for_sensor(self._data)
        self.entity_description = description
        self._attr_translation_key = description.translation_key
        self._attr_unique_id = f"{entry_id}_{address}_{instance}_{description.key}"
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

    @property
    @override
    def native_value(self) -> float | int | None:
        """Return the latest decoded measurement value."""
        event = self._coordinator.event_data.get(self._key)
        if not isinstance(event, GeneralSensorEvent):
            return None
        return _measurement_from_event(event.measured_value, self._data)

    @callback
    def _handle_event(self, event: object) -> None:
        """Handle a Part 306 general sensor event."""
        if (
            isinstance(event, GeneralSensorEvent)
            and event.short_address is not None
            and (
                event.short_address.address,
                event.instance_number,
            )
            == self._key
        ):
            self.async_write_ha_state()


class DaliIdentificationSensor(CoordinatorEntity[DaliCoordinator], SensorEntity):
    """Representation of a memory bank 0 identification value of a bus unit.

    The device registry shows the batch and serial number joined in its single
    serial number field, so this diagnostic entity is what exposes the undivided
    value memory bank 0 actually stores.
    """

    _attr_has_entity_name = True
    entity_description: DaliIdentificationSensorDescription

    def __init__(
        self,
        coordinator: DaliCoordinator,
        entry_id: str,
        title: str,
        address: int,
        description: DaliIdentificationSensorDescription,
        *,
        input_device: bool = False,
    ) -> None:
        """Initialize the entity."""
        super().__init__(coordinator)
        self.entity_description = description
        self._address = address
        self._input_device = input_device
        kind = "controldevice_" if input_device else ""
        self._attr_unique_id = f"{entry_id}_{address}_{kind}{description.key}"
        self._attr_device_info = coordinator.device_info(
            entry_id, title, address, input_device=input_device
        )

    @property
    @override
    def native_value(self) -> str | int | None:
        """Return the identification value read from memory bank 0."""
        return self.entity_description.value_fn(
            self.coordinator.device_data(self._address, input_device=self._input_device)
        )


class DaliAddressSensor(CoordinatorEntity[DaliCoordinator], SensorEntity):
    """Representation of a bus unit's DALI short address.

    The device registry has no field for the bus address, so this diagnostic
    entity exposes it. The address is also part of the device name.
    """

    _attr_has_entity_name = True
    _attr_translation_key = "dali_address"
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(
        self,
        coordinator: DaliCoordinator,
        entry_id: str,
        title: str,
        address: int,
        *,
        input_device: bool = False,
    ) -> None:
        """Initialize the entity."""
        super().__init__(coordinator)
        self._address = address
        kind = "controldevice_" if input_device else ""
        self._attr_unique_id = f"{entry_id}_{address}_{kind}dali_address"
        self._attr_device_info = coordinator.device_info(
            entry_id, title, address, input_device=input_device
        )

    @property
    @override
    def native_value(self) -> int:
        """Return the bus short address."""
        return self._address


class DaliEmergencySensor(CoordinatorEntity[DaliCoordinator], SensorEntity):
    """Representation of a DT1 emergency control-gear sensor."""

    _attr_has_entity_name = True
    entity_description: DaliEmergencySensorDescription

    def __init__(
        self,
        coordinator: DaliCoordinator,
        entry_id: str,
        title: str,
        address: int,
        description: DaliEmergencySensorDescription,
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
    def native_value(self) -> int | float | str | None:
        """Return the current value of the described emergency variable."""
        gear = self.coordinator.data.get(self._address)
        if gear is None or gear.emergency is None:
            return None
        return self.entity_description.value_fn(gear.emergency)


class DaliGearBankSensor(CoordinatorEntity[DaliCoordinator], SensorEntity):
    """Base for a sensor reading one value out of an extended memory bank.

    A bus unit implements each bank independently, so an entity reports itself
    unavailable until its own bank has answered.
    """

    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: DaliCoordinator,
        entry_id: str,
        title: str,
        address: int,
        description: SensorEntityDescription,
    ) -> None:
        """Initialize the entity."""
        super().__init__(coordinator)
        self.entity_description = description
        self._address = address
        self._attr_unique_id = f"{entry_id}_{address}_{description.key}"
        self._attr_device_info = coordinator.device_info(entry_id, title, address)

    @property
    def _gear(self) -> DaliGearData | None:
        """Return the data of the control gear this sensor belongs to."""
        return self.coordinator.data.get(self._address)


class DaliLuminaireSensor(DaliGearBankSensor):
    """Representation of a memory bank 1 luminaire value of a control gear."""

    entity_description: DaliLuminaireSensorDescription

    @property
    @override
    def available(self) -> bool:
        """Return whether the luminaire memory bank has been read."""
        gear = self._gear
        return super().available and gear is not None and gear.luminaire is not None

    @property
    @override
    def native_value(self) -> int | str | None:
        """Return the described luminaire value."""
        gear = self._gear
        if gear is None or gear.luminaire is None:
            return None
        return self.entity_description.value_fn(gear.luminaire)


class DaliMaintenanceSensor(DaliGearBankSensor):
    """Representation of a memory bank 207 rated-life value of a control gear."""

    entity_description: DaliMaintenanceSensorDescription

    @property
    @override
    def available(self) -> bool:
        """Return whether the maintenance memory bank has been read."""
        gear = self._gear
        return super().available and gear is not None and gear.maintenance is not None

    @property
    @override
    def native_value(self) -> int | None:
        """Return the described rated-life value."""
        gear = self._gear
        if gear is None or gear.maintenance is None:
            return None
        return self.entity_description.value_fn(gear.maintenance)


class DaliGearDiagnosticSensor(DaliGearBankSensor):
    """Representation of a memory bank 205 or 206 diagnostics measurement."""

    entity_description: DaliGearDiagnosticSensorDescription

    @property
    @override
    def available(self) -> bool:
        """Return whether the diagnostics memory banks have been read."""
        gear = self._gear
        return super().available and gear is not None and gear.diagnostics is not None

    @property
    @override
    def native_value(self) -> int | float | None:
        """Return the described diagnostics measurement."""
        gear = self._gear
        if gear is None or gear.diagnostics is None:
            return None
        return self.entity_description.value_fn(gear.diagnostics)


class DaliEnergySensor(DaliGearBankSensor):
    """Representation of the memory bank 202 active energy total of a gear."""

    @property
    @override
    def available(self) -> bool:
        """Return whether the energy memory bank has been read."""
        gear = self._gear
        return super().available and gear is not None and gear.active_energy is not None

    @property
    @override
    def native_value(self) -> float | None:
        """Return the energy the gear has consumed since it was built."""
        gear = self._gear
        return gear.active_energy if gear is not None else None


def _description_for_sensor(
    data: DaliGeneralSensorData,
) -> SensorEntityDescription:
    """Return an entity description for a Part 306 sensor."""
    if data.quantity_name in DALI_PART306_SENSOR_TYPES:
        return DALI_PART306_SENSOR_TYPES[data.quantity_name]
    return SensorEntityDescription(
        key=f"part306_{data.quantity_name or 'unknown'}",
        translation_key="part306_sensor",
        native_unit_of_measurement=_unit_for_sensor(data),
        state_class=SensorStateClass.MEASUREMENT,
        entity_registry_enabled_default=False,
    )


DALI_PART306_UNITS: dict[int, str] = {
    UnitOfMeasurement.CELSIUS: UnitOfTemperature.CELSIUS,
    UnitOfMeasurement.KELVIN: UnitOfTemperature.KELVIN,
    UnitOfMeasurement.PASCAL: UnitOfPressure.PA,
    UnitOfMeasurement.PERCENT: UnitOfRatio.PERCENTAGE,
    UnitOfMeasurement.PARTS_PER_MILLION: UnitOfRatio.PARTS_PER_MILLION,
    UnitOfMeasurement.DECIBEL_A: UnitOfSoundPressure.WEIGHTED_DECIBEL_A,
}


def _unit_for_sensor(data: DaliGeneralSensorData) -> str | None:
    """Return the native unit for an unclassified Part 306 sensor."""
    if data.unit_of_measurement is None:
        return None
    return DALI_PART306_UNITS.get(data.unit_of_measurement)


def _measurement_from_event(
    event_value: int, data: DaliGeneralSensorData
) -> float | int | None:
    """Convert a Part 306 event payload to a measured value."""
    if data.resolution is None or data.magnitude is None:
        return event_value
    if not 1 <= data.resolution <= 24:
        return event_value
    if data.resolution <= 9:
        measured_value = event_value >> (9 - data.resolution)
    else:
        # Per IEC 62386-306 Annex B, the low bits lost to the 9-bit event
        # payload are reconstructed by repeating the most significant bits.
        measured_value = event_value << (data.resolution - 9)
        if data.resolution <= 18:
            measured_value += event_value >> (18 - data.resolution)
    offset = (2 ** (data.resolution - 1)) - 1 if data.input_signal_signed else 0
    value = (measured_value - offset) * (10 ** (data.magnitude - 127))
    return int(value) if value == int(value) else value
