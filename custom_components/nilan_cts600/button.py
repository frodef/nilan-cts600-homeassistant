import logging

from homeassistant.core import HomeAssistant, callback
from homeassistant.config_entries import ConfigEntry
from homeassistant.helpers.typing import ConfigType, DiscoveryInfoType
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.components.button import ButtonEntity, ButtonEntityDescription

from .coordinator import getCoordinator
from .nilan_cts600 import Key

_LOGGER = logging.getLogger(__name__)

async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback) -> None:
    """ foo """
    _LOGGER.debug ("%s setup_entry: %s", __name__, entry.data)
    await async_setup_platform (hass, entry.data, async_add_entities)

async def async_setup_platform(
        hass: HomeAssistant,
        config: ConfigType,
        async_add_entities: AddEntitiesCallback,
        discovery_info: DiscoveryInfoType | None = None,
) -> None:
    """Set up the platform."""
    coordinator = await getCoordinator (hass, config)
    async_add_entities([CTS600Button (coordinator, key) for key in [Key.UP, Key.DOWN, Key.ENTER, Key.ESC, Key.ON, Key.OFF]])

class CTS600Button(CoordinatorEntity, ButtonEntity):
    def __init__(self, coordinator, key) -> None:
        super().__init__(coordinator)
        self.var_name = key.name.lower()
        self._name = coordinator.name + " " + self.var_name
        self._attr_device_info = coordinator.device_info
        self.entity_description = ButtonEntityDescription(key=self.var_name, device_class=None)
        self._attr_unique_id = f"serial-{self.coordinator.cts600.port}-{self.var_name}"
        self.key = key

    @property
    def name (self):
        """Return the name of the climate device."""
        return self._name
        
    async def async_press (self) -> None:
        await self.coordinator.key (self.key)
        self.coordinator.register_manual_activity()
        self.coordinator.cts600.updateDisplay()
        self.coordinator.async_set_updated_data(self.coordinator.data)


