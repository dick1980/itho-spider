"""Shared identity and availability for Spider entities."""

from homeassistant.const import CONF_NAME
from homeassistant.helpers.device_registry import DeviceInfo, async_get
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import CONF_GATEWAY_ID, CONF_SPIDER_ID, DOMAIN
from .coordinator import SpiderCoordinator


class SpiderEntity(CoordinatorEntity[SpiderCoordinator]):
    _attr_has_entity_name = True

    def __init__(self, coordinator: SpiderCoordinator, entry, key: str) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{entry.data[CONF_SPIDER_ID]}_{key}"
        gateways = async_get(coordinator.hass).async_get_devices(
            identifiers={(DOMAIN, entry.data[CONF_GATEWAY_ID])}
        )
        gateway = gateways[0] if gateways else None
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.data[CONF_SPIDER_ID])},
            name=entry.data[CONF_NAME],
            manufacturer="Itho Daalderop",
            model="Spider",
            via_device_id=gateway.id if gateway else None,
        )

    @property
    def available(self) -> bool:
        return self.coordinator.controller.available
