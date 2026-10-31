"""Home Assistant push updates for the local Spider controller."""

import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_PORT
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator

from .const import (
    CONF_ENABLE_CONTROL,
    CONF_GATEWAY_ID,
    CONF_SPIDER_ID,
    CONF_WAIT_FOR_WAKEUP,
    DEFAULT_ENABLE_CONTROL,
)
from .controller import SpiderController
from .protocol import SpiderState

_LOGGER = logging.getLogger(__name__)


class SpiderCoordinator(DataUpdateCoordinator[SpiderState]):
    def __init__(
        self, hass: HomeAssistant, entry: ConfigEntry, *, port=None, transport_factory=None
    ) -> None:
        super().__init__(hass, _LOGGER, config_entry=entry, name=entry.title)
        kwargs = {} if transport_factory is None else {"transport_factory": transport_factory}
        self.controller = SpiderController(
            port or entry.data[CONF_PORT],
            entry.data[CONF_GATEWAY_ID],
            entry.data[CONF_SPIDER_ID],
            enable_control=entry.options.get(CONF_ENABLE_CONTROL, DEFAULT_ENABLE_CONTROL),
            wait_for_wakeup=entry.options.get(CONF_WAIT_FOR_WAKEUP, False),
            on_update=self._updated,
            **kwargs,
        )
        self.data = self.controller.state

    def _updated(self) -> None:
        self.async_set_updated_data(self.controller.state)
