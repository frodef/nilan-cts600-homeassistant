import logging
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .coordinator import getCoordinator

from .const import PLATFORMS

_LOGGER = logging.getLogger(__name__)

async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up the integration from a (UI) config entry."""
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True

async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry):
    """Unload a config entry."""
    # 1. Unload all platforms associated with this entry
    if unload_ok := await hass.config_entries.async_unload_platforms(entry, PLATFORMS):
        # 2. If platforms unloaded successfully, clean up local resources
        # Example: Stop a data update coordinator
        # entry.runtime_data.coordinator.shutdown()
        _LOGGER.debug('UNLOAD: %s', entry)
        coordinator = await getCoordinator(hass, entry.data)
        await coordinator.async_shutdown()
    return unload_ok

