"""Explicitly arm gateway pairing for one configured Spider."""

from homeassistant.components.button import ButtonEntity
from homeassistant.const import EntityCategory
from homeassistant.exceptions import HomeAssistantError

from .controller import ControlError
from .entity import SpiderEntity

PARALLEL_UPDATES = 0


async def async_setup_entry(hass, entry, async_add_entities):
    async_add_entities([SpiderPairButton(entry.runtime_data, entry)])


class SpiderPairButton(SpiderEntity, ButtonEntity):
    _attr_translation_key = "pair_gateway"
    _attr_entity_category = EntityCategory.CONFIG
    _attr_icon = "mdi:access-point-plus"

    def __init__(self, coordinator, entry):
        super().__init__(coordinator, entry, "pair_gateway")

    @property
    def available(self):
        controller = self.coordinator.controller
        return controller.connected and controller.enable_control

    async def async_press(self):
        try:
            self.coordinator.controller.arm_pairing()
        except ControlError as exc:
            raise HomeAssistantError(str(exc)) from exc

    @property
    def extra_state_attributes(self):
        return {"pairing_status": self.coordinator.controller.pairing_status}
