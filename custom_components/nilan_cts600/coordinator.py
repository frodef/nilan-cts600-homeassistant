import logging, os, asyncio, async_timeout
from datetime import timedelta

from homeassistant.helpers.update_coordinator import (
    CoordinatorEntity,
    DataUpdateCoordinator,
)
from homeassistant.components.climate.const import (
    HVACMode,
    HVACAction,
    ClimateEntityFeature
)
from homeassistant.helpers.event import async_track_state_change
from homeassistant.const import (
    UnitOfTemperature,
    ATTR_UNIT_OF_MEASUREMENT,
)
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.util.unit_conversion import TemperatureConverter
from homeassistant.exceptions import PlatformNotReady

from .const import DOMAIN, DATA_KEY
from .nilan_cts600 import CTS600, NilanCTS600ProtocolError, nilanString, findUSB

_LOGGER = logging.getLogger(__name__)

if os.uname()[1] == 'x390':
    # development mockup device
    _LOGGER.warning ('%s Mockup device mode.', __name__)
    from .nilan_cts600 import CTS600Mockup as CTS600

_initLock = asyncio.Lock()

async def getCoordinator (hass, config):
    async with _initLock:
        if DATA_KEY not in hass.data:
            hass.data[DATA_KEY] = {}
        port = config.get ('port')
        if port == 'auto':
            port =  findUSB ()
        if port in hass.data[DATA_KEY]:
            return hass.data[DATA_KEY][port]

        _LOGGER.debug ("Creating new coordinator for %s.", port)
        coordinator= CTS600Coordinator (hass, port, config)
        try:
            await coordinator.initialize ()
        except Exception as e:
            _LOGGER.error ("Device init failed for %s: %s", port, e)
            raise PlatformNotReady
        hass.data[DATA_KEY][port] = coordinator
        _LOGGER.debug ("Created new coordinator done for %s.", port)
        return coordinator


class CTS600Coordinator(DataUpdateCoordinator):
    """Coordinated access to the CTS600.

    The main function of this class is to provide an async interface
    to the non-async code in nilan_cts600.py, so as to properly
    integrate with the HA eventloop.

    """

    def __init__ (self, hass, port, config): # port, name, retries=1, sensor_entity_id=None):
        """Initialize my coordinator."""

        if not port:
            raise PlatformNotReady
        try:
            cts600 = CTS600 (port=port, logger=_LOGGER.debug)
            cts600.connect ()
        except Exception as e:
            _LOGGER.error ("Device connect failed for %s: %s", port, e)
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
            raise Exception ("No HASS object!")
        
        self.retries = int(config.get ('retries', 2))
        sensor_entity_id = config.get ('sensor_T15')
            
        self.cts600 = cts600
        self._lock = asyncio.Lock()
        self._t15_fallback = None
        self._updateDataCounter = 100
        
        if sensor_entity_id:
            sensor_state = hass.states.get(sensor_entity_id)
            if sensor_state:
                self.hass.loop.create_task (self._update_T15_state (sensor_entity_id, None, sensor_state))
            async_track_state_change(hass, sensor_entity_id, self._update_T15_state)
        else:
            self._t15_fallback = 21


    async def _async_update_data(self):
        """Fetch data from API endpoint.

        This is the place to pre-process the data to lookup tables
        so entities can quickly look up their data.
        """
        async with async_timeout.timeout(15):
            if self._t15_fallback:
                await self.setT15 (self._t15_fallback)
                self._t15_fallback = None
            updateShowData = False
            self._updateDataCounter += 1
            if self._updateDataCounter >= 10:
                updateShowData = True
                self._updateDataCounter = 0
            return await self.updateData(updateShowData=updateShowData)

    async def _update_T15_state (self, entity_id, old_state, new_state):
        """ Update thermostat with latest (room) temperature from sensor."""
        if new_state.state is None or new_state.state in ["unknown", "unavailable"]:
            return
        if not self.hass:
            return

        sensor_unit = new_state.attributes.get(ATTR_UNIT_OF_MEASUREMENT) or UnitOfTemperature.CELSIUS
        value = TemperatureConverter.convert(
            float(new_state.state), sensor_unit, UnitOfTemperature.CELSIUS
        )
        await self.setT15 (value)

        
    async def _call (self, method, *args):
        """Make a synchronous call to CTS600 by creating a job and
        then await that job. Use self._lock to serialize access to the
        underlying API. Also implement self.retries."""
        async with self._lock:
            for attempt in range(1, self.retries+1):
                _LOGGER.debug ("Call try %d: %s %s", attempt, method.__func__.__name__, args)
                try:
                    result = await self.hass.async_add_executor_job (method, *args)
                    break
                except (TimeoutError, NilanCTS600ProtocolError) as e:
                    _LOGGER.debug ("Exception %s: %s %s", e.__class__.__name__, method.__func__.__name__, args)
                    if not attempt<self.retries:
                        raise e
            _LOGGER.debug ("Call result: %s %s => %s", method.__func__.__name__, args, result)
            return result

    async def initialize (self):
        await self._call (self.cts600.initialize)
        await self._call (self.cts600.setLanguage, "ENGLISH")
        slaveID = self.cts600.slaveID()
        product = nilanString(slaveID['product'])
        self.device_info = DeviceInfo(
            identifiers={
                # Serial numbers are unique identifiers within a specific domain
                (DOMAIN, self.cts600.port)
            },
            manufacturer="Nilan",
            model=product,
            sw_version=f"sw={slaveID['softwareVersion']},protocol={slaveID['protocolVersion']}",
        )
        _LOGGER.debug ("SlaveID: %s", self.cts600.slaveID())

    def key (self, key=0):
        return self._call (self.cts600.key, key)

    def key_on (self):
        return self._call (self.cts600.key_on)

    def key_off (self):
        return self._call (self.cts600.key_off)
    
    def updateData (self, updateShowData=True):
        return self._call (self.cts600.updateData, updateShowData)

    def setT15 (self, celcius):
        return self._call (self.cts600.setT15, celcius)

    def setFlow (self, flow):
        return self._call (self.cts600.setFlow, flow)

    def setThermostat (self, celsius):
        return self._call (self.cts600.setThermostat, celsius)

    def resetMenu (self):
        return self._call (self.cts600.resetMenu)

    def setMode (self, mode):
        return self._call (self.cts600.setMode, mode)
