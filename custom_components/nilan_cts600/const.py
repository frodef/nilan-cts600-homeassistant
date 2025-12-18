"""Constants for the NilanCTS600 integration."""

from homeassistant.const import Platform

DOMAIN = "nilan_cts600"
PLATFORMS = [Platform.BUTTON, Platform.CLIMATE, Platform.SENSOR]
DATA_KEY = "climate." + DOMAIN

# Connection types
CONNECTION_TYPE_SERIAL = "serial"
CONNECTION_TYPE_TCP = "tcp"

# Default values
DEFAULT_TCP_PORT = 502
DEFAULT_MODBUS_SLAVE_ID = 3
