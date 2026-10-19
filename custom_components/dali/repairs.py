"""Repairs for the Tridonic DALI integration."""

import asyncio

from dali.exceptions import ProgramShortAddressFailure
import probatio

from homeassistant.components.repairs import RepairsFlow, RepairsFlowResult
from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant

from . import DaliConfigEntry
from .const import (
    CONF_BUS_POWER,
    ISSUE_ADDRESS_COLLISION,
    ISSUE_BUS_VOLTAGE_ERROR,
    ISSUE_UNADDRESSED_CONTROLDEVICE,
)


class AssignShortAddressesRepairFlow(RepairsFlow):
    """Assign short addresses to unaddressed DALI control gear or devices."""

    def __init__(
        self, entry: DaliConfigEntry, *, address_control_devices: bool
    ) -> None:
        """Initialize the flow."""
        self._entry = entry
        self._address_control_devices = address_control_devices
        self._task: asyncio.Task[bool] | None = None
        self._abort_reason: str | None = None

    async def async_step_init(
        self, user_input: dict[str, str] | None = None
    ) -> RepairsFlowResult:
        """Handle the first step of the fix flow."""
        return await self.async_step_confirm()

    async def async_step_confirm(
        self, user_input: dict[str, str] | None = None
    ) -> RepairsFlowResult:
        """Ask the user to confirm addressing."""
        if self._entry.state is not ConfigEntryState.LOADED:
            return self.async_abort(reason="not_loaded")
        if user_input is not None:
            return await self.async_step_assign()
        return self.async_show_form(
            step_id="confirm",
            data_schema=probatio.Schema({}),
            description_placeholders={"title": self._entry.title},
        )

    async def async_step_assign(
        self, user_input: dict[str, str] | None = None
    ) -> RepairsFlowResult:
        """Run the commissioning sequence."""
        if self._task is None:
            coordinator = self._entry.runtime_data
            assign = (
                coordinator.async_assign_control_device_short_addresses
                if self._address_control_devices
                else coordinator.async_assign_gear_short_addresses
            )
            self._task = self.hass.async_create_task(assign())
        if not self._task.done():
            return self.async_show_progress(
                step_id="assign",
                progress_action="assign",
                progress_task=self._task,
            )
        try:
            if self._task.result():
                self._abort_reason = "unaddressed_remaining"
        except OSError, TimeoutError:
            self._abort_reason = "cannot_connect"
        except ProgramShortAddressFailure:
            self._abort_reason = "program_failed"
        return self.async_show_progress_done(next_step_id="finish")

    async def async_step_finish(
        self, user_input: dict[str, str] | None = None
    ) -> RepairsFlowResult:
        """Finish the fix flow."""
        if self._abort_reason:
            return self.async_abort(reason=self._abort_reason)
        return self.async_create_entry(data={})


class ResolveAddressCollisionRepairFlow(RepairsFlow):
    """Re-address DALI control gear that shares a short address."""

    def __init__(self, entry: DaliConfigEntry) -> None:
        """Initialize the flow."""
        self._entry = entry
        self._task: asyncio.Task[bool] | None = None
        self._abort_reason: str | None = None

    async def async_step_init(
        self, user_input: dict[str, str] | None = None
    ) -> RepairsFlowResult:
        """Handle the first step of the fix flow."""
        return await self.async_step_confirm()

    async def async_step_confirm(
        self, user_input: dict[str, str] | None = None
    ) -> RepairsFlowResult:
        """Ask the user to confirm re-addressing."""
        if self._entry.state is not ConfigEntryState.LOADED:
            return self.async_abort(reason="not_loaded")
        if user_input is not None:
            return await self.async_step_resolve()
        return self.async_show_form(
            step_id="confirm",
            data_schema=probatio.Schema({}),
            description_placeholders={"title": self._entry.title},
        )

    async def async_step_resolve(
        self, user_input: dict[str, str] | None = None
    ) -> RepairsFlowResult:
        """Run the collision-resolution sequence."""
        if self._task is None:
            coordinator = self._entry.runtime_data
            self._task = self.hass.async_create_task(
                coordinator.async_resolve_address_collisions()
            )
        if not self._task.done():
            return self.async_show_progress(
                step_id="resolve",
                progress_action="resolve",
                progress_task=self._task,
            )
        try:
            if self._task.result():
                self._abort_reason = "collision_remaining"
        except OSError, TimeoutError:
            self._abort_reason = "cannot_connect"
        except ProgramShortAddressFailure:
            self._abort_reason = "program_failed"
        return self.async_show_progress_done(next_step_id="finish")

    async def async_step_finish(
        self, user_input: dict[str, str] | None = None
    ) -> RepairsFlowResult:
        """Finish the fix flow."""
        if self._abort_reason:
            return self.async_abort(reason=self._abort_reason)
        return self.async_create_entry(data={})


class EnableBusPowerRepairFlow(RepairsFlow):
    """Switch on the interface's integrated bus power supply."""

    def __init__(self, entry: DaliConfigEntry) -> None:
        """Initialize the flow."""
        self._entry = entry

    async def async_step_init(
        self, user_input: dict[str, str] | None = None
    ) -> RepairsFlowResult:
        """Handle the first step of the fix flow."""
        return await self.async_step_confirm()

    async def async_step_confirm(
        self, user_input: dict[str, str] | None = None
    ) -> RepairsFlowResult:
        """Ask the user to confirm enabling bus power, then reload."""
        if user_input is not None:
            self.hass.config_entries.async_update_entry(
                self._entry,
                data={**self._entry.data, CONF_BUS_POWER: True},
            )
            await self.hass.config_entries.async_reload(self._entry.entry_id)
            return self.async_create_entry(data={})
        return self.async_show_form(
            step_id="confirm",
            data_schema=probatio.Schema({}),
            description_placeholders={"title": self._entry.title},
        )


async def async_create_fix_flow(
    hass: HomeAssistant,
    issue_id: str,
    data: dict[str, str | int | float | None] | None,
) -> RepairsFlow:
    """Create the fix flow for a DALI repair issue."""
    assert data is not None
    entry_id = data["entry_id"]
    assert isinstance(entry_id, str)
    entry = hass.config_entries.async_get_entry(entry_id)
    assert entry is not None
    if issue_id.startswith(ISSUE_BUS_VOLTAGE_ERROR):
        return EnableBusPowerRepairFlow(entry)
    if issue_id.startswith(ISSUE_ADDRESS_COLLISION):
        return ResolveAddressCollisionRepairFlow(entry)
    address_control_devices = issue_id.startswith(ISSUE_UNADDRESSED_CONTROLDEVICE)
    return AssignShortAddressesRepairFlow(
        entry, address_control_devices=address_control_devices
    )
