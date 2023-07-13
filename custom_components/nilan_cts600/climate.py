
import logging, asyncio

from homeassistant.helpers.typing import ConfigType, DiscoveryInfoType
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.core import HomeAssistant, callback
from homeassistant.const import (
    UnitOfTemperature,
    ATTR_UNIT_OF_MEASUREMENT,
)

from homeassistant.helpers.event import async_track_state_change
from homeassistant.exceptions import PlatformNotReady
from homeassistant.components.climate import PLATFORM_SCHEMA, ClimateEntity
from homeassistant.util.unit_conversion import TemperatureConverter
import homeassistant.helpers.config_validation as cv
import voluptuous as vol

from homeassistant.components.climate.const import (
    HVACMode,
    HVACAction,
    ClimateEntityFeature
)

from .const import DOMAIN
from .nilan_cts600 import CTS600, NilanCTS600ProtocolError, findUSB

_LOGGER = logging.getLogger(__name__)

DATA_KEY = "climate." + DOMAIN

PLATFORM_SCHEMA = PLATFORM_SCHEMA.extend(
    {
        # vol.Required(CONF_HOST): cv.string,
        # vol.Required(CONF_TOKEN): vol.All(cv.string, vol.Length(min=32, max=32)),
        # vol.Required(CONF_SENSOR): cv.entity_id,
        vol.Optional("name", default="CTS600"): cv.string,
        vol.Optional("retries", default=2): vol.Coerce(int),
        vol.Optional("port"): vol.Coerce(str),
        vol.Optional("sensor"): cv.entity_id,
    }
)

async def async_setup_platform(
        hass: HomeAssistant,
        config: ConfigType,
        async_add_entities: AddEntitiesCallback,
        discovery_info: DiscoveryInfoType | None = None,
) -> None:
    """Set up the platform."""
    from .nilan_cts600 import CTS600, NilanCTS600ProtocolError, findUSB
    if DATA_KEY not in hass.data:
        hass.data[DATA_KEY] = {}

    _LOGGER.debug ("setup_platform: %s // %s", config, discovery_info)
    port = config.get ('port') or findUSB ()
    retries = config.get ('retries')
    if not port:
        raise PlatformNotReady
    try:
        cts600 = CTS600 (port=port, logger=_LOGGER.debug)
        cts600.connect ()
    except Exception as e:
        _LOGGER.error ("Device connect failed for %s: %s", port, e)
        raise PlatformNotReady

    device = HaCTS600 (hass, cts600, config.get('name'),
                       retries=config.get('retries'),
                       sensor_entity_id=config.get ('sensor'),
                       )
    try:
        await device.initialize ()
    except Exception as e:
        _LOGGER.error ("Device init failed for %s: %s", port, e)
        raise PlatformNotReady

    hass.data[DATA_KEY][port] = device
    async_add_entities([device], update_before_add=True)
    # test = await device.key(1)
    # _LOGGER.debug ("test: %s", test)


class HaCTS600 (ClimateEntity):
    """
    The main function of this class is to provide an async interface
    to the non-async code in nilan_cts600.py, so as to properly
    integrate with the HA eventloop.

    """
    _mode_map = {
        # Map CTS600 display text to HVACMode.
        'HEAT': HVACMode.HEAT,
        'COOL': HVACMode.COOL,
        'OFF': HVACMode.OFF,
    }
    _action_map = {
        # Map CTS600 display text to HVACAction.
        'HEATING': HVACAction.HEATING,
        'COOLING': HVACAction.COOLING,
        'OFF': HVACAction.OFF,
    }
    def __init__ (self, hass, cts600, name, retries=1, sensor_entity_id=None):
        self.hass = hass
        self.cts600 = cts600
        self._name = name
        self.retries = retries
        self._lock = asyncio.Lock()

        self._state = None
        # self._current_temperature = None
        self._last_on_operation = None
        self._fan_mode = None
        self._air_condition_model = None

        if sensor_entity_id:
            sensor_state = hass.states.get(sensor_entity_id)
            if sensor_state:
                self.hass.loop.create_task (self._update_T15_state (sensor_entity_id, None, sensor_state))
            async_track_state_change(hass, sensor_entity_id, self._update_T15_state)

        
    async def _update_T15_state (self, entity_id, old_state, new_state):
        """ Update thermostat with latest (room) temperature from sensor."""
        if new_state.state is None or new_state.state in ["unknown", "unavailable"]:
            return

        sensor_unit = new_state.attributes.get(ATTR_UNIT_OF_MEASUREMENT) or UnitOfTemperature.CELSIUS
        value = TemperatureConverter.convert(
            float(new_state.state), sensor_unit, UnitOfTemperature.CELSIUS
        )
        await self.setT15 (value)

    @property
    def name (self):
        """Return the name of the climate device."""
        return self._name

    @property
    def min_temp(self):
        return 5

    @property
    def max_temp(self):
        return 30

    @property
    def target_temperature_step(self):
        """Return the target temperature step."""
        return 1

    @property
    def should_poll(self):
        """Return the polling state."""
        return True

    @property
    def temperature_unit(self):
        """Return the unit of measurement."""
        return UnitOfTemperature.CELSIUS

    @property
    def supported_features(self):
        """Return the set of supported features."""
        return ClimateEntityFeature.TARGET_TEMPERATURE | ClimateEntityFeature.FAN_MODE
    
    @property
    def hvac_modes(self):
        """Return the list of available hvac modes."""
        return [HVACMode.HEAT, HVACMode.COOL, HVACMode.AUTO, HVACMode.OFF]

    @property
    def hvac_mode(self):
        """Return hvac mode ie. heat, cool, fan only."""
        cts600mode = self.cts600.data.get ('mode')
        mode = self._mode_map.get(cts600mode, None) if cts600mode else None
        # _LOGGER.debug ('hvac mode %s -> %s', cts600mode, mode)
        return mode

    @property
    def hvac_action(self):
        """Return hvac action ie. heat, cool, off."""
        led = self.cts600.led()
        if led == 'on':
            cts600action = self.cts600.data.get ('status')
            action = self._action_map.get(cts600action, None) if cts600action else None
            _LOGGER.debug ('hvac action %s -> %s', cts600action, action)
            return action
        elif led == 'off':
            return HVACAction.IDLE
        else:
            return None

    @property
    def fan_modes (self):
        """Return the list of available fan modes."""
        return ['1', '2', '3', '4']

    @property
    def fan_mode (self):
        """Return the current fan speed."""
        flow = self.cts600.data.get ('flow', None)
        return str (flow) if flow else None
    
    @property
    def target_temperature(self):
        """Return the temperature we try to reach."""
        _LOGGER.debug ('target_temp %s', self.cts600.data)
        return self.cts600.data.get('thermostat', None)

    @property
    def current_temperature (self):
        """Return the current temperature."""
        return self.cts600.data.get ('T15', None)

    async def async_set_temperature (self, temperature=None, **kwargs):
        """Set target temperature."""
        _LOGGER.debug ('set fan_temperature %s', temperature)
        await self.setThermostat (int(temperature))
    
    async def async_set_fan_mode (self, fan_mode):
        """Set the fan mode."""
        _LOGGER.debug ('set fan_mode %s', fan_mode)
        await self.setFlow (int(fan_mode))
    
    async def _call (self, method, *args):
        """Make a synchronous call to CTS600 by creating a job and
        then await that job. Use self._lock to serialize access to the
        underlying API. Also implement self.retries."""
        async with self._lock:
            _LOGGER.debug ("Call: %s %s", method.__func__.__name__, args)
            for attempt in range(1, self.retries+1):
                try:
                    result = await self.hass.async_add_executor_job (method, *args)
                except (TimeoutError, NilanCTS600ProtocolError) as e:
                    _LOGGER.debug ("Exception %s: %s %s", e.__class__.__name__, method.__func__.__name__, args)
                    if not attempt<self.retries:
                        raise e
            _LOGGER.debug ("Result: %s %s => %s", method.__func__.__name__, args, result)
            return result

    def initialize (self):
        return self._call (self.cts600.initialize)

    def key (self, key=0):
        return self._call (self.cts600.key, key)

    def updateData (self):
        return self._call (self.cts600.updateData)

    def setT15 (self, celcius):
        return self._call (self.cts600.setT15, celcius)

    def setFlow (self, flow):
        return self._call (self.cts600.setFlow, flow)

    def setThermostat (self, celsius):
        return self._call (self.cts600.setThermostat, celsius)

    async def async_update (self):
        state = await self.updateData ()
        _LOGGER.debug("Got new state: %s", state)
        return state

    
