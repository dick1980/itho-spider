"""Configure a directly connected evofw3 gateway and one Itho Spider."""

from __future__ import annotations

import logging
import os
import re
from typing import Any

try:
    import probatio as vol
except ImportError:  # Home Assistant versions before the schema-library migration.
    import voluptuous as vol

from homeassistant.config_entries import (
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlowWithReload,
)
from homeassistant.const import CONF_NAME, CONF_PORT
from homeassistant.core import callback
from homeassistant.helpers import selector

from .const import (
    CONF_ENABLE_CONTROL,
    CONF_GATEWAY_ID,
    CONF_SPIDER_ID,
    CONF_WAIT_FOR_WAKEUP,
    DEFAULT_ENABLE_CONTROL,
    DEFAULT_NAME,
    DOMAIN,
)
from .controller import ControlError
from .pairing_flow import PairingFlowMixin, confirmation_schema
from .transport import async_probe_port, validate_port

_LOGGER = logging.getLogger(__name__)
_DEVICE_ID = re.compile(r"[0-9]{2}:[0-9]{6}\Z")


def _valid_device_id(value: str, device_type: str) -> bool:
    """Check the decimal RAMSES address and its 18-bit serial number."""
    return bool(
        _DEVICE_ID.fullmatch(value)
        and value.startswith(f"{device_type}:")
        and int(value[3:]) <= 0x3FFFF
    )


def _canonical_ports(ports: list[str]) -> list[str]:
    """Resolve USB aliases in an executor, without opening any device."""
    return [os.path.realpath(port) for port in ports]


def _user_schema() -> vol.Schema:
    """Return the setup form; the port belongs to the Home Assistant host."""
    return vol.Schema(
        {
            vol.Required(CONF_PORT): selector.TextSelector(),
            vol.Required(CONF_GATEWAY_ID): selector.TextSelector(),
            vol.Required(CONF_SPIDER_ID): selector.TextSelector(),
            vol.Required(CONF_NAME, default=DEFAULT_NAME): selector.TextSelector(),
            vol.Required(
                CONF_ENABLE_CONTROL, default=DEFAULT_ENABLE_CONTROL
            ): selector.BooleanSelector(),
            vol.Required(CONF_WAIT_FOR_WAKEUP, default=False): selector.BooleanSelector(),
        }
    )


class IthoSpiderConfigFlow(PairingFlowMixin, ConfigFlow, domain=DOMAIN):
    """Handle the setup of one gateway and one already paired Spider."""

    VERSION = 2

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> IthoSpiderOptionsFlow:
        """Create the options flow; Home Assistant supplies its config entry."""
        return IthoSpiderOptionsFlow()

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Validate local identity without transmitting any radio packet."""
        errors: dict[str, str] = {}
        placeholders: dict[str, str] = {}

        if user_input is not None:
            data = {
                key: user_input[key].strip()
                for key in (CONF_PORT, CONF_GATEWAY_ID, CONF_SPIDER_ID, CONF_NAME)
            }
            port = data[CONF_PORT]
            try:
                validate_port(port)
            except ValueError:
                errors[CONF_PORT] = "invalid_port"
            if not _valid_device_id(data[CONF_GATEWAY_ID], "18"):
                errors[CONF_GATEWAY_ID] = "invalid_gateway_id"
            if not _valid_device_id(data[CONF_SPIDER_ID], "21"):
                errors[CONF_SPIDER_ID] = "invalid_spider_id"
            if not data[CONF_NAME]:
                errors[CONF_NAME] = "invalid_name"

            if not errors:
                await self.async_set_unique_id(data[CONF_SPIDER_ID])
                self._abort_if_unique_id_configured()
                entries = self._async_current_entries()
                if any(entry.data.get(CONF_SPIDER_ID) == data[CONF_SPIDER_ID] for entry in entries):
                    return self.async_abort(reason="spider_already_configured")

                ports = [port, *(entry.data[CONF_PORT] for entry in entries)]
                resolved = await self.hass.async_add_executor_job(_canonical_ports, ports)
                if not resolved[0].startswith("/dev/"):
                    errors[CONF_PORT] = "invalid_port"
                elif any(
                    (resolved[0] == existing_port)
                    != (data[CONF_GATEWAY_ID] == entry.data[CONF_GATEWAY_ID])
                    for entry, existing_port in zip(entries, resolved[1:], strict=True)
                ):
                    return self.async_abort(reason="port_already_configured")
                else:
                    try:
                        if resolved[0] in resolved[1:]:
                            # Reuse the existing verified configuration. Setup acquires
                            # a shared, identity-checked connection; never probe an open port.
                            detected_id = data[CONF_GATEWAY_ID]
                        else:
                            detected_id = await async_probe_port(port)
                    except OSError, TimeoutError, ValueError:
                        errors["base"] = "cannot_connect"
                    except Exception:  # Do not hide programming failures from the log.
                        _LOGGER.exception("Unexpected error probing the evofw3 gateway")
                        errors["base"] = "unknown"
                    else:
                        if detected_id != data[CONF_GATEWAY_ID]:
                            errors[CONF_GATEWAY_ID] = "gateway_mismatch"
                            placeholders["detected_id"] = detected_id
                        else:
                            self._setup_data = data
                            self._setup_options = {
                                CONF_ENABLE_CONTROL: user_input.get(
                                    CONF_ENABLE_CONTROL, DEFAULT_ENABLE_CONTROL
                                ),
                                CONF_WAIT_FOR_WAKEUP: user_input.get(CONF_WAIT_FOR_WAKEUP, False),
                            }
                            return await self.async_step_association()

        return self.async_show_form(
            step_id="user",
            data_schema=self.add_suggested_values_to_schema(_user_schema(), user_input or {}),
            errors=errors,
            description_placeholders=placeholders,
        )

    def _pair_data(self):
        return self._setup_data

    async def async_step_association(self, user_input=None):
        return self.async_show_menu(
            step_id="association",
            menu_options=["pair_prepare", "save_later"],
            description_placeholders=self._pair_placeholders(),
        )

    async def async_step_save_later(self, user_input=None):
        """Already paired or receive-only: create the entry without radio pairing."""
        return self._finish_pairing()

    def _finish_pairing(self):
        self._abort_if_unique_id_configured()
        return self.async_create_entry(
            title=self._setup_data[CONF_NAME],
            data=self._setup_data,
            options=self._setup_options,
        )


class IthoSpiderOptionsFlow(PairingFlowMixin, OptionsFlowWithReload):
    """Configure whether the integration may control the paired thermostat."""

    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        return self.async_show_menu(
            step_id="init",
            menu_options=["settings", "pair_prepare", "remove"],
            description_placeholders=self._pair_placeholders(),
        )

    def _pair_data(self):
        return self.config_entry.data

    def _finish_pairing(self):
        # Unchanged options finish the wizard without reloading the live controller.
        return self.async_create_entry(title="", data=dict(self.config_entry.options))

    async def async_step_save_later(self, user_input=None):
        return self.async_abort(reason="pair_not_confirmed")

    async def async_step_settings(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Apply options through Home Assistant's automatic entry reload."""
        if user_input is not None:
            return self.async_create_entry(
                title="",
                data={**self.config_entry.options, **user_input},
            )

        return self.async_show_form(
            step_id="settings",
            data_schema=vol.Schema(
                {
                    vol.Required(
                        CONF_ENABLE_CONTROL,
                        default=self.config_entry.options.get(
                            CONF_ENABLE_CONTROL, DEFAULT_ENABLE_CONTROL
                        ),
                    ): selector.BooleanSelector(),
                    vol.Required(
                        CONF_WAIT_FOR_WAKEUP,
                        default=self.config_entry.options.get(CONF_WAIT_FOR_WAKEUP, False),
                    ): selector.BooleanSelector(),
                }
            ),
        )

    _removal_controller = None
    _removal_token = None
    _physical_unpair_confirmed = False

    async def async_step_remove(self, user_input=None):
        return self.async_show_menu(
            step_id="remove",
            menu_options=["remove_ha", "unpair_prepare"],
            description_placeholders=self._pair_placeholders(),
        )

    async def async_step_remove_ha(self, user_input=None):
        return await self._confirm_remove("remove_ha", user_input)

    async def async_step_unpair_prepare(self, user_input=None):
        errors = {}
        if user_input is not None:
            runtime = getattr(self.config_entry, "runtime_data", None)
            if runtime is None:
                errors["base"] = "not_loaded"
            else:
                try:
                    token = runtime.controller.prepare_removal()
                except ControlError:
                    errors["base"] = "operation_busy"
                else:
                    self._removal_controller = runtime.controller
                    self._removal_token = token
                    return await self.async_step_unpair_confirm()
        return self.async_show_form(
            step_id="unpair_prepare",
            data_schema=vol.Schema({}),
            errors=errors,
            description_placeholders=self._pair_placeholders(),
        )

    async def async_step_unpair_confirm(self, user_input=None):
        errors = {}
        if user_input is not None:
            if not self._removal_controller.removal_active(self._removal_token):
                self._end_removal()
                return self.async_abort(reason="removal_expired")
            if user_input.get("confirm") is True:
                self._physical_unpair_confirmed = True
                return await self.async_step_remove_confirm()
            errors["base"] = "confirmation_required"
        return self.async_show_form(
            step_id="unpair_confirm",
            data_schema=confirmation_schema(),
            errors=errors,
            description_placeholders=self._pair_placeholders(),
        )

    async def async_step_remove_confirm(self, user_input=None):
        return await self._confirm_remove("remove_confirm", user_input)

    async def _confirm_remove(self, step_id, user_input):
        errors = {}
        if step_id == "remove_confirm" and (
            not self._physical_unpair_confirmed
            or not self._removal_controller.removal_active(self._removal_token)
        ):
            self._end_removal()
            return self.async_abort(reason="removal_expired")
        if user_input is not None:
            if user_input.get("confirm") is True:
                result = await self.hass.config_entries.async_remove(self.handler)
                self._removal_controller = None
                self._removal_token = None
                return self.async_abort(
                    reason="removed_restart" if result["require_restart"] else "removed"
                )
            errors["base"] = "confirmation_required"
        return self.async_show_form(
            step_id=step_id,
            data_schema=confirmation_schema(),
            errors=errors,
            description_placeholders=self._pair_placeholders(),
        )

    def _end_removal(self):
        if self._removal_controller is not None:
            self._removal_controller.finish_removal(self._removal_token)
            self._removal_controller = None
            self._removal_token = None

    def async_remove(self):
        self._end_removal()
        super().async_remove()
