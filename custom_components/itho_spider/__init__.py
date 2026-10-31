"""Itho Spider through a directly connected evofw3 USB gateway."""

import os

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_PORT, EVENT_HOMEASSISTANT_STOP, Platform
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryNotReady
from homeassistant.helpers import device_registry as dr

from .const import CONF_GATEWAY_ID, CONF_SPIDER_ID, DOMAIN
from .coordinator import SpiderCoordinator
from .shared_gateway import DATA_GATEWAYS, get_gateway

PLATFORMS = [Platform.CLIMATE, Platform.SENSOR, Platform.BINARY_SENSOR, Platform.BUTTON]
type SpiderConfigEntry = ConfigEntry[SpiderCoordinator]


async def async_setup_entry(hass: HomeAssistant, entry: SpiderConfigEntry) -> bool:
    port = await hass.async_add_executor_job(os.path.realpath, entry.data[CONF_PORT])
    pool = hass.data.setdefault(DATA_GATEWAYS, {})
    try:
        gateway = get_gateway(pool, port, entry.data[CONF_GATEWAY_ID])
    except ValueError as exc:
        raise ConfigEntryNotReady(str(exc)) from exc
    coordinator = SpiderCoordinator(
        hass,
        entry,
        port=port,
        transport_factory=gateway.client_factory(entry.data[CONF_SPIDER_ID]),
    )
    try:
        await coordinator.controller.async_start()
    except (OSError, TimeoutError, ValueError) as exc:
        raise ConfigEntryNotReady(f"Cannot identify the USB gateway: {exc}") from exc
    entry.runtime_data = coordinator

    async def async_stop(event) -> None:
        await coordinator.controller.async_close()

    entry.async_on_unload(hass.bus.async_listen_once(EVENT_HOMEASSISTANT_STOP, async_stop))
    registry = dr.async_get(hass)
    if not registry.async_get_devices(identifiers={(DOMAIN, entry.data[CONF_GATEWAY_ID])}):
        registry.async_get_or_create(
            config_entry_id=entry.entry_id,
            identifiers={(DOMAIN, entry.data[CONF_GATEWAY_ID])},
            name="evofw3 USB gateway",
            manufacturer="evofw3",
            model="USB RF gateway",
        )
    try:
        await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    except BaseException:
        await coordinator.controller.async_close()
        raise
    return True


async def async_unload_entry(hass: HomeAssistant, entry: SpiderConfigEntry) -> bool:
    if unloaded := await hass.config_entries.async_unload_platforms(entry, PLATFORMS):
        await entry.runtime_data.controller.async_close()
    return unloaded


async def async_remove_entry(hass: HomeAssistant, entry: SpiderConfigEntry) -> None:
    """Keep the shared gateway device ID when its original owner is removed."""
    peers = [
        peer
        for peer in hass.config_entries.async_entries(DOMAIN)
        if peer.entry_id != entry.entry_id
        and peer.data.get(CONF_GATEWAY_ID) == entry.data[CONF_GATEWAY_ID]
    ]
    if peers:
        registry = dr.async_get(hass)
        for device in registry.async_get_devices(
            identifiers={(DOMAIN, entry.data[CONF_GATEWAY_ID])}
        ):
            if device.config_entry_id == entry.entry_id:
                registry.async_update_device(device.id, new_config_entry_id=peers[0].entry_id)


async def async_migrate_entry(hass: HomeAssistant, entry: SpiderConfigEntry) -> bool:
    """Keep existing devices/entity IDs when changing uniqueness to each Spider."""
    if entry.version == 1:
        hass.config_entries.async_update_entry(
            entry, version=2, unique_id=entry.data[CONF_SPIDER_ID]
        )
    return entry.version == 2
