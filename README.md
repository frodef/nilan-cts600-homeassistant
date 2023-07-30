# nilan-cts600-homeassistant
This is a Home Assistant integration for the Nilan CTS600 HVAC control
system, controlling e.g. the [Nilan
VPL15](https://www.en.nilan.dk/products/ventilation-with-cooling-heating/heat-pump-and-heat-pipe/vpl-15)
ventilation unit.

# What is this integration for? #

The Nilan VPL15 ventilation unit (and similar units from Nilan) have
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

This integration is created for my Nilan VPL15 ventilation unit
controlled by CTS600. There are other Nilan ventilation units provided
with the CTS600 controller. These systems may or may not work as
is. If you have such a non-VPL15 system, I'd be interested in making
this integration work, so please open an Github issue for this
purpose.

The following is a list of Nilan ventilation units that I believe have
been delivered with the CTS600 controller:
  * Comfort-450
  * Comfort-600
  * Comfort-300
  * VPL-28
  * VP-18 M2
  * VGU-250
  

# About the CTS600




Connect to your CTS600 via a serial RS485 USB adapter. Programmed for
interfacing Nilan VPL15. May or may not work with other (old) Nilan
products with CTS600 interface.
