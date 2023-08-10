import logging

from homeassistant.core import HomeAssistant, callback
from homeassistant.config_entries import ConfigEntry
from homeassistant.helpers.typing import ConfigType, DiscoveryInfoType
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
    SensorEntityDescription,
)
from homeassistant.const import (
    UnitOfTemperature,
    ATTR_UNIT_OF_MEASUREMENT,
)
from .coordinator import getCoordinator

_LOGGER = logging.getLogger(__name__)

_ENTITIES = (
    SensorEntityDescription(
        key="T1",
        name="T1",
        state_class=SensorStateClass.MEASUREMENT,
        device_class=SensorDeviceClass.TEMPERATURE,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
    ),
    SensorEntityDescription(
        key="T2",
        name="T2",
        state_class=SensorStateClass.MEASUREMENT,
        device_class=SensorDeviceClass.TEMPERATURE,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
    ),
    SensorEntityDescription(
        key="T5",
        name="T5",
        state_class=SensorStateClass.MEASUREMENT,
        device_class=SensorDeviceClass.TEMPERATURE,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
    ),
    SensorEntityDescription(
        key="T6",
        name="T6",
        state_class=SensorStateClass.MEASUREMENT,
        device_class=SensorDeviceClass.TEMPERATURE,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
    ),
    SensorEntityDescription(
        key="T15",
        name="T5",
        state_class=SensorStateClass.MEASUREMENT,
        device_class=SensorDeviceClass.TEMPERATURE,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
    ),
    SensorEntityDescription(
        key="display",
        name="display"
    )
)

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
    async_add_entities([CTS600Sensor (coordinator, e, None) for e in _ENTITIES],
                       update_before_add=True)

class CTS600Sensor(CoordinatorEntity, SensorEntity):
    """An entity using CoordinatorEntity.

    The CoordinatorEntity class provides:
      should_poll
      async_update
      async_added_to_hass
      available

    """

    def __init__(
        self, coordinator, description: SensorEntityDescription, entry_id: str
    ) -> None:
        """Pass coordinator to CoordinatorEntity."""
        super().__init__(coordinator)
        self.var_name = description.key
        # self._attr_name = DOMAIN + "_" + spec["name"]
        # self._attr_state_class = spec["state-class"]
        # self._attr_device_class = spec["device-class"]
        # self._attr_native_unit_of_measurement = spec["unit"]

        self._name = coordinator.name + " " + self.var_name
        self._attr_device_info = coordinator.device_info
        self.entity_description = description
        self._attr_unique_id = f"serial-{self.coordinator.cts600.port}-{self.var_name}"

    @callback
    def _handle_coordinator_update(self) -> None:
        """Handle updated data from the coordinator."""
        #        _LOGGER.debug("Entity update: %s", self.coordinator.data)
        value = self.coordinator.cts600.data.get(self.var_name)
        if value:
            self._attr_native_value = value
            self.async_write_ha_state()

    @property
    def name (self):
        """Return the name of the climate device."""
        return self._name
