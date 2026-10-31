"""Gateway connection and readiness are distinct from RF thermostat status."""

from homeassistant.components.binary_sensor import BinarySensorDeviceClass, BinarySensorEntity
from homeassistant.const import EntityCategory

from .entity import SpiderEntity

PARALLEL_UPDATES = 0


async def async_setup_entry(hass, entry, async_add_entities) -> None:
    async_add_entities(
        SpiderBinarySensor(entry.runtime_data, entry, key)
        for key in ("gateway_connected", "control_ready", "battery_low")
    )


class SpiderBinarySensor(SpiderEntity, BinarySensorEntity):
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, coordinator, entry, key: str) -> None:
        super().__init__(coordinator, entry, key)
        self._key = key
        self._attr_translation_key = key
        if key == "gateway_connected":
            self._attr_device_class = BinarySensorDeviceClass.CONNECTIVITY
        elif key == "battery_low":
            self._attr_device_class = BinarySensorDeviceClass.BATTERY

    @property
    def available(self) -> bool:
        return self.coordinator.controller.available if self._key == "battery_low" else True

    @property
    def is_on(self) -> bool | None:
        controller = self.coordinator.controller
        if self._key == "gateway_connected":
            return controller.connected
        if self._key == "control_ready":
            return controller.control_ready
        return controller.state.battery_low
