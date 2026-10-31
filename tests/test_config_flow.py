"""Exercise the real Home Assistant flow manager with a mocked USB probe."""

from collections.abc import Generator
from unittest.mock import AsyncMock, patch

import pytest
from homeassistant.config_entries import SOURCE_USER
from homeassistant.const import CONF_NAME, CONF_PORT
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.itho_spider.const import (
    CONF_ENABLE_CONTROL,
    CONF_GATEWAY_ID,
    CONF_SPIDER_ID,
    CONF_WAIT_FOR_WAKEUP,
    DOMAIN,
)

GATEWAY = "18:123456"
SPIDER = "21:123456"

pytestmark = pytest.mark.asyncio

USER_INPUT = {
    CONF_PORT: "/dev/ttyACM0",
    CONF_GATEWAY_ID: GATEWAY,
    CONF_SPIDER_ID: SPIDER,
    CONF_NAME: "Test room A",
    CONF_ENABLE_CONTROL: True,
}
ENTRY_DATA = {key: value for key, value in USER_INPUT.items() if key != CONF_ENABLE_CONTROL}


@pytest.fixture(autouse=True)
def mock_probe(enable_custom_integrations: None) -> Generator[AsyncMock]:
    """Ensure no test can open a USB port or start the real coordinator."""
    with (
        patch(
            "custom_components.itho_spider.config_flow.async_probe_port",
            return_value=GATEWAY,
        ) as probe,
        patch("custom_components.itho_spider.async_setup_entry", return_value=True),
    ):
        yield probe


async def finish_add(hass, result):
    if result["type"] is FlowResultType.MENU and result["step_id"] == "association":
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {"next_step_id": "save_later"}
        )
    return result


async def test_create_entry(hass: HomeAssistant, mock_probe: AsyncMock) -> None:
    """Identity verification creates an entry with control kept in options."""
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": SOURCE_USER})
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "user"
    mock_probe.assert_not_awaited()

    result = await hass.config_entries.flow.async_configure(result["flow_id"], USER_INPUT)
    result = await finish_add(hass, result)
    await hass.async_block_till_done()

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "Test room A"
    assert result["data"] == ENTRY_DATA
    assert result["result"].unique_id == SPIDER
    assert result["result"].options == {CONF_ENABLE_CONTROL: True, CONF_WAIT_FOR_WAKEUP: False}
    mock_probe.assert_awaited_once_with("/dev/ttyACM0")


async def test_create_read_only_entry(hass: HomeAssistant, mock_probe: AsyncMock) -> None:
    """The initial form can explicitly disable thermostat control."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={"source": SOURCE_USER},
        data={**USER_INPUT, CONF_ENABLE_CONTROL: False},
    )
    result = await finish_add(hass, result)
    await hass.async_block_till_done()
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["result"].options == {CONF_ENABLE_CONTROL: False, CONF_WAIT_FOR_WAKEUP: False}
    mock_probe.assert_awaited_once()


@pytest.mark.parametrize(
    ("field", "value", "error"),
    [
        (CONF_PORT, "socket://localhost:1234", "invalid_port"),
        (CONF_PORT, "/dev/../tmp/file", "invalid_port"),
        (CONF_PORT, "/dev/tty\x00ACM0", "invalid_port"),
        (CONF_GATEWAY_ID, "21:123456", "invalid_gateway_id"),
        (CONF_GATEWAY_ID, "18:262144", "invalid_gateway_id"),
        (CONF_SPIDER_ID, "21:999999", "invalid_spider_id"),
        (CONF_SPIDER_ID, "18:123456", "invalid_spider_id"),
        (CONF_NAME, " ", "invalid_name"),
    ],
)
async def test_invalid_input_never_opens_port(
    hass: HomeAssistant,
    mock_probe: AsyncMock,
    field: str,
    value: str,
    error: str,
) -> None:
    """Reject malformed or non-local addresses before any serial access."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={"source": SOURCE_USER},
        data={**USER_INPUT, field: value},
    )
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {field: error}
    mock_probe.assert_not_awaited()


@pytest.mark.parametrize("exception", [OSError, TimeoutError, ValueError])
async def test_unavailable_gateway_can_be_retried(
    hass: HomeAssistant, mock_probe: AsyncMock, exception: type[Exception]
) -> None:
    """A failed probe keeps the form open and permits correction or retry."""
    mock_probe.side_effect = exception("test connection failure")
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}, data=USER_INPUT
    )
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "cannot_connect"}

    mock_probe.side_effect = None
    result = await hass.config_entries.flow.async_configure(result["flow_id"], USER_INPUT)
    result = await finish_add(hass, result)
    await hass.async_block_till_done()
    assert result["type"] is FlowResultType.CREATE_ENTRY


async def test_wrong_gateway_is_not_accepted(hass: HomeAssistant, mock_probe: AsyncMock) -> None:
    """Opening a different gateway cannot silently change its configured ID."""
    mock_probe.return_value = "18:000001"
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}, data=USER_INPUT
    )
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {CONF_GATEWAY_ID: "gateway_mismatch"}
    assert result["description_placeholders"] == {"detected_id": "18:000001"}
    assert not hass.config_entries.async_entries(DOMAIN)


@pytest.mark.parametrize(
    ("existing_data", "unique_id", "reason"),
    [
        (ENTRY_DATA, GATEWAY, "spider_already_configured"),
        (
            {**ENTRY_DATA, CONF_GATEWAY_ID: "18:000001", CONF_PORT: "/dev/ttyACM1"},
            "18:000001",
            "spider_already_configured",
        ),
        (
            {**ENTRY_DATA, CONF_GATEWAY_ID: "18:000001", CONF_SPIDER_ID: "21:000001"},
            "18:000001",
            "port_already_configured",
        ),
    ],
)
async def test_duplicates_are_rejected_before_probe(
    hass: HomeAssistant,
    mock_probe: AsyncMock,
    existing_data: dict,
    unique_id: str,
    reason: str,
) -> None:
    """Do not disrupt a gateway that is already owned by an existing entry."""
    MockConfigEntry(domain=DOMAIN, unique_id=unique_id, data=existing_data).add_to_hass(hass)
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}, data=USER_INPUT
    )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == reason
    mock_probe.assert_not_awaited()


async def test_usb_alias_is_also_a_duplicate(hass: HomeAssistant, mock_probe: AsyncMock) -> None:
    """A by-id alias must not create a second owner for an existing port."""
    MockConfigEntry(
        domain=DOMAIN,
        unique_id="18:000001",
        data={
            **ENTRY_DATA,
            CONF_GATEWAY_ID: "18:000001",
            CONF_SPIDER_ID: "21:000001",
        },
    ).add_to_hass(hass)
    with patch(
        "custom_components.itho_spider.config_flow._canonical_ports",
        return_value=["/dev/ttyACM0", "/dev/ttyACM0"],
    ):
        result = await hass.config_entries.flow.async_init(
            DOMAIN,
            context={"source": SOURCE_USER},
            data={**USER_INPUT, CONF_PORT: "/dev/serial/by-id/evofw3"},
        )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "port_already_configured"
    mock_probe.assert_not_awaited()


async def test_options_change_control_without_probe(
    hass: HomeAssistant, mock_probe: AsyncMock
) -> None:
    """Options save independently of hardware and use HA's reload mechanism."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id=GATEWAY,
        data=ENTRY_DATA,
        options={CONF_ENABLE_CONTROL: True},
    )
    entry.add_to_hass(hass)
    result = await hass.config_entries.options.async_init(entry.entry_id)
    assert result["type"] is FlowResultType.MENU
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"next_step_id": "settings"}
    )
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "settings"

    with patch.object(hass.config_entries, "async_reload", return_value=True) as reload:
        result = await hass.config_entries.options.async_configure(
            result["flow_id"], {CONF_ENABLE_CONTROL: False}
        )
        await hass.async_block_till_done()
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert entry.options == {CONF_ENABLE_CONTROL: False, CONF_WAIT_FOR_WAKEUP: False}
    reload.assert_awaited_once_with(entry.entry_id)
    mock_probe.assert_not_awaited()


async def test_second_spider_reuses_existing_gateway_without_probe(hass, mock_probe):
    MockConfigEntry(
        domain=DOMAIN, version=2, unique_id=SPIDER, data=ENTRY_DATA
    ).add_to_hass(hass)
    result = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={"source": SOURCE_USER},
        data={**USER_INPUT, CONF_SPIDER_ID: "21:123457", CONF_NAME: "Test room B"},
    )
    result = await finish_add(hass, result)
    await hass.async_block_till_done()
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["result"].unique_id == "21:123457"
    mock_probe.assert_not_awaited()


@pytest.mark.parametrize("battery_wait", [False, True])
async def test_040_options_form_keeps_battery_and_unknown_options(hass, mock_probe, battery_wait):
    """Saving a different setting must not reset an existing power-source choice."""
    entry = MockConfigEntry(
        domain=DOMAIN, version=2, unique_id=SPIDER, data=ENTRY_DATA,
        options={CONF_ENABLE_CONTROL: True, CONF_WAIT_FOR_WAKEUP: battery_wait,
                 "reserved_user_option": "keep-me"},
    )
    entry.add_to_hass(hass)
    result = await hass.config_entries.options.async_init(entry.entry_id)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"next_step_id": "settings"}
    )
    # Submission omits the wakeup field; HA uses the existing form default.
    with patch.object(hass.config_entries, "async_reload", return_value=True):
        await hass.config_entries.options.async_configure(
            result["flow_id"], {CONF_ENABLE_CONTROL: False}
        )
        await hass.async_block_till_done()
    assert entry.options == {CONF_ENABLE_CONTROL: False, CONF_WAIT_FOR_WAKEUP: battery_wait,
                             "reserved_user_option": "keep-me"}
    mock_probe.assert_not_awaited()
