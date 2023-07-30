# nilan-cts600-homeassistant

This is a Home Assistant integration for the Nilan CTS600 HVAC control
system, controlling e.g. the [Nilan
VPL-15](https://www.en.nilan.dk/products/ventilation-with-cooling-heating/heat-pump-and-heat-pipe/vpl-15)
ventilation unit. This integration, via a serial Modbus adapter, is to
be connected to the ventilation unit and replaces the physical control
panel.

Currently, this integration implements the
[Climate](https://www.home-assistant.io/integrations/climate/)
interface for Home Assistant. This means that you can set the
ventilation unit's mode (auto, heat, cool, or off) and its target
temperature. You can also set the fan speed (1, 2, 3, or 4). Finally,
the thermometer in the physical control panel (Nilan sensor T15) is
replaced with any HA entity, typically a temperature sensor.

![CTS600](https://nilanireland.ie/wp-content/uploads/2013/08/CTS-600-1.png "CTS600")

# What is this integration for? #

The Nilan VPL-15 ventilation unit (and similar units from Nilan) have
been delivered with a range of control systems over the years,
starting I believe with simple analog controls back in the day, until
todays modern CTS602 or CTS700-based control systems that supports
LAN interfacing, mobile apps and whatnot.

This integration is specifically for units controlled via the CTS600
interface. Historically this is an intermediate technology which is
digital but not really designed to be interfaced or integrated with
other systems.

There exists a different integration in HACS for CTS602-based systems,
named
[Nilan](http://homeassistant.home:8123/hacs/repository/487536666).

This integration is created for my Nilan VPL-15 ventilation unit
controlled by CTS600. There are other Nilan ventilation units provided
with the CTS600 controller. These systems may or may not work as
is. If you have such a non-VPL-15 system, I'd be interested in making
this integration work, so please test and open an Github issue for
this purpose.

The following is a list of Nilan ventilation units other than the
VPL-15 that I believe have been delivered with the CTS600 controller:
  * Comfort-450
  * Comfort-600
  * Comfort-300
  * VPL-28
  * VP-18 M2
  * VGU-250

# Serial RS485 adapter

An adapter is required to interface the CTS600 to the PC running Home
Assistant. I am using a USB serial RS485 (modbus) adapter. These come
in many shapes and colours. I reccommend the one that is black with
green screw terminals and a USB pigtail. [Link to
Aliexpress.](https://www.aliexpress.com/item/1005004520479272.html)
I'd advise against the blue translucent ones.

![adapter](usb-rs485.webp "Image of adapter")

## Physical connection

The Nilan VPL-15 (and presumably other) unit connects to the physical
control panel via 4 wires. Two wires provides 12V power, and the
remaining two are the RS485 A and B communication wires.

Only the two A and B communication wires must be connected to the USB
adapter. **Do not connect the power wires to the adapter**, as this
will likely destroy your adapter, and possibly also your PC and/or
ventilation unit!

The image below identifies the wires on the side of the original
control panel.

![connection](connection.png "Connection")

# Configuration

This integration currently supports only manual configuration in
configuration.yaml, for example:

    climate:
      platform: nilan_cts600
      name: LoftCTS600
      retries: 3
      sensor_T15: input_number.stuetemp
      port: /dev/ttyUSB0

These are the configuration entries:

  * `name`: Any name you choose to identify the ventilation unit.
  * `retries`: The number of times to retry a CTS600 request before failing.
  * `sensor_T15`: Names the entity that provides the value for the
    room temperature, substituting the temperature sensor in the
    original control panel.
  * `port`: The device node corresponding to your RS485 adapter. If
    you have no other USB serial adapters installed, this will be
    `/dev/ttyUSB0`.

# About the CTS600

