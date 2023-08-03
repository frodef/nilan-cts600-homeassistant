import logging
import voluptuous as vol
from homeassistant import config_entries
from homeassistant.helpers.selector import selector
from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)

def file_in_use (file_path):
    """ Return True if FILE_PATH is in use by the current process, as indicated by an entry in /proc/self/fd. """
    import os
    rpath = os.path.realpath (file_path)
    for entry in os.scandir ('/proc/self/fd'):
        if os.path.realpath (entry) == rpath:
            return True
    return False

def list_serial_devices (by_id="/dev/serial/by-id"):
    """Return a list of {'dev': <device-path>, 'description':
    <description>, 'id': <bool>} for each serial device. Prefer
    devices found in /dev/serial/by-id because these will not change
    across OS boots etc. Furthermore, list first the devices we
    believe to be unused by the current process.

    """
    import serial.tools.list_ports, os
    ids = {}
    for entry in os.scandir(by_id):
        # Map e.g. '/dev/ttyUSB0' to '/dev/serial/by-id/usb-foo-bar-00'
        if entry.is_symlink():
            ids[os.path.realpath(entry.path)] = entry

    return sorted([{'dev': ids[p.device].path,
                    'description': ids[p.device].name,
                    'id': True}
                   if ids.get(p.device)
                   else {'dev': p.device,
                         'description': str(p),
                         'id': False}
                   for p in serial.tools.list_ports.comports()
                   ],
                  key=lambda x: (2 if file_in_use(x['dev']) else 0) + (1 if not x['id'] else 0))

class CTS600ConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Example config flow."""
    # The schema version of the entries that it creates
    # Home Assistant will call your migrate method if the version changes
    VERSION = 1

    async def async_step_user(self, user_input=None):
        # Specify items in the order they are to be displayed in the UI
        import serial.tools.list_ports

        errors = {}
        detected_ports = list_serial_devices()
        suggestions = user_input or {
            "name": "Nilan Central Ventilation",
            "port": detected_ports[0]['dev'] if detected_ports else "",
            "retries": 3,
        }

        config_schema = {
            vol.Required ("name"):
            selector ({
                "text": {
                    "type": "text"
                }
            }),
            vol.Required("port"):
            selector({
                "select": {
                    "options": [{'label': p['description'], 'value': p['dev']} for p in detected_ports],
                    "mode": "dropdown",
                    "custom_value": True,
                }
            }),
            vol.Optional ("sensor_T15"): selector ({
                "entity": {
                    "filter": {
                        "domain": ["sensor", "input_number"]
                    }
                }
            }),
        }
        if self.show_advanced_options:
            config_schema[vol.Optional ("retries", default=2)] = selector ({
                "number": {
                    "min": 1,
                    "max": 5,
                    "mode": "box"
                }
            })
            
        if user_input and user_input["port"]:
            try:
                serial.Serial(user_input["port"]).close()
            except serial.SerialException:
                errors["port"] = f"Not a serial port: {user_input['port']}"

        if user_input and not errors:
            return self.async_create_entry (title=user_input["name"], data=user_input)
        else:
            if not detected_ports:
                errors['base'] = "No serial port detected."
            return self.async_show_form(step_id="user",
                                        data_schema=self.add_suggested_values_to_schema(vol.Schema(config_schema), suggestions),
                                        errors=errors,
                                        last_step=True)
