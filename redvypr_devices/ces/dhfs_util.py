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


description = 'Utils for digital heat flow sensors'


logging.basicConfig(stream=sys.stderr)
logger = logging.getLogger('dhfs_util')
logger.setLevel(logging.DEBUG)

class DeviceBaseConfig(pydantic.BaseModel):
    publishes: bool = True
    subscribes: bool = True
    description: str = 'Utils for digital heat flow sensors'
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


class initDeviceWidget(QtWidgets.QWidget):
    def __init__(self, device=None):
        super(QtWidgets.QWidget, self).__init__()
        layout = QtWidgets.QVBoxLayout(self)
        self.device = device
        self.serialwidget = QtWidgets.QWidget()
        self.init_serialwidget()
        self.label = QtWidgets.QLabel("Serial device")
        # self.startbtn = QtWidgets.QPushButton("Open device")
        # self.startbtn.clicked.connect(self.start_clicked)
        # self.stopbtn = QtWidgets.QPushButton("Close device")
        # self.stopbtn.clicked.connect(self.stop_clicked)
        layout.addWidget(self.label)
        layout.addWidget(self.serialwidget)
        # layout.addWidget(self.startbtn)
        # layout.addWidget(self.stopbtn)

    def init_serialwidget(self):
        """Fills the serial widget with content
        """
        layout = QtWidgets.QGridLayout(self.serialwidget)
        # Serial baud rates
        baud = [300, 600, 1200, 2400, 4800, 9600, 19200, 38400, 57600, 115200, 576000, 921600]
        self._combo_serial_devices = QtWidgets.QComboBox()
        # self._combo_serial_devices.currentIndexChanged.connect(self._serial_device_changed)
        self._combo_serial_baud = QtWidgets.QComboBox()
        index_baud = 4
        for ib, b in enumerate(baud):
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

        # How to differentiate packets
        self._packet_ident_lab = QtWidgets.QLabel('Packet identification')
        self._packet_ident = QtWidgets.QComboBox()
        self._packet_ident.addItem('newline \\n')
        self._packet_ident.addItem('newline \\r\\n')
        self._packet_ident.addItem('None')
        # Max packetsize
        self._packet_size_lab = QtWidgets.QLabel("Maximum packet size")
        self._packet_size_lab.setToolTip(
            'The number of received bytes after which a packet is sent.\n Add 0 for no size check')
        onlyInt = QtGui.QIntValidator()
        self._packet_size = QtWidgets.QLineEdit()
        self._packet_size.setValidator(onlyInt)
        self._packet_size.setText('0')
        # self.packet_ident

        layout.addWidget(self._packet_ident, 0, 1)
        layout.addWidget(self._packet_ident_lab, 0, 0)
        layout.addWidget(self._packet_size_lab, 0, 2)
        layout.addWidget(self._packet_size, 0, 3)
        layout.addWidget(QtWidgets.QLabel('Serial device'), 1, 0)
        layout.addWidget(self._combo_serial_devices, 2, 0)
        layout.addWidget(QtWidgets.QLabel('Baud'), 1, 1)
        layout.addWidget(self._combo_serial_baud, 2, 1)
        layout.addWidget(QtWidgets.QLabel('Parity'), 1, 2)
        layout.addWidget(self._combo_parity, 2, 2)
        layout.addWidget(QtWidgets.QLabel('Databits'), 1, 3)
        layout.addWidget(self._combo_databits, 2, 3)
        layout.addWidget(QtWidgets.QLabel('Stopbits'), 1, 4)
        layout.addWidget(self._combo_stopbits, 2, 4)
        layout.addWidget(self._button_serial_openclose, 2, 5)

        self.statustimer = QtCore.QTimer()
        self.statustimer.timeout.connect(self.update_buttons)
        self.statustimer.start(500)

    def update_buttons(self):
        """ Updating all buttons depending on the thread status (if its alive, graying out things)
        """

        status = self.device.get_thread_status()
        thread_status = status['thread_running']

        if (thread_status):
            self._button_serial_openclose.setText('Close')
            self._combo_serial_baud.setEnabled(False)
            self._combo_serial_devices.setEnabled(False)
        else:
            self._button_serial_openclose.setText('Open')
            self._combo_serial_baud.setEnabled(True)
            self._combo_serial_devices.setEnabled(True)

    def start_clicked(self):
        # print('Start clicked')
        button = self._button_serial_openclose
        # print('Start clicked:' + button.text())
        # config_template['comport'] = {'type': 'str'}
        # config_template['baud'] = {'type': 'int', 'default': 4800}
        # config_template['parity'] = {'type': 'int', 'default': serial.PARITY_NONE}
        # config_template['stopbits'] = {'type': 'int', 'default': serial.STOPBITS_ONE}
        # config_template['bytesize'] = {'type': 'int', 'default': serial.EIGHTBITS}
        # config_template['dt_poll'] = {'type': 'float', 'default': 0.05}
        # config_template['chunksize'] = {'type': 'int',
        #                                'default': 1000}  # The maximum amount of bytes read with one chunk
        # config_template['packetdelimiter'] = {'type': 'str',
        #                                      'default': '\n'}  # The maximum amount of bytes read with one chunk
        if ('Open' in button.text()):
            button.setText('Close')
            serial_name = str(self._combo_serial_devices.currentText())
            serial_baud = int(self._combo_serial_baud.currentText())
            self.device.custom_config.comport = serial_name
            self.device.custom_config.baud = serial_baud
            stopbits = self._combo_stopbits.currentText()
            if (stopbits == '1'):
                self.device.custom_config.stopbits = serial.STOPBITS_ONE
            elif (stopbits == '1.5'):
                self.device.custom_config.stopbits = serial.STOPBITS_ONE_POINT_FIVE
            elif (stopbits == '2'):
                self.device.custom_config.stopbits = serial.STOPBITS_TWO

            databits = int(self._combo_databits.currentText())
            self.device.custom_config.bytesize = databits

            parity = self._combo_parity.currentText()
            if (parity == 'None'):
                self.device.custom_config.parity = serial.PARITY_NONE
            elif (parity == 'Even'):
                self.device.custom_config.parity = serial.PARITY_EVEN
            elif (parity == 'Odd'):
                self.device.custom_config.parity = serial.PARITY_ODD
            elif (parity == 'Mark'):
                self.device.custom_config.parity = serial.PARITY_MARK
            elif (parity == 'Space'):
                self.device.custom_config.parity = serial.PARITY_SPACE

            self.device.thread_start()
        else:
            self.stop_clicked()

    def stop_clicked(self):
        button = self._button_serial_openclose
        self.device.thread_stop()
        button.setText('Closing')
        # self._combo_serial_baud.setEnabled(True)
        # self._combo_serial_devices.setEnabled(True)

    def dhfs_command_clicked(self):
        funcname = __name__ + '.dhfs_command_clicked():'
        logger.debug(funcname)
        try:
            calibrationdata = self.device.custom_config.calibrationdata
            coeffs = self.device.custom_config.__calibration_coeffs__
        except Exception as e:
            logger.exception(e)
            logger.debug(funcname)

        for c, cal in zip(coeffs, calibrationdata):
            # print('Coeff', c)
            if 'ntc' in c.parameter.lower():
                coeffstr = ''
                # print('coeff',c.coeff)
                for ctmp in reversed(c.coeff):
                    coeffstr += '{:.6e} '.format(ctmp)
                comstr = '{:s}: set {:s} {:s}'.format(c.sn, c.parameter.lower(), coeffstr)
                # print('Command')
                print(comstr)
            elif 'hf' in c.parameter.lower():
                coeffstr = '{:.3f} '.format(c.coeff)
                comstr = '{:s}: set {:s} {:s}'.format(c.sn, c.parameter.lower(), coeffstr)
                # print('Command')
                print(comstr)
            else:
                logger.info(funcname + ' unknown parameter {:s}'.format(c.parameter))