"""Frozen 0.4.0 registry contract, using synthetic identities only.

Seed existing HA registry records before loading the candidate. Deliberately do
not import entity descriptions: changing a production key must fail this test.
"""

from copy import deepcopy
from unittest.mock import patch

import pytest
from homeassistant.config_entries import ConfigEntryState
from homeassistant.helpers import area_registry as ar
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry
from test_integration import FakeTransport

from custom_components.itho_spider import async_migrate_entry
from custom_components.itho_spider.config_flow import IthoSpiderConfigFlow

DOMAIN = "itho_spider"
GATEWAY = "18:123456"
SPIDERS = ("21:123456", "21:123457")
KEYS_040 = {
    "climate": ("climate",),
    "sensor": (
        "command_status", "temperature", "target_temperature", "heating_demand",
        "battery", "operating_mode", "program_mode", "last_seen",
    ),
    "binary_sensor": ("gateway_connected", "control_ready", "battery_low"),
    "button": ("pair_gateway",),
}


def entry_snapshot(entry):
    return deepcopy((entry.entry_id, entry.unique_id, entry.version, entry.minor_version,
                     entry.title, dict(entry.data), dict(entry.options)))


def entity_snapshot(record):
    return (record.id, record.entity_id, record.unique_id, record.config_entry_id,
            record.device_id, record.name, record.icon, record.area_id,
            record.disabled_by, record.hidden_by)


def device_snapshot(record):
    return (record.id, record.identifiers, record.config_entry_id,
            record.via_device_id, record.name_by_user, record.area_id)


@pytest.mark.asyncio
async def test_040_two_spiders_keep_entries_registries_options_and_references(hass):
    """Existing renamed/disabled records survive setup and a complete reload."""
    assert IthoSpiderConfigFlow.VERSION == 2
    entities, devices = er.async_get(hass), dr.async_get(hass)
    area = ar.async_get(hass).async_create("Test area")
    entries, old_entities, old_devices = [], {}, {}
    gateway = None
    for index, spider in enumerate(SPIDERS):
        entry = MockConfigEntry(
            domain=DOMAIN, version=2, minor_version=1, unique_id=spider,
            title=f"Existing thermostat {index}",
            data={"port": "/dev/serial/by-id/test-upgrade", "gateway_id": GATEWAY,
                  "spider_id": spider, "name": f"Existing thermostat {index}"},
            options={"enable_control": True, "wait_for_wakeup": bool(index),
                     "reserved_user_option": "keep-me"},
        )
        entry.add_to_hass(hass)
        entries.append(entry)
        if gateway is None:
            gateway = devices.async_get_or_create(
                config_entry_id=entry.entry_id, identifiers={(DOMAIN, GATEWAY)},
                name="evofw3 USB gateway",
            )
            gateway = devices.async_update_device(
                gateway.id, name_by_user="Existing shared gateway", area_id=area.id
            )
            old_devices[gateway.id] = device_snapshot(gateway)
        device = devices.async_get_or_create(
            config_entry_id=entry.entry_id, identifiers={(DOMAIN, spider)},
            name=entry.data["name"], via_device_id=gateway.id,
        )
        device = devices.async_update_device(
            device.id, name_by_user=f"Custom device {index}", area_id=area.id
        )
        old_devices[device.id] = device_snapshot(device)
        for domain, keys in KEYS_040.items():
            for key in keys:
                record = entities.async_get_or_create(
                    domain, DOMAIN, f"{spider}_{key}", config_entry=entry,
                    device_id=device.id, suggested_object_id=f"existing_{index}_{key}",
                    disabled_by=er.RegistryEntryDisabler.USER if key == "battery" else None,
                    hidden_by=er.RegistryEntryHider.USER if key == "last_seen" else None,
                )
                record = entities.async_update_entity(
                    record.entity_id, name=f"Custom {key}", icon="mdi:thermometer",
                    area_id=area.id,
                )
                old_entities[record.entity_id] = entity_snapshot(record)
    old_entries = [entry_snapshot(e) for e in entries]
    buses = []

    def transport_factory(*args, **kwargs):
        bus = FakeTransport(*args, **kwargs)
        buses.append(bus)
        return bus

    with patch("custom_components.itho_spider.shared_gateway.GatewayTransport", transport_factory):
        try:
            for cycle in range(2):
                for entry in entries:
                    assert await async_migrate_entry(hass, entry)  # v2 is a no-op
                    if entry.state is not ConfigEntryState.LOADED:
                        assert await hass.config_entries.async_setup(entry.entry_id)
                    assert entry.state is ConfigEntryState.LOADED
                await hass.async_block_till_done()
                assert [entry_snapshot(e) for e in entries] == old_entries
                assert len(entities.entities) == 26
                assert len(devices.devices) == 3
                for entity_id, before in old_entities.items():
                    assert entity_snapshot(entities.async_get(entity_id)) == before
                    if not before[-2]:  # all enabled dashboard/automation entity references resolve
                        assert hass.states.get(entity_id) is not None
                for device_id, before in old_devices.items():
                    assert device_snapshot(devices.async_get(device_id)) == before
                assert len(buses) == 1 and buses[0].connect_count == cycle + 1
                assert buses[0].sent == []  # no pairing, relay or temperature command on startup
                direct, battery = [e.runtime_data.controller for e in entries]
                assert direct.enable_control and battery.enable_control
                assert direct.wait_for_wakeup is False and battery.wait_for_wakeup is True
                assert direct.pending_temperature is None and battery.pending_temperature is None
                for entry in entries:
                    assert await hass.config_entries.async_unload(entry.entry_id)
        finally:
            for entry in entries:
                await hass.config_entries.async_unload(entry.entry_id)


@pytest.mark.asyncio
@pytest.mark.parametrize("options", [{}, {"enable_control": False, "wait_for_wakeup": True}])
async def test_v1_migration_keeps_data_options_and_entry_id(hass, options):
    entry = MockConfigEntry(
        domain=DOMAIN, version=1, unique_id=GATEWAY, title="Legacy thermostat",
        data={"port": "/dev/test", "gateway_id": GATEWAY, "spider_id": SPIDERS[0],
              "name": "Legacy thermostat"}, options=options,
    )
    entry.add_to_hass(hass)
    before = entry_snapshot(entry)
    assert await async_migrate_entry(hass, entry)
    after = entry_snapshot(entry)
    assert after == (before[0], SPIDERS[0], 2, *before[3:])


@pytest.mark.asyncio
async def test_future_schema_is_refused_without_rewriting(hass):
    entry = MockConfigEntry(domain=DOMAIN, version=3, unique_id=SPIDERS[0],
                            data={"spider_id": SPIDERS[0]}, options={"wait_for_wakeup": True})
    entry.add_to_hass(hass)
    before = entry_snapshot(entry)
    assert not await async_migrate_entry(hass, entry)
    assert entry_snapshot(entry) == before
