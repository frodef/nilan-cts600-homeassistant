from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .const import PLATFORMS

async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up the integration from a (UI) config entry."""
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True
