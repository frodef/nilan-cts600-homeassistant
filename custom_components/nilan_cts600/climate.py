import logging

from homeassistant.helpers.typing import ConfigType, DiscoveryInfoType
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.const import UnitOfTemperature

from homeassistant.components.climate import ClimateEntity, ClimateEntityDescription
from homeassistant.util.unit_conversion import TemperatureConverter
from homeassistant.components.climate.const import (
    HVACMode,
    HVACAction,
    ClimateEntityFeature
)
from .coordinator import getCoordinator

_LOGGER = logging.getLogger(__name__)

async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback) -> None:
    await async_setup_platform (hass, entry.data, async_add_entities)
    
async def async_setup_platform(
        hass: HomeAssistant,
        config: ConfigType,
        async_add_entities: AddEntitiesCallback,
        discovery_info: DiscoveryInfoType | None = None,
) -> None:
    """Set up the platform."""
    coordinator = await getCoordinator (hass, config)
    device = CTS600Climate (hass, coordinator)
    async_add_entities([device], update_before_add=True)

class CTS600Climate (CoordinatorEntity, ClimateEntity):
    """ Provide the HA Climate interface. """
    _mode_map = {
        # Map CTS600 display text to HVACMode.
        'HEAT': HVACMode.HEAT,
        'COOL': HVACMode.COOL,
        'AUTO': HVACMode.AUTO,
        'OFF': HVACMode.OFF,
    }
    _mode_imap = {v:k for k,v in _mode_map.items()}
    _action_map = {
        # Map CTS600 display text to HVACAction.
        'HEATING': HVACAction.HEATING,
        'COOLING': HVACAction.COOLING,
        'OFF': HVACAction.OFF,
    }

    def __init__ (self, hass, coordinator):
        super().__init__(coordinator)

        self.cts600 = coordinator.cts600
        self._name = coordinator.name + " Climate Control"
        self._attr_unique_id = f"serial-{self.cts600.port}-climate"
        
        self._state = None
        self._last_on_operation = None
        self._fan_mode = None
        self._air_condition_model = None

        self._attr_device_info = coordinator.device_info
        self.entity_description = ClimateEntityDescription(
            key='nilan_cts600',
            icon='mdi:hvac'
        )
        
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
        return self.cts600.data.get('thermostat', None)

    @property
    def current_temperature (self):
        """Return the current temperature."""
        return self.cts600.getT15 ()

    async def async_set_temperature (self, temperature=None, **kwargs):
        """Set target temperature."""
        _LOGGER.debug ('set fan_temperature %s', temperature)
        await self.coordinator.setThermostat (int(temperature))
    
    async def async_set_fan_mode (self, fan_mode):
        """Set the fan mode."""
        _LOGGER.debug ('set fan_mode %s', fan_mode)
        await self.coordinator.setFlow (int(fan_mode))

    async def async_set_hvac_mode(self, hvac_mode):
        """Set new target hvac mode."""
        _LOGGER.debug ('set hvac_mode %s', hvac_mode)
        display = await self.coordinator.resetMenu()
        current_mode = display.split('/')[0].split(' ')[0]
        if self._mode_map[current_mode] == hvac_mode:
            return
        elif hvac_mode == HVACMode.OFF:
            await self.coordinator.key_off()
        else:
            if current_mode == 'OFF':
                await self.coordinator.key_on()
            await self.coordinator.setMode (self._mode_imap[hvac_mode])

    
