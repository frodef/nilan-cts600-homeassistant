import logging

from homeassistant.components.button import ButtonEntity, ButtonEntityDescription
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.typing import ConfigType, DiscoveryInfoType
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .coordinator import getCoordinator
from .nilan_cts600 import Key

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    """foo"""
    _LOGGER.debug("%s setup_entry: %s", __name__, entry.data)
    await async_setup_platform(hass, entry.data, async_add_entities, entry_id=entry.entry_id)


async def async_setup_platform(
    hass: HomeAssistant,
    config: ConfigType,
    async_add_entities: AddEntitiesCallback,
    discovery_info: DiscoveryInfoType | None = None,
    entry_id: str | None = None,
) -> None:
    """Set up the platform."""
    coordinator = await getCoordinator(hass, config)
    async_add_entities(
        [
            CTS600Button(coordinator, key, entry_id)
            for key in [Key.UP, Key.DOWN, Key.ENTER, Key.ESC, Key.ON, Key.OFF]
        ]
    )


class CTS600Button(CoordinatorEntity, ButtonEntity):
    """Button entity for CTS600."""
    
    _attr_has_entity_name = True

    def __init__(self, coordinator, key, entry_id: str | None = None) -> None:
        super().__init__(coordinator)
        self.var_name = key.name.lower()
        self._attr_device_info = coordinator.device_info
        self.entity_description = ButtonEntityDescription(
            key=self.var_name,
            name=self.var_name.replace("_", " ").title(),
            device_class=None,
        )
        # Use entry_id for stable unique_id
        self._attr_unique_id = f"{entry_id}-{self.var_name}" if entry_id else f"{coordinator.name}-{self.var_name}"
        self.key = key

    async def async_press(self) -> None:
        await self.coordinator.key(self.key)
        self.coordinator.register_manual_activity()
        self.coordinator.cts600.updateDisplay()
        self.coordinator.async_set_updated_data(self.coordinator.data)
