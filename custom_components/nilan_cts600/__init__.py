from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .const import PLATFORMS, DATA_KEY, CONNECTION_TYPE_TCP


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up the integration from a (UI) config entry."""
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    
    if unload_ok and DATA_KEY in hass.data:
        # Determine the connection key
        config = entry.data
        connection_type = config.get("connection_type", CONNECTION_TYPE_TCP)
        
        if connection_type == CONNECTION_TYPE_TCP:
            host = config.get("host")
            tcp_port = config.get("tcp_port", 502)
            connection_key = f"tcp://{host}:{tcp_port}"
        else:
            connection_key = config.get("port")
        
        # Remove the coordinator from hass.data and disconnect
        if connection_key in hass.data[DATA_KEY]:
            coordinator = hass.data[DATA_KEY].pop(connection_key)
            if hasattr(coordinator, 'cts600') and coordinator.cts600:
                coordinator.cts600.disconnect()
    
    return unload_ok
