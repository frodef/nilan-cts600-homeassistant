
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
    """ Apply string attribute, i.e. blinking, according to bits in attributeData. """
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

def nilanADToCelsius (advalue):
    """ Convert AD temperature sensor value to celsius. """
    return 57.5 - (advalue * ((34 - 12) / (328 - 168)))

def nilanCelsiusToAD (celsius):
    """ Convert Celsius to AD temperature sensor value. """
    return round ((57.5 - celsius) / ((34 - 12) / (328 - 168)))

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

def read_request (recv):
    slave = word8(recv)
    function_code = word8(recv)
    op = NilanOperators(function_code)
    data_size = None
    parameters = ()
    
    if (op == NilanOperators.REPORT_SLAVE_ID):
        data_size = 0
    elif (op == NilanOperators.WI_RO_REGS):
        parameters = (word16(recv), word16(recv))
        data_size = word16(recv)
    elif (op in (NilanOperators.READ_DISCRETE_INPUTS, NilanOperators.READ_MULTIPLE_HOLDING_REGISTERS, NilanOperators.PRESET_SINGLE_REGISTER)):
        data_size = 4
    else:
        raise Exception(f"Unknown request op {op}")

    data = recv(data_size)
    crc = word16b(recv)

    print(f'REQ: {op} : {parameters} : {data}')
    
    return op.name, parameters, data, crc

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
        self.dataText = {}
        self._data_trace = []

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
        # time.sleep (0.05)
        # while self.client.recv(1):
        #     pass
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
            print(f'Warning: No ack handler for op {ackOP}.')
    
    def send (self, op, frame):
        """Transmit OP to SELF.UNIT and then remaining FRAME."""
        f = [self.unit, op.value] + frame
        f = appendCRC(f)
        # self.log('SEND: %s', ['#x%02x' % x for x in f])
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
            print (f'ack_preset_single_register mismatch: {request} -> {parameters}')

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
        
    def key (self, key=0):
        """Transmit a keypress message to CTS600. KEY is a bitmap of
        the keys pressed. CTS600 will respond with more or less random
        register updates, and a zero KEY bitmap is effectively a
        generic request for state update from CTS600.

        """
        self.wi_ro_regs (0x100, key)
        if key != 0:
            self.wi_ro_regs (0x100, key)
            self.wi_ro_regs (0x100, 0)
        return self.display()

    def key_esc (self):
        return self.key (0x01)
    
    def key_up (self, repeat=1):
        for _ in range (repeat-1):
            self.key (0x02)
        return self.key(0x02)

    def key_down (self, repeat=1):
        for _ in range(repeat-1):
            self.key (0x04)
        return self.key(0x04)

    def key_enter (self):
        return self.key (0x08)

    def key_off (self):
        return self.key (0x10)

    def key_on (self):
        return self.key (0x20)

    def resetMenu (self, maxTries=10):
        """ Put CTS600 in default state, by pressing ESC sufficiently many times. """
        return cycleToMenuEnd (None, lambda: self.key_esc())

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
    
    def display (self):
        return " ".join ([self.displayRow (r).strip() for r in range (0, self.rows)])

    def led (self):
        return {0: 'off', 1: 'on', 2: 'unknown', 3: 'blink'}[self.output_bits[0x100] & 0x03]

    def updateData (self):
        """ Cycle through the "SHOW DATA" menu and record the relevant values.
        """
        newData = dict() # Record fresh data values here.
        newTrace = [] # Record the menu displays we cycle through.
        newDataText = dict() # Record the display texts each data value is based on here.

        def go (x, prop=None):
            """Assuming X is the current display string, append X to
            TRACE and if PROP is given then insert X into newDataText
            too. Return X."""
            if prop:
                newDataText[prop] = x
            newTrace.append(x)
            return x

        # First record the three values from the top-level menu display:
        newData['thermostat'] = parseCelsius(go(self.resetMenu(), 'thermostat'))
        newData['mode'] = go (self.display(), 'mode').split (None, 2)[0]
        newData['flow'] = parseFlow (go (self.display(), 'flow'))
        # Now enter the DISPLAY DATA menu and record the various data entries:
        go (self.key_up())
        newData['status'] = go(self.key_enter(), 'status').split(None, 2)[1]
        newData['T15'] = parseCelsius (go(self.key_down(), 'T15'))
        newData['T2'] = parseCelsius (go(self.key_down(), 'T2'))
        newData['T1'] = parseCelsius (go(self.key_down(), 'T1'))
        newData['T5'] = parseCelsius (go(self.key_down(), 'T5'))
        newData['T6'] = parseCelsius (go(self.key_down(), 'T6'))
        newData['inletFlow'] = parseLastNumber (go(self.key_down(), 'inletFlow'))
        newData['exhaustFlow'] = parseLastNumber (go(self.key_down(), 'exhaustFlow'))
        # Record the state of the status LED
        newData['LED'] = self.led()
        self.data = newData
        self.dataText = newDataText
        self._data_trace = newTrace
        return newData

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
        self.log ('setT15: %s -> %s', celsius, nilanCelsiusToAD (celsius))
        self.wi_ro_regs (0x2a, nilanCelsiusToAD (celsius))
        
    
def test(port=None):
    port = port or findUSB()
    client = ModbusSerialClient(port=port, baudrate=19200, parity='N', stopbits=2, bytesize=8)
    cts600 = CTS600(client=client)
    cts600.connect()
    cts600.initialize()
    slaveID = cts600.slaveID()
    print ('CTS600: ', slaveID)
    cts600.key ()
    return cts600

