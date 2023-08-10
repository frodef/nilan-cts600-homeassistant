
import codecs, struct, time, os, re
from enum import Enum
from pymodbus.client import ModbusSerialClient
from pymodbus.utilities import computeCRC

class NilanCTS600Exception (Exception):
    pass

class NilanCTS600ProtocolError (NilanCTS600Exception):
    pass

class NilanOperators(Enum):
    READ_DISCRETE_INPUTS = 2
    READ_MULTIPLE_HOLDING_REGISTERS = 3
    READ_INPUT_REGISTERS = 4
    PRESET_SINGLE_REGISTER = 6
    REPORT_SLAVE_ID = 17
    WI_RO_BITS = 65
    WI_RO_REGS = 66

class Key (Enum):
    """ A bitmap representing the console buttons. """
    NONE = 0x00
    ESC = 0x01
    UP = 0x02
    DOWN = 0x04
    ENTER = 0x08
    OFF = 0x10
    ON = 0x20

    def __int__ (self):
        return self.value
    def __add__(self, other):
        return self.value | int(other)
    
def word8 (recv, index=None):
    if index is not None:
        return recv[index]
    else:
        return recv(1)[0]
    
def word16 (recv, index=None):
    if index is not None:
        return recv[index+0]*0x100+recv[index+1]
    else:
        return recv(1)[0]*0x100+recv(1)[0]

def word16b (recv):
    return recv(1)[0]+recv(1)[0]*0x100

def frame8 (x):
    return [x & 0xff]

def frame16 (x):
    return [(x>>8) & 0xff, (x>>0) & 0xff]

def frame (*args):
    f = []
    for x in args:
        f.extend(x)
    return f

def parseLastNumber (string):
    return int (string.split()[-1], 10)
    
def parseCelsius (string):
    """ Assuming STRING contains a number with a °C suffix, return that number. """
    return parseLastNumber(string[0:string.find('°C')])

def parseFlow (string):
    """ Assuming STRING contains a number 1-4 delimited like >num<, return that number."""
    flowText = re.findall ('>([1-4])<', string)
    return int (flowText[0], 10) if flowText else None

def findUSB (dev='/dev/'):
    for ttyusb in filter(lambda x: re.search('^ttyUSB[0-9]*', x), os.listdir(dev)):
        return dev + ttyusb
    raise Exception ('No USB device found.')

def cycleToMenuEnd (initText, cycler, maxTries=10, match=None):
    """ Repeat CYCLER function until it returns the same string, or until it matches MATCH."""
    if match and re.findall (match, initText):
        return initText
    old_text = initText
    tries = 0
    while (new_text := cycler()) != old_text:
        # print (f'cycle: {new_text}')
        if match and re.findall (match, new_text):
            return new_text
        tries += 1
        if tries >= maxTries:
            raise NilanCTS600Exception (f'Unable to cycle menu: {old_text} -> {new_text}')
        old_text = new_text
    if match:
        return False
    else:
        return old_text

_nilanCodePage = {
    8: 198,
    9: 216,
    10: 197,
    11: 196,
    12: 214,
    13: 218,
    223: 176 }

def nilanString (buffer):
    """ Decode binary buffer into a text string. """
    return codecs.decode(bytes(map (lambda b: _nilanCodePage.get(b, b), buffer.replace (b'\x00', b''))),
                         encoding='latin-1')

def nilanStringApplyAttribute (string, attributeData, startBlink='{', endBlink='}'):
    """Apply string attribute, i.e. blinking, according to bits in
    attributeData. That is, if a number should blink, enclose it in
    curly brackets."""
    output = ""
    mode = 0
    for i in range (0, len(string)):
        bitPos = i*2
        newMode = (attributeData[bitPos//8]>>(bitPos&0x7)) & 0x03
        if newMode != mode:
            if newMode == 0x0:
                output += endBlink
            elif newMode == 0x2:
                output += startBlink
            mode = newMode
        output += string[i]
    if mode != 0:
        output += endBlink
    return output

def nilanADToCelsius (advalue, x=56.25):
    """ Convert AD temperature sensor value to celsius. """
    return x - (advalue * ((34 - 12) / (328 - 168)))

def nilanCelsiusToAD (celsius, x=56.25):
    """ Convert Celsius to AD temperature sensor value. """
    return round ((x - celsius) / ((34 - 12) / (328 - 168)))

def appendCRC (frame):
    crc = computeCRC (frame)
    return frame + [(crc>>0)&0xff, (crc>>8)&0xff]

default_slave_id_format = (
    ('slaveID', 'B'),
    ('runStatus', 'B'),
    ('errorStatus', 'B'),
    ('resetStatus', 'B'),
    ('protocolVersion', 'B'),
    ('softwareVersion', 'H'),
    ('softwareDate', 'H'),
    ('softwareTime', 'H'),
    ('product', '10s'),
    ###
    ('numofOutputBits', 'H'),
    ('numofLEDs', 'H'),
    ('numofInputBits', 'H'),
    ('numofKeys', 'H'),
    ('numofOutputRegisters', 'H'),
    ('numofInputRegisters', 'H'),
    ('reserved', '2s'),
    ('numofActions', 'H'),
    ('displayRows', 'H'),
    ('displayColumns', 'H'),
    ('displayType', 'B'),
    ('displayDataType', 'B'))

def decodeSlaveID (data, format = default_slave_id_format):
    def fb(fmt):
        return '!' + ''.join([s for n,s in fmt])
    f = format
    while f and (struct.calcsize (fb(f)) > len(data)):
        f = f[:-1] # decrease struct format if there's not enough data
    return dict (zip ([n for n,s in f], struct.unpack_from(fb(f), data)))


def read_response (rawRecv):
    """ Parse a Nilan response packet from rawRecv, which is a function
    that returns consequtive bytes.
    """
    frame = []
    def recv (n):
        nonlocal frame
        if n==0:
            return []
        b = rawRecv(n)
        if len(b) == 0:
            raise TimeoutError
        frame.extend(b)
        return b

    slave = word8(recv)
    function_code = word8(recv)
    try:
        op = NilanOperators(function_code)
    except ValueError:
        raise NilanCTS600ProtocolError (f"Received unknown function code: {function_code}")
    parameters = ()
    data_size = None
    
    if (op == NilanOperators.REPORT_SLAVE_ID):
        data_size = word8(recv)
    elif (op in (NilanOperators.WI_RO_REGS, NilanOperators.WI_RO_BITS)):
        parameters = (word16(recv), word16(recv))
        data_size = word16(recv)
    elif (op in (NilanOperators.READ_MULTIPLE_HOLDING_REGISTERS, NilanOperators.READ_INPUT_REGISTERS)):
        data_size = word8(recv)
    elif (op == NilanOperators.PRESET_SINGLE_REGISTER):
        parameters = (word16(recv), word16(recv))
        data_size = 0
    else:
        raise Exception(f"Unknown response op {op}")

    data = recv(data_size)
    computedCRC = computeCRC(bytes(frame))
    gotCRC = word16b(recv)
    # print(f'ACK: {op} : {parameters} : {data} : {gotCRC:04x} : {computedCRC:04x}')
    return op.name, parameters, data, gotCRC == computedCRC

def _scanner_reset_menu ():
    """ Keep hittin ESC until nothing more happens. """
    return [ (Key.ESC,""), {'regexp': '.*'}]

def _scanner_search_menu (action, regexp):
    """ Do action until regexp matches. """
    return [ (action,""), dict(regexp=regexp, stop=True), dict(regexp='.*') ]
    

class CTS600:
    _ack_handlers = {
        'REPORT_SLAVE_ID': 'ack_report_slave_id',
        'READ_MULTIPLE_HOLDING_REGISTERS': 'ack_read_multiple_holding_registers',
        'READ_INPUT_REGISTERS': 'ack_read_multiple_holding_registers',
        'PRESET_SINGLE_REGISTER': 'ack_preset_single_register',
        'WI_RO_REGS': 'ack_wi_ro_regs',
        'WI_RO_BITS': 'ack_wi_ro_bits'
        }
    _slave_id_struct = default_slave_id_format
    remote_version = 0x5c
        
    def __init__(self, port=None, client=None, unit=3, rows=2, columns=8, logger=None):
        self.port = port
        self.client = client or ModbusSerialClient(port=port, baudrate=19200, parity='N', stopbits=2, bytesize=8)
        self._logger = logger
        self.unit = unit
        self.output_registers = [0] * 0x300
        self.output_bits = dict()
        self.crc_fails = 0
        self.slave_id_data = None
        self.rows = rows
        self.columns = columns
        self.data = {}
        self.metaData = {}
        self._t15_adtemp = None

    def log (self, fmt, *args):
        if self._logger:
            self._logger(fmt, *args)
        
    def connect (self):
        self.client.connect()
        self.client.framer.resetFrame()
        
    def slaveID (self):
        return decodeSlaveID (self.slave_id_data, self._slave_id_struct)
        
    def read_holding_registers (self, address, count):
        self.doRequest ((NilanOperators.READ_MULTIPLE_HOLDING_REGISTERS, address, count),
                        frame (frame16 (address),
                               frame16 (count)))

    def read_input_registers (self, address, count):
        self.doRequest ((NilanOperators.READ_INPUT_REGISTERS, address, count),
                        frame (frame16 (address),
                               frame16 (count)))
        
    def preset_single_register (self, address, value):
        self.doRequest (
            (NilanOperators.PRESET_SINGLE_REGISTER, address, value),
            frame (frame16 (address),
                   frame16 (value)))

    def wi_ro_regs (self, address, *values):
        self.doRequest (
            (NilanOperators.WI_RO_REGS, address, values),
            frame (frame16 (address),
                   frame16 (len (values)),
                   frame16 (2*len (values)),
                   *map (frame16, values)))
        
    def doRequest (self, request, requestFrame=[]):
        """Transmit a request and receive and process a response.  The
        request is sent to SELF.UNIT and the function-code is the
        first element of the REQUEST argument. Then REQUESTFRAME is
        tacked on the request.

        """
        (reqOP, *args) = request if isinstance(request, tuple) else (request,)
        self.send(reqOP, requestFrame)
        (ackOP, parameters, data, crcOK) = read_response(self.client.recv)
        if (not crcOK):
            self.crc_fails += 1
            self.log ('CRC Fail: %s', request)
            return False
        handler = getattr(self, self._ack_handlers.get(ackOP, 'None'), None)
        if handler:
            handler(ackOP, parameters, data, request=request)
        else:
            self.log("Warning: No ack handler for op %s.", ackOP)
    
    def send (self, op, frame):
        """Transmit OP to SELF.UNIT and then remaining FRAME."""
        f = [self.unit, op.value] + frame
        f = appendCRC(f)
        return self.client.send(bytes(f))

    def ack_report_slave_id (self, op, parameters, data, request=None):
        self.slave_id_data = data

    def ack_read_multiple_holding_registers (self, op, parameters, data, request=None):
        (reqOP, address, count) = request or (None, None)
        if address is not None and count is not None:
            values = [word16(data, i*2) for i in range(0, count)]
            a = address
            for v in values:
                self.output_registers[a] = v
                a += 2

    def ack_preset_single_register (self, op, parameters, data, request=None):
        if (request and (request != (NilanOperators.PRESET_SINGLE_REGISTER, *parameters))):
            self.log ("ack_preset_single_register mismatch: %s -> %s", request, parameters)

    def ack_wi_ro_regs (self, op, parameters, data, request=None):
        (address, count) = parameters
        # print (f'ack_wi_ro_regs: {parameters} : {data}')
        for i in range(0, len(data)):
            self.output_registers[address+i] = word8(data, i)

    def ack_wi_ro_bits (self, op, parameters, data, request):
        (address, bitCount) = parameters
        # print (f'ack_wi_ro_bits: {parameters} : {data}')
        for i in range (0, len(data)):
            self.output_bits[address+i] = data[i]

    def initialize (self):
        self.doRequest(NilanOperators.REPORT_SLAVE_ID)
        self.read_holding_registers (0x102, 1)
        self.preset_single_register (0x104, self.remote_version)
        
    def key (self, key=Key.NONE):
        """Transmit a keypress message to CTS600. KEY is a bitmap of
        the keys pressed. CTS600 will respond with more or less random
        register updates, and a zero KEY bitmap is effectively a
        generic request for state update from CTS600.

        """
        keycode = int (key) if key else 0
        self.wi_ro_regs (0x100, keycode)
        if keycode != 0:
            self.wi_ro_regs (0x100, keycode)
            self.wi_ro_regs (0x100, 0)
        return self.display()

    def key_esc (self):
        return self.key (Key.ESC)
    
    def key_up (self, repeat=1):
        for _ in range (repeat-1):
            self.key (Key.UP)
        return self.key(Key.UP)

    def key_down (self, repeat=1):
        for _ in range(repeat-1):
            self.key (Key.DOWN)
        return self.key(Key.DOWN)

    def key_enter (self):
        return self.key (Key.ENTER)

    def key_off (self):
        return self.key (Key.OFF)

    def key_on (self):
        return self.key (Key.ON)

    def displayRow (self, row, startBlink='{', endBlink='}'):
        """Construct a string representation of the CTS600 display's
        row number ROW.  Any text that should be blinking is put
        inside curly brackets.

        NB: Will not query CTS600 for updated data.

        """
        bytesPerRow = self.columns + int(self.columns/4)
        startRegister = 0x200 + row*bytesPerRow
        return nilanStringApplyAttribute(
            nilanString(bytes(self.output_registers[startRegister:startRegister+self.columns])),
            self.output_registers[startRegister+self.columns:startRegister+bytesPerRow],
            startBlink=startBlink,
            endBlink=endBlink)
    
    def display (self, newline='/'):
        return newline.join ([self.displayRow (r).strip() for r in range (0, self.rows)])

    def led (self):
        if 0x100 in self.output_bits:
            return ['off', 'on', 'unknown', 'blink'][self.output_bits[0x100] & 0x03]
        else:
            return 'unknown'

    def resetMenu (self, maxTries=10):
        """ Put CTS600 in default state, by pressing ESC sufficiently many times. """
        self.scanMenu ([_scanner_reset_menu()])
        return self.display()

    def scanMenu (self, menu_spec, data=None, meta_data=None):
        """Cycle through the CTS600 menu and record the relevant
        values, according to the structure specified in MENU_SPEC.

        """
        data = data or dict()
        metaData = meta_data or dict()
        translate_var = str.maketrans ("/", " ", "<>")
        
        def record_matching_entry (m, e, prefix=""):
            """ Local utility, record regexp match M for entry E. """
            if 'var' in m:
                variable_key = "_".join(m['var'].translate(translate_var).split())
            elif 'var' in e:
                variable_key = e['var']
            else:
                return
            if variable_key and 'value' in m:
                variable_key = prefix + variable_key
                data[variable_key] = e['parse'] (m['value']) if 'parse' in e else m['value']
                metaData[variable_key] = dict()
                if 'description' in m:
                    metaData[variable_key]['description'] = m['description']
                if 'kind' in e:
                    metaData[variable_key]['kind'] = e['kind']

        def run_action (action):
            return self.key (action) if isinstance (action, Key) else action()
                
        def scanSequence (menu_spec_sequence):
            """ Match entries one after the next. """
            for e in menu_spec_sequence:
                if isinstance (e, list):
                    scanParallell (e[1:], e[0][0], e[0][1])
                elif isinstance (e, dict):
                    display = run_action(e['display']) if 'display' in e else self.display()
                    # print (f"scan: {e}, disp {display}")
                    if 'regexp' in e:
                        if not (match := re.match (e['regexp'], display)):
                            break # Stop sequence at first mismatch
                        else:
                            record_matching_entry (match.groupdict(), e)
                            if 'gonext' in e:
                                run_action(e['gonext'])
                else:
                    run_action (e)
 
        def scanParallell (menu_spec_parallell, gonext, var_prefix=""):
            """ Match any entry until display doesn't change or matching entry says to stop. """
            previous_display = None
            display = self.display()
            stopped = False
            while not (stopped or display == previous_display):
                # Search for the first entry that matches display, and execute entry
                # print (f"psearch: {display}")
                next_gonext = gonext
                for e in menu_spec_parallell:
                    if not 'regexp' in e:
                        raise Exception (f"Parallell menu_spec missing regexp: %s", menu_spec_parallell)
                    if match := re.match (e['regexp'], display):
                        next_gonext = e.get ('gonext', gonext)
                        record_matching_entry (match.groupdict(), e, var_prefix)
                        if e.get ('stop', False):
                            stopped = True
                        if 'then' in e:
                            scanSequence (e['then'])
                        break
                else:
                    print (f'Parallell no match for {display}')
                    break
                if not stopped:
                    previous_display = display
                    display = run_action(next_gonext)
        scanSequence (menu_spec)
        return data, metaData

    def updateDisplay (self):
        self.data['display'] = self.display(newline='\n')
        self.data['led'] = self.led()
        
    def scanData (self, updateShowData=True, updateAllData=False):
        """ Scan the main display and "SHOW DATA" menu and record the relevant operating parameters.
        """
        f = dict
        scan_menu = [
            _scanner_reset_menu(),
            f (regexp="(?P<value>.*)", var='display', parse=lambda d: d.replace ('/', '\n')),
            f (regexp=".* (?P<value>\d+)°C", var='thermostat', parse=int),
            f (regexp="^(?P<value>\w+)", var='mode'),
            f (regexp=".*>(?P<value>\d+)<", var='flow', parse=int)
        ]
        if updateShowData:
            show_data = [
                f (display=Key.UP, regexp="SHOW/DATA", gonext=self.key_enter),
                [ (Key.DOWN, ""),
                  f (regexp="STATUS/(?P<value>.*)", var='status'),
                  # Match any temperature sensor like T5:
                  f (regexp="(?P<description>.*)/(?P<var>T\d+)\s+(?P<value>\d+)°C$", parse=int, kind='temperature'),
                  # Match any flow value:
                  f (regexp="(?P<var>.*/FLOW)\s+(?P<value>\d+)", parse=int, kind='flow'),
                 ],
            ]
            if updateAllData:
                show_data[1] += [
                    # Match any software version:
                    f (regexp="(?P<var>SOFTWARE.*/\w*)\s*(?P<value>\S+)\s*"),
                    # Finally, match any variable/value on separate lines:
                    f (regexp="(?P<var>.*)/\s*(?P<value>.*\w)\s*"),
                ]
            scan_menu += show_data
        scanData, scanMetaData = self.scanMenu (scan_menu, data=self.data.copy(), meta_data = self.metaData.copy())
        scanData['LED'] = self.led()
        self.data = scanData
        self.metaData = scanMetaData
        return self.data

    def updateData (self, updateDisplayData):
        return self.scanData (updateShowData = updateDisplayData)
        
    def scanCooling (self):
        """ Scan the COOLING menu """
        def intOrOff (x):
            return int(x) if x != 'OFF' else None
                
        f = dict
        return self.scanMenu ([
            _scanner_reset_menu(),
            _scanner_search_menu (Key.DOWN, "COOLING"),
            Key.ENTER,
            [ (Key.DOWN, ""),
              f (regexp="TEMP.*/SET\s*(?P<value>\S+)", var='coolingTemp', parse=intOrOff),
              f (regexp="VENT.*/HIGH\s+(?P<value>\w+)", var='coolingVentilationHigh', parse=intOrOff)
             ]
        ])
    
    def scanServiceMenu (self):
        """ Requires that service menu is enabled. """
        f = dict
        return self.scanMenu ([
            _scanner_reset_menu(),
            _scanner_search_menu (Key.DOWN, "SERVICE"),
            Key.ENTER,
            [ (Key.DOWN, ""),
              f (regexp="AIR/EXCHANGE",
                 then=[ Key.ENTER,
                        [ (Key.DOWN, "AIR_"),
                          f (regexp="(?P<var>[\w/<>]+)\s+(?P<value>\d+)%", parse=int, kind='%'),
                          f (regexp="(?P<var>[\w/<>]+)\s+(?P<value>\d+)", parse=int),
                          f (regexp=".*")
                         ],
                        Key.ESC]),
              f (regexp="DEFROST",
                 then=[ Key.ENTER,
                        [ (Key.NONE, "DEFROST_"),
                          f (regexp="(?P<var>.+?)(?P<value>[\w.]+)$")
                         ],
                        Key.ESC
                       ]
                 ),
              f (regexp=".*")
             ]
        ])
    
    def setThermostat (self, celsius):
        """ Set thermostat to CELSIUS degrees. """
        def getBlinkText (string):
            return string[string.find('{')+1:string.find('}')].strip()

        if not 5 <= celsius <= 30:
            raise Exception (f'Illegal thermostat value: {celsius}')

        currentThermostat = parseCelsius(self.resetMenu())
        if f'{currentThermostat}' != getBlinkText (self.key_enter()):
            x = self.key()
            raise Exception ('Failed to enter thermostat input mode.', x, getBlinkText (x))
        if celsius > currentThermostat:
            for _ in range (0, celsius - currentThermostat):
                self.key_up()
        elif celsius < currentThermostat:
            for _ in range (0, currentThermostat - celsius):
                self.key_down()
        return self.key_enter()

    def setFlow (self, flow):
        """ Set fan flow level to FLOW, i.e. 1-4. """
        def getBlinkText (string):
            return string[string.find('{')+1:string.find('}')].strip()

        if not 1 <= flow <= 4:
            raise Exception (f'Illegal flow value: {flow}')

        currentFlow = parseFlow(self.resetMenu())
        self.key_enter() # thermostat
        self.key_enter() # heat/cool mode
        if f'>{currentFlow}<' != getBlinkText (self.key_enter()):
            x = self.key()
            raise Exception ('Failed to flow input mode.', x, getBlinkText (x))
        if flow > currentFlow:
            for _ in range (0, flow - currentFlow):
                self.key_up()
        elif flow < currentFlow:
            for _ in range (0, currentFlow - flow):
                self.key_down()
        self.key_enter() # commit value
        return self.key()

    def setLanguage (self, language):
        """ Set CTS600 display language to the first language that matches LANGUAGE. """
        def getBlinkText (string):
            return string[string.find('{')+1:string.find('}')].strip()

        self.resetMenu ()
        self.key_down (repeat=8)
        # Cycle all the way up, then all the way down searching for LANGUAGE.
        if (cycleToMenuEnd (getBlinkText(self.key_enter ()),
                            lambda: getBlinkText(self.key_up()),
                            match=language)
            or cycleToMenuEnd (getBlinkText(self.display ()),
                               lambda: getBlinkText(self.key_down()),
                               match=language)):
            self.key_enter() # commit
            return True
        else:
            self.key_esc()
            return False
        
    def setMode (self, mode):
        """ Set operation mode to MODE, i.e. HEAT, COOL, or AUTO. """
        # ordering of all_modes is important; it corresponds to CTS600
        # menu up to down.
        all_modes = ['AUTO', 'COOL', 'HEAT']
        if not mode in all_modes:
            raise Exception (f'Illegal operation mode: {mode}')
        mode_index = all_modes.index (mode)
        # operate menu based on mode position, so as to operate
        # independent of CTS600 language setting.
        self.resetMenu()
        self.key_enter() # thermostat
        self.key_enter() # mode
        # now ensure we're at topmost mode, i.e. 'AUTO'
        self.key_up()
        self.key_up()
        self.key_up()
        for _ in range (mode_index):
            self.key_down ()
        self.key_enter () # commit value
        return self.key()
    
    def setT15 (self, celsius):
        """ Set the T15 room sensor temperature. """
        adtemp = nilanCelsiusToAD (celsius)
        self.log ('setT15: %s -> %s', celsius, adtemp)
        self.wi_ro_regs (0x2a, adtemp)
        self._t15_adtemp = adtemp

    def getT15 (self):
        """ Get the previously set T15 room sensor temperature, in celsius. """
        return nilanADToCelsius (self._t15_adtemp) if self._t15_adtemp else None

    def enable_service_menu (self):
        """ Enable the CTS600 service menu by pressing down and enter for 10 seconds. """
        import time
        self.wi_ro_regs (0x100, int (Key.DOWN + Key.ENTER))
        self.wi_ro_regs (0x100, int (Key.DOWN + Key.ENTER))
        time.sleep (10)
        self.wi_ro_regs (0x100, int (Key.NONE))
        return self.display()
        
    
class CTS600Mockup (CTS600):
    """ A no-op pseudo-device just for testing and debugging. """
    mockup_data = {'thermostat': 21,
                   'mode': 'COOL',
                   'flow': 2,
                   'status': 'COOLING',
                   'T15': 23,
                   'T2': 6,
                   'T1': 16,
                   'T5': 4,
                   'T6': 39,
                   'inletFlow': 2,
                   'exhaustFlow': 2,
                   'LED': 'on'}
    mockup_slave_id = {'slaveID': 16,
                       'runStatus': 1,
                       'errorStatus': 0,
                       'resetStatus': 1,
                       'protocolVersion': 100,
                       'softwareVersion': 131,
                       'softwareDate': 0,
                       'softwareTime': 0,
                       'product': b'6551720001',
                       'numofOutputBits': 0,
                       'numofLEDs': 0,
                       'numofInputBits': 0,
                       'numofKeys': 0,
                       'numofOutputRegisters': 0,
                       'numofInputRegisters': 0,
                       'reserved': b'\x00\x00',
                       'numofActions': 0,
                       'displayRows': 2,
                       'displayColumns': 8,
                       'displayType': 1,
                       'displayDataType': 1}
    slave_id = None
    
    def doRequest (self, request, requestFrame=[]):
        import time
        time.sleep(0.1)
        pass

    def initialize (self):
        CTS600.initialize (self)
        for i in range (0, 0x200):
            self.output_bits[i] = 0
        import time
        time.sleep (1)
        self.slave_id = self.mockup_slave_id
    
    def connect (self):
        pass

    def setThermostat (self, celsius):
        self.data['thermostat'] = celsius
        return ""

    def setMode (self, mode):
        pass

    def slaveID (self):
        """ Output from my VPL-15 """
        return self.slave_id

    def updateData (self, updateDisplayData):
        import threading, time
        def doit ():
            time.sleep (2 if updateDisplayData else 6)
            self.data = self.mockup_data
        threading.Thread (target=doit).start()

def test(port=None):
    port = port or findUSB()
    print (f"port: {port}")
    client = ModbusSerialClient(port=port, baudrate=19200, parity='N', stopbits=2, bytesize=8)
    cts600 = CTS600(client=client)
    cts600.connect()
    cts600.initialize()
    slaveID = cts600.slaveID()
    print ('CTS600: ', slaveID)
    cts600.key ()
    return cts600

def t2 (x):
    a,b,*c = x
    print (f"a: {a}, b: {b}, c: {c}")
    return a,b,c
