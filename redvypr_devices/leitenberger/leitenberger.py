import datetime
import logging
import queue
from PyQt5 import QtWidgets, QtCore, QtGui
import time
import numpy as np
import serial
import serial.tools.list_ports
import logging
import sys
import pydantic
from redvypr.data_packets import check_for_command
from redvypr.devices.plot import XYplotWidget
#from redvypr.redvypr_packet_statistic import do_data_statistics, create_data_statistic_dict


description = 'Device to connect to a Leitenberger temperature calibration bath'


logging.basicConfig(stream=sys.stderr)
logger = logging.getLogger('leitenberger')
logger.setLevel(logging.DEBUG)

class DeviceBaseConfig(pydantic.BaseModel):
    publishes: bool = True
    subscribes: bool = True
    description: str = 'Leitenberger temperature bath'
    gui_tablabel_display: str = 'Data'


class DeviceCustomConfig(pydantic.BaseModel):
    baud: int = 9600
    parity: int = serial.PARITY_NONE
    stopbits: int = serial.STOPBITS_ONE
    bytesize: int = serial.EIGHTBITS
    dt_poll: float = 0.05
    chunksize: int = pydantic.Field(default=1000, description='The maximum amount of bytes read with one chunk')
    packetdelimiter: str = pydantic.Field(default='\n', description='The delimiter to distinuish packets')
    comport: str = ''

redvypr_devicemodule = True

def start(device_info, config={}, dataqueue=None, datainqueue=None, statusqueue=None):
    """

    """
    funcname = __name__ + '.start()'
    logger.debug(funcname + ':Starting reading serial data')
    chunksize   = config['chunksize'] #The maximum amount of bytes read with one chunk
    serial_name = config['comport']
    baud        = config['baud']
    parity      = config['parity']
    stopbits    = config['stopbits']
    bytesize    = config['bytesize']
    dt_poll     = config['dt_poll']

    print('Starting',config)
    
    newpacket   = config['packetdelimiter']
    # Check if a delimiter shall be used (\n, \r\n, etc ...)
    if(len(newpacket)>0):
        FLAG_DELIMITER = True
    else:
        FLAG_DELIMITER = False
    if(type(newpacket) is not bytes):
        newpacket = newpacket.encode('utf-8')
        
    rawdata_all    = b''
    dt_update      = 1 # Update interval in seconds
    bytes_read     = 0
    sentences_read = 0
    bytes_read_old = 0 # To calculate the amount of bytes read per second
    t_update       = time.time()
    serial_device = False
    if True:
        try:
            serial_device = serial.Serial(serial_name,baud,parity=parity,stopbits=stopbits,bytesize=bytesize,timeout=0)
            #print('Serial device 0',serial_device)
            #serial_device.timeout(0.05)
            #print('Serial device 1',serial_device)                        
        except Exception as e:
            #print('Serial device 2',serial_device)
            logger.debug(funcname + ': Exception open_serial_device {:s} {:d}: '.format(serial_name,baud) + str(e))
            return False

    got_dollar = False    
    while True:
        # TODO, here commands could be send as well
        try:
            data = datainqueue.get(block=False)
        except:
            data = None
        if (data is not None):
            command = check_for_command(data, thread_uuid=device_info['thread_uuid'])
            logger.debug('Got a command: {:s}'.format(str(data)))

            if (command is not None):
                print('Command', command)
                if command == 'stop':
                    serial_device.close()
                    sstr = funcname + ': Command is for me: {:s}'.format(str(command))
                    logger.debug(sstr)
                    try:
                        statusqueue.put_nowait(sstr)
                    except:
                        pass
                    return
                elif command == 'set':
                    print('Set temperature')
                    temp = data['temp']
                    WRITE_SET_TEMP_COM = '$1WVAR0 {}'.format(temp)
                    WRITE_SET_TEMP_COM = WRITE_SET_TEMP_COM.replace('.',',')
                    print('Write command',WRITE_SET_TEMP_COM)
                    serial_device.write(WRITE_SET_TEMP_COM.encode() + b' \r')
                    time.sleep(0.1)
                    ndata = serial_device.inWaiting()
                    try:
                        rawdata_tmp = serial_device.read(ndata)
                    except Exception as e:
                        print(e)
                        # print('rawdata_tmp', rawdata_tmp)

        if((time.time() - t_update) > dt_update):
            # Read the set temperature value
            READ_SET_TEMP_COM = b'$1RVAR0 \r'
            print('Writing', READ_SET_TEMP_COM)
            serial_device.write(READ_SET_TEMP_COM)
            time.sleep(0.1)
            ndata = serial_device.inWaiting()
            try:
                rawdata_tmp = serial_device.read(ndata)
            except Exception as e:
                print(e)
                # print('rawdata_tmp', rawdata_tmp)

            data = {}
            print('SET TEMP', rawdata_tmp)
            try:
                rawstr = rawdata_tmp.decode('UTF-8')
                temp_set = float(rawstr.split()[1])
                data['temp_set'] = temp_set
            except:
                logger.warning('Could not parse String:{}'.format(rawstr), exc_info=True)
                temp_set = None


            # And now the real temperature
            READ_TEMP_COM = b'$1RVAR100 \r'
            print('Writing', READ_TEMP_COM)
            serial_device.write(READ_TEMP_COM)
            time.sleep(0.1)
            ndata = serial_device.inWaiting()
            try:
                rawdata_tmp = serial_device.read(ndata)
            except Exception as e:
                print(e)
                #print('rawdata_tmp', rawdata_tmp)

            print('READ TEMP', rawdata_tmp)
            #b'*1 +0023.18\r'

            try:
                rawstr = rawdata_tmp.decode('UTF-8')
                temp = float(rawstr.split()[1])
                data['temp'] = temp
            except:
                logger.warning('Could not parse String:{}'.format(rawstr),exc_info=True)
                temp = None

            # Read the symbol of steadiness
            READ_TEMP_COM = b'$1RVAR29 \r'
            print('Writing', READ_TEMP_COM)
            serial_device.write(READ_TEMP_COM)
            time.sleep(0.1)
            ndata = serial_device.inWaiting()
            try:
                rawdata_tmp = serial_device.read(ndata)
            except Exception as e:
                print(e)
                # print('rawdata_tmp', rawdata_tmp)

            print('READ Steadiness', rawdata_tmp)
            # b'*1 1\r'

            try:
                rawstr = rawdata_tmp.decode('UTF-8')
                steady = int(rawstr.split()[1])
                data['temp_steady'] = steady
            except:
                logger.warning('Could not parse String:{}'.format(rawstr), exc_info=True)

            # Read the stability range
            READ_TEMP_COM = b'$1RVAR28 \r'
            print('Writing', READ_TEMP_COM)
            serial_device.write(READ_TEMP_COM)
            time.sleep(0.1)
            ndata = serial_device.inWaiting()
            try:
                rawdata_tmp = serial_device.read(ndata)
            except Exception as e:
                print(e)
                # print('rawdata_tmp', rawdata_tmp)

            print('READ Stability', rawdata_tmp)
            # b'*1 1\r'

            try:
                rawstr = rawdata_tmp.decode('UTF-8')
                stability = float(rawstr.split()[1])
                data['temp_stability'] = stability
            except:
                logger.warning('Could not parse String:{}'.format(rawstr), exc_info=True)


            print('Data',data)
            dataqueue.put(data)
            t_update = time.time()

            
                





class initDeviceWidget(QtWidgets.QWidget):
    def __init__(self,device=None):
        super(QtWidgets.QWidget, self).__init__()
        layout        = QtWidgets.QVBoxLayout(self)
        self.device   = device
        self.serialwidget = QtWidgets.QWidget()
        self.init_serialwidget()
        self.label    = QtWidgets.QLabel("Serial device")
        #self.startbtn = QtWidgets.QPushButton("Open device")
        #self.startbtn.clicked.connect(self.start_clicked)
        #self.stopbtn = QtWidgets.QPushButton("Close device")
        #self.stopbtn.clicked.connect(self.stop_clicked)
        layout.addWidget(self.label)        
        layout.addWidget(self.serialwidget)
        #layout.addWidget(self.startbtn)
        #layout.addWidget(self.stopbtn)
        
    def init_serialwidget(self):
        """Fills the serial widget with content
        """
        layout = QtWidgets.QGridLayout(self.serialwidget)
        # Serial baud rates
        baud = [300,600,1200,2400,4800,9600,19200,38400,57600,115200,576000,921600]
        self._combo_serial_devices = QtWidgets.QComboBox()
        #self._combo_serial_devices.currentIndexChanged.connect(self._serial_device_changed)
        self._combo_serial_baud = QtWidgets.QComboBox()
        index_baud = 4
        for ib,b in enumerate(baud):
            if b == self.device.custom_config.baud:
                index_baud = ib
            self._combo_serial_baud.addItem(str(b))

        self._combo_serial_baud.setCurrentIndex(index_baud)
        # creating a line edit
        edit = QtWidgets.QLineEdit(self)
        onlyInt = QtGui.QIntValidator()
        edit.setValidator(onlyInt)
  
        # setting line edit
        self._combo_serial_baud.setLineEdit(edit)
        
        self._combo_parity = QtWidgets.QComboBox()
        self._combo_parity.addItem('None')
        self._combo_parity.addItem('Odd')
        self._combo_parity.addItem('Even')
        self._combo_parity.addItem('Mark')
        self._combo_parity.addItem('Space')
        
        self._combo_stopbits = QtWidgets.QComboBox()
        self._combo_stopbits.addItem('1')
        self._combo_stopbits.addItem('1.5')
        self._combo_stopbits.addItem('2')
        
        self._combo_databits = QtWidgets.QComboBox()
        self._combo_databits.addItem('8')
        self._combo_databits.addItem('7')
        self._combo_databits.addItem('6')
        self._combo_databits.addItem('5')
        
        self._button_serial_openclose = QtWidgets.QPushButton('Open')
        self._button_serial_openclose.clicked.connect(self.start_clicked)


        # Check for serial devices and list them
        for comport in serial.tools.list_ports.comports():
            self._combo_serial_devices.addItem(str(comport.device))

        #How to differentiate packets
        self._packet_ident_lab = QtWidgets.QLabel('Packet identification')
        self._packet_ident = QtWidgets.QComboBox()
        self._packet_ident.addItem('newline \\n')
        self._packet_ident.addItem('newline \\r\\n')
        self._packet_ident.addItem('None')
        # Max packetsize
        self._packet_size_lab   = QtWidgets.QLabel("Maximum packet size")
        self._packet_size_lab.setToolTip('The number of received bytes after which a packet is sent.\n Add 0 for no size check')
        onlyInt = QtGui.QIntValidator()
        self._packet_size       = QtWidgets.QLineEdit()
        self._packet_size.setValidator(onlyInt)
        self._packet_size.setText('0')
        #self.packet_ident

        layout.addWidget(self._packet_ident,0,1)
        layout.addWidget(self._packet_ident_lab,0,0)
        layout.addWidget(self._packet_size_lab,0,2)
        layout.addWidget(self._packet_size,0,3)
        layout.addWidget(QtWidgets.QLabel('Serial device'),1,0)
        layout.addWidget(self._combo_serial_devices,2,0)
        layout.addWidget(QtWidgets.QLabel('Baud'),1,1)
        layout.addWidget(self._combo_serial_baud,2,1)
        layout.addWidget(QtWidgets.QLabel('Parity'),1,2)  
        layout.addWidget(self._combo_parity,2,2) 
        layout.addWidget(QtWidgets.QLabel('Databits'),1,3)  
        layout.addWidget(self._combo_databits,2,3) 
        layout.addWidget(QtWidgets.QLabel('Stopbits'),1,4)  
        layout.addWidget(self._combo_stopbits,2,4) 
        layout.addWidget(self._button_serial_openclose,2,5)

        self.statustimer = QtCore.QTimer()
        self.statustimer.timeout.connect(self.update_buttons)
        self.statustimer.start(500)
        
    
    def update_buttons(self):
        """ Updating all buttons depending on the thread status (if its alive, graying out things)
        """

        status = self.device.get_thread_status()
        thread_status = status['thread_running']

        if(thread_status):
            self._button_serial_openclose.setText('Close')
            self._combo_serial_baud.setEnabled(False)
            self._combo_serial_devices.setEnabled(False)
        else:
            self._button_serial_openclose.setText('Open')
            self._combo_serial_baud.setEnabled(True)
            self._combo_serial_devices.setEnabled(True)
        
            
    def start_clicked(self):
        #print('Start clicked')
        button = self._button_serial_openclose
        #print('Start clicked:' + button.text())
        #config_template['comport'] = {'type': 'str'}
        #config_template['baud'] = {'type': 'int', 'default': 4800}
        #config_template['parity'] = {'type': 'int', 'default': serial.PARITY_NONE}
        #config_template['stopbits'] = {'type': 'int', 'default': serial.STOPBITS_ONE}
        #config_template['bytesize'] = {'type': 'int', 'default': serial.EIGHTBITS}
        #config_template['dt_poll'] = {'type': 'float', 'default': 0.05}
        #config_template['chunksize'] = {'type': 'int',
        #                                'default': 1000}  # The maximum amount of bytes read with one chunk
        #config_template['packetdelimiter'] = {'type': 'str',
        #                                      'default': '\n'}  # The maximum amount of bytes read with one chunk
        if('Open' in button.text()):
            button.setText('Close')
            serial_name = str(self._combo_serial_devices.currentText())
            serial_baud = int(self._combo_serial_baud.currentText())
            self.device.custom_config.comport = serial_name
            self.device.custom_config.baud = serial_baud
            stopbits = self._combo_stopbits.currentText()
            if(stopbits=='1'):
                self.device.custom_config.stopbits =  serial.STOPBITS_ONE
            elif(stopbits=='1.5'):
                self.device.custom_config.stopbits =  serial.STOPBITS_ONE_POINT_FIVE
            elif(stopbits=='2'):
                self.device.custom_config.stopbits =  serial.STOPBITS_TWO
                
            databits = int(self._combo_databits.currentText())
            self.device.custom_config.bytesize = databits

            parity = self._combo_parity.currentText()
            if(parity=='None'):
                self.device.custom_config.parity = serial.PARITY_NONE
            elif(parity=='Even'):                
                self.device.custom_config.parity = serial.PARITY_EVEN
            elif(parity=='Odd'):                
                self.device.custom_config.parity = serial.PARITY_ODD
            elif(parity=='Mark'):                
                self.device.custom_config.parity = serial.PARITY_MARK
            elif(parity=='Space'):                
                self.device.custom_config.parity = serial.PARITY_SPACE
                

            self.device.thread_start()
        else:
            self.stop_clicked()

    def stop_clicked(self):
        button = self._button_serial_openclose
        self.device.thread_stop()
        button.setText('Closing') 
        #self._combo_serial_baud.setEnabled(True)
        #self._combo_serial_devices.setEnabled(True)      

class displayDeviceWidget(QtWidgets.QWidget):
    def __init__(self,device=None):
        super(QtWidgets.QWidget, self).__init__()
        layout = QtWidgets.QVBoxLayout(self)
        hlayout = QtWidgets.QHBoxLayout()
        self.tempSpinBox = QtWidgets.QDoubleSpinBox()
        self.tempSpinBox.setValue(10)
        self.buttonSendcom = QtWidgets.QPushButton('Send')
        self.buttonSendcom.clicked.connect(self.sendcom_clicked)
        config = XYplotWidget.configXYplot()
        self.device = device
        self.plotWidget = XYplotWidget.XYplot(config=config, redvypr_device=self.device)
        self.plotWidget.set_line(0,y_addr='/k:temp',name='leitenberger')
        self.plotWidget.config.lines[0].unit = 'degC'
        self.plotWidget.add_line(y_addr='/k:temp_set',color='black',name='leitenberger')
        self.plotWidget.config.lines[1].unit = 'degC'
        hlayout.addWidget(self.tempSpinBox)
        hlayout.addWidget(self.buttonSendcom)
        layout.addLayout(hlayout)
        layout.addWidget(self.plotWidget)
        layout.addStretch()

    def sendcom_clicked(self):
        print('Sending command')
        temp = self.tempSpinBox.value()
        self.device.thread_command('set',data={'temp':temp})
    def update_data(self,data):
        funcname = __name__ + '.update():'
        print('data',data)
        self.plotWidget.update_plot(data)

        
