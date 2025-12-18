import asyncio
from datetime import timedelta
import logging
import os
import time

import async_timeout

from homeassistant.components.climate.const import (
    ClimateEntityFeature,
    HVACAction,
    HVACMode,
)
from homeassistant.const import ATTR_UNIT_OF_MEASUREMENT, UnitOfTemperature
from homeassistant.core import Event, EventStateChangedData, callback
from homeassistant.exceptions import PlatformNotReady
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.event import async_track_state_change_event
from homeassistant.helpers.update_coordinator import (
    CoordinatorEntity,
    DataUpdateCoordinator,
    UpdateFailed,
)
from homeassistant.util.unit_conversion import TemperatureConverter

from .const import DATA_KEY, DOMAIN, CONNECTION_TYPE_TCP
from .nilan_cts600 import (
    CTS600,
    Key,
    NilanCTS600Exception,
    NilanCTS600ProtocolError,
    findUSB,
    nilanString,
)

try:
    from pymodbus.exceptions import ConnectionException as ModbusConnectionException
except ImportError:
    ModbusConnectionException = OSError  # Fallback

_LOGGER = logging.getLogger(__name__)

if os.uname()[1] == "x390":
    # development mockup device
    _LOGGER.warning("%s Mockup device mode.", __name__)
    from .nilan_cts600 import CTS600Mockup as CTS600

_initLock = asyncio.Lock()


async def getCoordinator(hass, config):
    async with _initLock:
        if DATA_KEY not in hass.data:
            hass.data[DATA_KEY] = {}
        
        connection_type = config.get("connection_type", CONNECTION_TYPE_TCP)
        
        # Determine the unique key for this connection
        if connection_type == CONNECTION_TYPE_TCP:
            host = config.get("host")
            tcp_port = config.get("tcp_port", 502)
            connection_key = f"tcp://{host}:{tcp_port}"
        else:
            port = config.get("port")
            if port == "auto":
                port = findUSB()
            connection_key = port
        
        if connection_key in hass.data[DATA_KEY]:
            return hass.data[DATA_KEY][connection_key]

        _LOGGER.debug("Creating new coordinator for %s.", connection_key)
        coordinator = CTS600Coordinator(hass, config)
        try:
            await coordinator.initialize()
        except Exception as e:
            _LOGGER.error("Device init failed for %s: %s", connection_key, e)
            raise PlatformNotReady
        hass.data[DATA_KEY][connection_key] = coordinator
        _LOGGER.debug("Created new coordinator done for %s.", connection_key)
        return coordinator


class CTS600Coordinator(DataUpdateCoordinator):
    """Coordinated access to the CTS600.

    The main function of this class is to provide an async interface
    to the non-async code in nilan_cts600.py, so as to properly
    integrate with the HA eventloop.

    """

    def __init__(
        self, hass, config
    ):  # port, name, retries=1, sensor_entity_id=None):
        """Initialize my coordinator."""

        connection_type = config.get("connection_type", CONNECTION_TYPE_TCP)
        
        try:
            if connection_type == CONNECTION_TYPE_TCP:
                host = config.get("host")
                tcp_port = int(config.get("tcp_port", 502))
                cts600 = CTS600(host=host, tcp_port=tcp_port, logger=_LOGGER.debug)
                self._connection_info = f"tcp://{host}:{tcp_port}"
            else:
                port = config.get("port")
                if port == "auto":
                    port = findUSB()
                cts600 = CTS600(port=port, logger=_LOGGER.debug)
                self._connection_info = port
            cts600.connect()
        except Exception as e:
            _LOGGER.error("Device connect failed for %s: %s", config, e)
            raise PlatformNotReady

        super().__init__(
            hass,
            _LOGGER,
            # Name of the data. For logging purposes.
            name=config.get("name", "Nilan CTS600"),
            # Polling interval. Will only be polled if there are subscribers.
            update_interval=timedelta(seconds=5),
        )

        if not hass:
            raise Exception("No HASS object!")

        self.retries = int(config.get("retries", 2))
        sensor_entity_id = config.get("sensor_T15")

        self.cts600 = cts600
        self._lock = asyncio.Lock()
        self._t15_fallback = None
        self._updateDataCounter = 100
        self._manual_activity_ts = 0

        if sensor_entity_id:
            # sensor_state = hass.states.get(sensor_entity_id)
            # if sensor_state:
            #     self.hass.loop.create_task (self._update_T15_state (sensor_entity_id, None, sensor_state))
            async_track_state_change_event(
                hass, sensor_entity_id, self._update_T15_state
            )
        else:
            self._t15_fallback = 21

    def register_manual_activity(self):
        self._manual_activity_ts = time.time_ns() // 1000_000_000

    def manual_mode(self):
        return 30 > (time.time_ns() // 1000_000_000 - self._manual_activity_ts)

    def request_refresh(self):
        self._updateDataCounter = 100
        self.async_set_updated_data(self.data)

    async def _async_update_data(self):
        """Fetch data from API endpoint.

        This is the place to pre-process the data to lookup tables
        so entities can quickly look up their data.
        """
        try:
            if self.manual_mode():
                # Do nothing, just update display
                await self.key(Key.NONE)
                self.cts600.updateDisplay()
            else:
                async with async_timeout.timeout(15):
                    if self._t15_fallback:
                        await self.setT15(self._t15_fallback)
                        self._t15_fallback = None
                    updateShowData = False
                    self._updateDataCounter += 1
                    if self._updateDataCounter >= 10:
                        updateShowData = True
                        self._updateDataCounter = 0
                    return await self.updateData(updateShowData=updateShowData)
        except (
            TimeoutError,
            OSError,
            ModbusConnectionException,
            NilanCTS600Exception,
            NilanCTS600ProtocolError,
        ) as err:
            # Try to reconnect on connection errors
            _LOGGER.warning("Connection error, attempting reconnect: %s", err)
            try:
                await self.hass.async_add_executor_job(self.cts600.reconnect)
                _LOGGER.info("Reconnect successful")
            except (
                TimeoutError,
                OSError,
                ModbusConnectionException,
                NilanCTS600Exception,
            ) as reconnect_err:
                raise UpdateFailed(
                    f"Connection failed and reconnect unsuccessful: {reconnect_err}"
                ) from reconnect_err
            raise UpdateFailed(f"Update failed: {err}") from err
        return None

    async def _update_T15_state(self, event: Event[EventStateChangedData]) -> None:
        """Update thermostat with latest (room) temperature from sensor."""
        new_state = event.data["new_state"]

        if new_state.state is None or new_state.state in ["unknown", "unavailable"]:
            return
        if not self.hass:
            return

        sensor_unit = (
            new_state.attributes.get(ATTR_UNIT_OF_MEASUREMENT)
            or UnitOfTemperature.CELSIUS
        )
        value = TemperatureConverter.convert(
            float(new_state.state), sensor_unit, UnitOfTemperature.CELSIUS
        )
        await self.setT15(value)

    async def _call(self, method, *args):
        """Make a synchronous call to CTS600.

        Creates an executor job and awaits it. Uses self._lock to serialize
        access to the underlying API. Implements retry logic and automatic
        reconnection on connection failures.
        """
        async with self._lock:
            for attempt in range(1, self.retries + 1):
                _LOGGER.debug(
                    "Call try %d: %s %s", attempt, method.__func__.__name__, args
                )
                try:
                    result = await self.hass.async_add_executor_job(method, *args)
                    break
                except (TimeoutError, NilanCTS600ProtocolError) as e:
                    _LOGGER.debug(
                        "Exception %s: %s %s",
                        e.__class__.__name__,
                        method.__func__.__name__,
                        args,
                    )
                    if not attempt < self.retries:
                        raise
                except (OSError, ModbusConnectionException) as e:
                    # Connection error (e.g., broken pipe, connection reset)
                    _LOGGER.warning(
                        "Connection error in %s: %s, attempting reconnect",
                        method.__func__.__name__,
                        e,
                    )
                    try:
                        await self.hass.async_add_executor_job(self.cts600.reconnect)
                        _LOGGER.info("Reconnect successful, retrying operation")
                        # Retry the operation after reconnect
                        result = await self.hass.async_add_executor_job(method, *args)
                        break
                    except (
                        TimeoutError,
                        OSError,
                        ModbusConnectionException,
                        NilanCTS600Exception,
                    ) as reconnect_err:
                        _LOGGER.error("Reconnect failed: %s", reconnect_err)
                        raise reconnect_err from e
            _LOGGER.debug(
                "Call result: %s %s => %s", method.__func__.__name__, args, result
            )
            return result

    async def initialize(self):
        await self._call(self.cts600.initialize)
        await self._call(self.cts600.setLanguage, "ENGLISH")
        slaveID = self.cts600.slaveID()
        product = nilanString(slaveID["product"])
        self.device_info = DeviceInfo(
            identifiers={
                # Use connection info as unique identifier
                (DOMAIN, self._connection_info)
            },
            name=self.name,  # Use the name from ConfigEntry
            manufacturer="Nilan",
            model=product,
            sw_version=f"sw={slaveID['softwareVersion']},protocol={slaveID['protocolVersion']}",
        )
        _LOGGER.debug("SlaveID: %s", self.cts600.slaveID())

    def key(self, key=Key.NONE):
        return self._call(self.cts600.key, key)

    def key_on(self):
        return self._call(self.cts600.key_on)

    def key_off(self):
        return self._call(self.cts600.key_off)

    def updateData(self, updateShowData=True):
        return self._call(self.cts600.updateData, updateShowData)

    def setT15(self, celcius):
        return self._call(self.cts600.setT15, celcius)

    async def setFlow(self, flow):
        await self._call(self.cts600.setFlow, flow)
        self.request_refresh()

    async def setThermostat(self, celsius):
        await self._call(self.cts600.setThermostat, celsius)
        self.request_refresh()

    def resetMenu(self):
        return self._call(self.cts600.resetMenu)

    async def setMode(self, mode):
        await self._call(self.cts600.setMode, mode)
        self.request_refresh()
