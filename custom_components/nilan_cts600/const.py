"""Constants for the NilanCTS600 integration."""

from homeassistant.const import Platform

DOMAIN = "nilan_cts600"
PLATFORMS = [Platform.CLIMATE, Platform.SENSOR, Platform.BUTTON]
DATA_KEY = "climate." + DOMAIN
