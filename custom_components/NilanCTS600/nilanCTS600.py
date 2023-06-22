
import codecs, struct, time
from enum import Enum
from pymodbus.client import ModbusSerialClient
from pymodbus.utilities import computeCRC

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
    
def parseCelcius (string):
    return parseLastNumber(string[0:string.find('°C')])

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
    return 59.3 - (advalue * (10 / (262 - 195)))

def nilanCelsiusToAD (celsius):
    """ Convert Celsius to AD temperature sensor value. """
    return int ((59.3 - celsius) / (10 / (262 - 195)))

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
    op = NilanOperators(function_code)
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
        
    def __init__(self, client, unit=3, rows=2, columns=8):
        self.client = client
        self.unit = unit
        self.output_registers = [0] * 0x300
        self.output_bits = dict()
        self.crc_fails = 0
        self.slave_id_data = None
        self.rows = rows
        self.columns = columns
        self.data = {}

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
        time.sleep (0.05)
        # while self.client.recv(1):
        #     pass
        self.send(reqOP, requestFrame)
        (ackOP, parameters, data, crcOK) = read_response(self.client.recv)
        if (not crcOK):
            self.crc_fails += 1
            print (f'CRC Fail! {request}')
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
        # print('SEND: %s' % ['#x%02x' % x for x in f])
        return self.client.send(bytes(f))

    def ack_report_slave_id (self, op, parameters, data, request=None):
        self.slave_id_data = data

    def ack_read_multiple_holding_registers (self, op, parameters, data, request=None):
        (reqOP, address, count) = request or (None, None)
        if address is not None and count is not None:
            values = [word16(data, i*2) for i in range(0, count)]
            print (f"read multiple: #x{address:04x}, {values}")
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

    def key (self, key=0):
        self.wi_ro_regs (0x100, key)
        self.wi_ro_regs (0x100, key)
        self.wi_ro_regs (0x100, 0)
        return self.display()

    def esc (self):
        return self.key (0x01)
    
    def up (self):
        return self.key(0x02)

    def down (self):
        return self.key(0x04)

    def enter (self):
        self.wi_ro_regs (0x100, 8)
        self.wi_ro_regs (0x100, 8)
        self.wi_ro_regs (0x100, 0)
        return self.display()

    def off (self):
        return self.key (0x10)

    def on (self):
        return self.key (0x20)

    def displayRow (self, row, startBlink='{', endBlink='}'):
        bytesPerRow = self.columns + int(self.columns/4)
        startRegister = 0x200 + row*bytesPerRow
        return nilanStringApplyAttribute(
            nilanString(bytes(cts600.output_registers[startRegister:startRegister+self.columns])),
            cts600.output_registers[startRegister+self.columns:startRegister+bytesPerRow],
            startBlink=startBlink,
            endBlink=endBlink)
    
    def display (self):
        return " ".join ([self.displayRow (r).strip() for r in range (0, self.rows)])

    def led (self):
        return {0: 'off', 1: 'on', 2: 'unknown', 3: 'blink'}[self.output_bits[0x100] & 0x03]

    def updateData (self):
        """ Cycle through the "SHOW DATA" menu and record the relevant values.
        """
        trace = []
        newData = dict()

        def go (x):
            trace.append(x)

        go (self.esc())
        go (self.esc())
        go (self.esc())
        newData['thermostatTxt'] = trace[-1]
        newData['thermostat'] = parseCelcius(newData['thermostatTxt'])
        go (self.up())
        go (self.enter())
        newData['statusTxt'] = trace[-1]
        newData['status'] = newData['statusTxt'].split(None, 2)[1]
        go (self.down())
        newData['T15Txt'] = trace[-1]
        newData['T15'] = parseCelcius (newData['T15Txt'])
        go (self.down())
        newData['T2Txt'] = trace[-1]
        newData['T2'] = parseCelcius (newData['T2Txt'])
        go (self.down())
        newData['T1Txt'] = trace[-1]
        newData['T1'] = parseCelcius (newData['T1Txt'])
        go (self.down())
        newData['T5Txt'] = trace[-1]
        newData['T5'] = parseCelcius (newData['T5Txt'])
        go (self.down())
        newData['T6Txt'] = trace[-1]
        newData['T6'] = parseCelcius (newData['T6Txt'])
        go (self.down())
        newData['inletFlowTxt'] = trace[-1]
        newData['inletFlow'] = parseLastNumber (newData['inletFlowTxt'])
        go (self.down())
        newData['exhaustFlowTxt'] = trace[-1]
        newData['exhaustFlow'] = parseLastNumber (newData['exhaustFlowTxt'])
        newData['trace'] = trace
        self.data = newData
        return newData

    def setThermostat (self, celcius):
        """ Set thermostat degrees. """
        def getBlinkText (string):
            return string[string.find('{')+1:string.find('}')].strip()

        if not 5 <= celcius <= 50:
            raise Exception (f'Illegal thermostat value: {celcius}')

        self.esc()
        self.esc()
        currentThermostat = parseCelcius(self.esc())
        if f'{currentThermostat}' != getBlinkText (self.enter()):
            x = self.key()
            raise Exception ('Failed to enter thermostat enter mode.', x, getBlinkText (x))
        if celcius > currentThermostat:
            for _ in range (0, celcius - currentThermostat):
                self.up()
        elif celcius < currentThermostat:
            for _ in range (0, currentThermostat - celcius):
                self.down()
        self.enter()
        self.data['thermostatTxt'] = self.esc()
        self.data['thermostat'] = parseCelcius (self.data['thermostatTxt'])
        return self.data['thermostat']

    def setT15 (self, celcius):
        """ Set the T15 room sensor temperature. """
        self.wi_ro_regs (0x2a, nilanCelsiusToAD (celcius))
        
    
def test(port="/dev/ttyUSB0"):
    client = ModbusSerialClient(port=port, baudrate=19200, parity='N', stopbits=2, bytesize=8)
    client.connect()
    cts600 = CTS600(client)

    client.framer.resetFrame()
    cts600.doRequest(NilanOperators.REPORT_SLAVE_ID)
    slaveID = cts600.slaveID()
    print ('CTS600: ', slaveID)
    cts600.read_holding_registers (0x102, 1)
    cts600.preset_single_register (0x104, cts600.remote_version)
    cts600.key ()
    return cts600

