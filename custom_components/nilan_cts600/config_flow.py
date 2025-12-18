import logging

import voluptuous as vol

from homeassistant.config_entries import ConfigFlow
from homeassistant.helpers.selector import selector

from .const import DOMAIN, CONNECTION_TYPE_SERIAL, CONNECTION_TYPE_TCP

_LOGGER = logging.getLogger(__name__)


def file_in_use(file_path):
    """Return True if FILE_PATH is in use by the current process, as indicated by an entry in /proc/self/fd."""
    import os

    rpath = os.path.realpath(file_path)
    try:
        for entry in os.scandir("/proc/self/fd"):
            if os.path.realpath(entry) == rpath:
                return True
    except FileNotFoundError:
        pass
    return False


def list_serial_devices(by_id="/dev/serial/by-id"):
    """Return a list of {'dev': <device-path>, 'description':
    <description>, 'id': <bool>} for each serial device. Prefer
    devices found in /dev/serial/by-id because these will not change
    across OS boots etc. Furthermore, list first the devices we
    believe to be unused by the current process.

    """
    import os

    import serial.tools.list_ports

    ids = {}
    try:
        for entry in os.scandir(by_id):
            # Map e.g. '/dev/ttyUSB0' to '/dev/serial/by-id/usb-foo-bar-00'
            if entry.is_symlink():
                ids[os.path.realpath(entry.path)] = entry
    except FileNotFoundError:
        pass

    return sorted(
        [
            {"dev": ids[p.device].path, "description": ids[p.device].name, "id": True}
            if ids.get(p.device)
            else {"dev": p.device, "description": str(p), "id": False}
            for p in serial.tools.list_ports.comports()
        ],
        key=lambda x: (2 if file_in_use(x["dev"]) else 0) + (1 if not x["id"] else 0),
    )


class CTS600ConfigFlow(ConfigFlow, domain=DOMAIN):
    """Example config flow."""

    # The schema version of the entries that it creates
    # Home Assistant will call your migrate method if the version changes
    VERSION = 1

    def __init__(self):
        """Initialize the config flow."""
        self._connection_type = None

    async def async_step_user(self, user_input=None):
        """Handle the initial step - connection type selection."""
        errors = {}

        if user_input is not None:
            self._connection_type = user_input.get(
                "connection_type", CONNECTION_TYPE_TCP
            )
            if self._connection_type == CONNECTION_TYPE_TCP:
                return await self.async_step_tcp()
            else:
                return await self.async_step_serial()

        config_schema = {
            vol.Required("connection_type", default=CONNECTION_TYPE_TCP): selector(
                {
                    "select": {
                        "options": [
                            {"label": "Modbus TCP", "value": CONNECTION_TYPE_TCP},
                            {
                                "label": "Modbus RTU (Serial)",
                                "value": CONNECTION_TYPE_SERIAL,
                            },
                        ],
                        "mode": "dropdown",
                    }
                }
            ),
        }

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(config_schema),
            errors=errors,
        )

    async def async_step_tcp(self, user_input=None):
        """Handle TCP configuration."""
        errors = {}
        suggestions = user_input or {
            "name": "Nilan Central Ventilation",
            "host": "",
            "tcp_port": 502,
        }

        config_schema = {
            vol.Required("name"): selector({"text": {"type": "text"}}),
            vol.Required("host"): selector({"text": {"type": "text"}}),
            vol.Optional("tcp_port", default=502): selector(
                {"number": {"min": 1, "max": 65535, "mode": "box"}}
            ),
            vol.Optional("sensor_T15"): selector(
                {"entity": {"filter": {"domain": ["sensor", "input_number"]}}}
            ),
        }

        if user_input and not errors:
            # Validate connection
            try:
                from pymodbus.client import ModbusTcpClient

                client = ModbusTcpClient(
                    host=user_input["host"],
                    port=int(user_input.get("tcp_port", 502)),
                )
                if not client.connect():
                    errors["host"] = "cannot_connect"
                else:
                    client.close()
            except Exception as e:
                _LOGGER.error("Connection test failed: %s", e)
                errors["host"] = "cannot_connect"

            if not errors:
                data = {
                    **user_input,
                    "connection_type": CONNECTION_TYPE_TCP,
                    "tcp_port": int(user_input.get("tcp_port", 502)),
                }
                return self.async_create_entry(title=user_input["name"], data=data)

        return self.async_show_form(
            step_id="tcp",
            data_schema=self.add_suggested_values_to_schema(
                vol.Schema(config_schema), suggestions
            ),
            errors=errors,
            last_step=True,
        )

    async def async_step_serial(self, user_input=None):
        """Handle Serial configuration."""
        errors = {}
        detected_ports = list_serial_devices()
        suggestions = user_input or {
            "name": "Nilan Central Ventilation",
            "port": detected_ports[0]["dev"] if detected_ports else "",
            "retries": 3,
        }

        config_schema = {
            vol.Required("name"): selector({"text": {"type": "text"}}),
            vol.Required("port"): selector(
                {
                    "select": {
                        "options": [
                            {"label": p["description"], "value": p["dev"]}
                            for p in detected_ports
                        ],
                        "mode": "dropdown",
                        "custom_value": True,
                    }
                }
            ),
            vol.Optional("sensor_T15"): selector(
                {"entity": {"filter": {"domain": ["sensor", "input_number"]}}}
            ),
        }
        if self.show_advanced_options:
            config_schema[vol.Optional("retries", default=2)] = selector(
                {"number": {"min": 1, "max": 5, "mode": "box"}}
            )

        if user_input and not errors:
            data = {
                **user_input,
                "connection_type": CONNECTION_TYPE_SERIAL,
            }
            return self.async_create_entry(title=user_input["name"], data=data)
        else:
            if not detected_ports:
                errors["base"] = "no_serial_port"
            return self.async_show_form(
                step_id="serial",
                data_schema=self.add_suggested_values_to_schema(
                    vol.Schema(config_schema), suggestions
                ),
                errors=errors,
                last_step=True,
            )
