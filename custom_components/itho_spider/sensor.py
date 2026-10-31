"""Reported Spider measurements and diagnostic states."""

from collections.abc import Callable
from dataclasses import dataclass

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.const import PERCENTAGE, EntityCategory, UnitOfTemperature

from .entity import SpiderEntity

PARALLEL_UPDATES = 0


@dataclass(frozen=True, kw_only=True)
class SpiderSensorDescription(SensorEntityDescription):
    value_fn: Callable


DESCRIPTIONS = (
    SpiderSensorDescription(
        key="command_status",
        translation_key="command_status",
        device_class=SensorDeviceClass.ENUM,
        options=[
            "idle",
            "pending",
            "waiting_for_thermostat",
            "confirmed",
            "overridden_locally",
            "cancelled_mode_change",
            "unconfirmed",
            "cancelled_unconfirmed",
            "failed",
        ],
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda c: c.last_command_result or "idle",
    ),
    SpiderSensorDescription(
        key="temperature",
        translation_key="temperature",
        device_class=SensorDeviceClass.TEMPERATURE,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda c: c.state.temperature,
    ),
    SpiderSensorDescription(
        key="target_temperature",
        translation_key="target_temperature",
        device_class=SensorDeviceClass.TEMPERATURE,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        value_fn=lambda c: c.state.target_temperature,
    ),
    SpiderSensorDescription(
        key="heating_demand",
        translation_key="heating_demand",
        native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda c: (
            None if c.state.heating_demand is None else round(c.state.heating_demand * 100, 1)
        ),
    ),
    SpiderSensorDescription(
        key="battery",
        translation_key="battery",
        device_class=SensorDeviceClass.BATTERY,
        native_unit_of_measurement=PERCENTAGE,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda c: c.state.battery_percent,
    ),
    SpiderSensorDescription(
        key="operating_mode",
        translation_key="operating_mode",
        device_class=SensorDeviceClass.ENUM,
        options=["heat", "cool", "off"],
        value_fn=lambda c: c.state.operating_mode,
    ),
    SpiderSensorDescription(
        key="program_mode",
        translation_key="program_mode",
        device_class=SensorDeviceClass.ENUM,
        options=["manual", "schedule", "temporary_override"],
        value_fn=lambda c: (
            None
            if c.state.time_planning is None
            else (
                "temporary_override"
                if c.state.time_planning and c.state.temp_adjusted
                else "schedule"
                if c.state.time_planning
                else "manual"
            )
        ),
    ),
    SpiderSensorDescription(
        key="last_seen",
        translation_key="last_seen",
        device_class=SensorDeviceClass.TIMESTAMP,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda c: c.last_seen_utc,
    ),
)


async def async_setup_entry(hass, entry, async_add_entities) -> None:
    async_add_entities(SpiderSensor(entry.runtime_data, entry, d) for d in DESCRIPTIONS)


class SpiderSensor(SpiderEntity, SensorEntity):
    def __init__(self, coordinator, entry, description) -> None:
        super().__init__(coordinator, entry, description.key)
        self.entity_description = description

    @property
    def native_value(self):
        return self.entity_description.value_fn(self.coordinator.controller)

    @property
    def extra_state_attributes(self):
        if self.entity_description.key == "command_status":
            return {"pending_temperature": self.coordinator.controller.pending_temperature}
        return None
