"""Temperature control without advertising unimplemented HVAC mode changes."""

from typing import Any

from homeassistant.components.climate import (
    ClimateEntity,
    ClimateEntityFeature,
    HVACAction,
    HVACMode,
)
from homeassistant.const import ATTR_TEMPERATURE, UnitOfTemperature
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError

from .controller import ControlError
from .entity import SpiderEntity
from .protocol import MAX_TEMPERATURE, MIN_TEMPERATURE, ProtocolError

PARALLEL_UPDATES = 0


async def async_setup_entry(hass, entry, async_add_entities) -> None:
    async_add_entities([SpiderClimate(entry.runtime_data, entry)])


class SpiderClimate(SpiderEntity, ClimateEntity):
    _attr_name = None
    _attr_translation_key = "thermostat"
    _attr_temperature_unit = UnitOfTemperature.CELSIUS
    _attr_target_temperature_step = 0.5
    _attr_min_temp = MIN_TEMPERATURE
    _attr_max_temp = MAX_TEMPERATURE
    _enable_turn_on_off_backwards_compatibility = False

    def __init__(self, coordinator, entry) -> None:
        super().__init__(coordinator, entry, "climate")

    @property
    def supported_features(self) -> ClimateEntityFeature:
        if self.coordinator.controller.enable_control:
            return ClimateEntityFeature.TARGET_TEMPERATURE
        return ClimateEntityFeature(0)

    @property
    def current_temperature(self) -> float | None:
        return self.coordinator.data.temperature

    @property
    def target_temperature(self) -> float | None:
        return self.coordinator.data.target_temperature

    @property
    def hvac_mode(self) -> HVACMode | None:
        mode = self.coordinator.data.operating_mode
        return {"heat": HVACMode.HEAT, "cool": HVACMode.COOL, "off": HVACMode.OFF}.get(mode)

    @property
    def hvac_modes(self) -> list[HVACMode]:
        # Only the current mode can be selected. No unsupported off/cool writes.
        return [self.hvac_mode] if self.hvac_mode is not None else []

    @property
    def hvac_action(self) -> HVACAction | None:
        state = self.coordinator.data
        if state.operating_mode == "off":
            return HVACAction.OFF
        if state.demand is None:
            return None
        if state.demand == 0:
            return HVACAction.IDLE
        return {"heat": HVACAction.HEATING, "cool": HVACAction.COOLING}.get(state.operating_mode)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        controller = self.coordinator.controller
        return {
            "control_ready": controller.control_ready,
            "wait_for_wakeup": controller.wait_for_wakeup,
            "time_planning": controller.state.time_planning,
            "temporary_adjustment": controller.state.temp_adjusted,
            "second_temperature_field": controller.state.cooling_target,
            "pending_temperature": controller.pending_temperature,
            "last_command_result": controller.last_command_result,
        }

    async def async_set_hvac_mode(self, hvac_mode: HVACMode) -> None:
        if hvac_mode != self.hvac_mode:
            raise ServiceValidationError("Change heating/cooling/off mode on the Spider itself")

    async def async_set_temperature(self, **kwargs: Any) -> None:
        if (mode := kwargs.get("hvac_mode")) is not None and mode != self.hvac_mode:
            raise ServiceValidationError("Change heating/cooling/off mode on the Spider itself")
        if ATTR_TEMPERATURE not in kwargs:
            raise ServiceValidationError("A target temperature is required")
        try:
            await self.coordinator.controller.async_set_temperature(kwargs[ATTR_TEMPERATURE])
        except ProtocolError as exc:
            raise ServiceValidationError(str(exc)) from exc
        except (ControlError, OSError, TimeoutError) as exc:
            raise HomeAssistantError(str(exc)) from exc
