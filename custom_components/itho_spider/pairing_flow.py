"""Pairing wizard shared by initial setup and an existing Spider's options."""

from __future__ import annotations

import asyncio
import os

try:
    import probatio as vol
except ImportError:
    import voluptuous as vol

from homeassistant.const import CONF_NAME, CONF_PORT
from homeassistant.helpers import selector

from .const import CONF_GATEWAY_ID, CONF_SPIDER_ID, CONF_WAIT_FOR_WAKEUP
from .controller import ControlError, SpiderController
from .shared_gateway import DATA_GATEWAYS, get_gateway

PAIRING_TIMEOUT = 180


def confirmation_schema(key: str = "confirm") -> vol.Schema:
    return vol.Schema({vol.Required(key, default=False): selector.BooleanSelector()})


class PairingFlowMixin:
    """Own a bounded pairing window; never close an existing entry's USB client."""

    _pair_controller = None
    _pair_task = None
    _pair_token = None
    _owns_controller = False
    _pair_outcome = None

    def _pair_placeholders(self):
        data = self._pair_data()
        return {"name": data[CONF_NAME], "spider_id": data[CONF_SPIDER_ID]}

    async def _close_pair_controller(self):
        if self._owns_controller:
            controller = self._pair_controller
            self._owns_controller = False
            self._pair_controller = None
            await controller.async_close()

    async def _start_pair_controller(self):
        if hasattr(self, "_setup_data"):
            data = self._setup_data
            port = await self.hass.async_add_executor_job(os.path.realpath, data[CONF_PORT])
            gateway = get_gateway(
                self.hass.data.setdefault(DATA_GATEWAYS, {}), port, data[CONF_GATEWAY_ID]
            )
            self._pair_controller = SpiderController(
                port,
                data[CONF_GATEWAY_ID],
                data[CONF_SPIDER_ID],
                enable_control=True,
                wait_for_wakeup=self._setup_options.get(CONF_WAIT_FOR_WAKEUP, False),
                transport_factory=gateway.client_factory(data[CONF_SPIDER_ID]),
            )
            self._owns_controller = True
            await self._pair_controller.async_start()
        else:
            runtime = getattr(self.config_entry, "runtime_data", None)
            if runtime is None:
                raise ControlError("The integration is not loaded")
            self._pair_controller = runtime.controller

    async def async_step_pair_prepare(self, user_input=None):
        errors = {}
        if user_input is not None:
            try:
                await self._start_pair_controller()
                if self._pair_controller.diagnostics()["bound_status_seen"]:
                    self._pair_outcome = "already_paired"
                    await self._close_pair_controller()
                    return await self.async_step_pair_result()
                self._pair_token = self._pair_controller.arm_pairing()
            except ControlError, OSError, TimeoutError, ValueError:
                await self._close_pair_controller()
                errors["base"] = "pair_unavailable"
            else:
                self._pair_outcome = None
                self._pair_task = self.hass.async_create_background_task(
                    self._wait_for_pairing(), "itho_spider_pairing_wizard"
                )
                return await self.async_step_pair_wait()
        return self.async_show_form(
            step_id="pair_prepare",
            data_schema=vol.Schema({}),
            errors=errors,
            description_placeholders=self._pair_placeholders(),
        )

    async def _wait_for_pairing(self):
        controller = self._pair_controller
        try:
            async with asyncio.timeout(PAIRING_TIMEOUT):
                while controller.pairing_status in {
                    "waiting_for_offer",
                    "waiting_for_confirmation",
                }:
                    controller.pairing_event.clear()
                    await controller.pairing_event.wait()
                self._pair_outcome = controller.pairing_status
        except TimeoutError:
            self._pair_outcome = "timed_out"
        finally:
            controller.cancel_pairing(self._pair_token)
            await self._close_pair_controller()

    async def async_step_pair_wait(self, user_input=None):
        if self._pair_task.done():
            self._pair_task.result()
            return self.async_show_progress_done(next_step_id="pair_result")
        return self.async_show_progress(
            step_id="pair_wait",
            progress_action="pairing",
            progress_task=self._pair_task,
            description_placeholders=self._pair_placeholders(),
        )

    async def async_step_pair_result(self, user_input=None):
        if self._pair_outcome not in {"confirmed", "already_paired"}:
            return await self.async_step_pair_failed()
        errors = {}
        if user_input is not None:
            if user_input.get("confirm") is True:
                return self._finish_pairing()
            errors["base"] = "confirmation_required"
        return self.async_show_form(
            step_id="pair_result",
            data_schema=confirmation_schema(),
            errors=errors,
            description_placeholders=self._pair_placeholders(),
        )

    async def async_step_pair_failed(self, user_input=None):
        return self.async_show_menu(
            step_id="pair_failed",
            menu_options=["pair_prepare", "save_later"],
            description_placeholders=self._pair_placeholders(),
        )

    def async_remove(self):
        if self._pair_controller is not None and self._pair_token is not None:
            self._pair_controller.cancel_pairing(self._pair_token)
        if self._pair_task is not None and not self._pair_task.done():
            self._pair_task.cancel()
        if self._owns_controller:
            self.hass.async_create_task(self._close_pair_controller())
        super().async_remove()
