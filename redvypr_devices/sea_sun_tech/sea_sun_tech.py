import datetime
import logging
import queue
from PyQt6 import QtWidgets, QtCore, QtGui
import time
import numpy as np
import serial
import serial.tools.list_ports
import logging
import sys
import pydantic
import typing
from pathlib import Path
import multiprocessing
import threading
from redvypr.data_packets import create_datadict
from redvypr.redvypr_address import RedvyprAddress
from redvypr.widgets.standard_device_widgets import RedvyprdevicewidgetSimple
from redvypr.devices.interface.serial_single import SerialDeviceConfig, SerialDeviceWidget
from redvypr.data_packets import check_for_command
from redvypr.devices.plot import XYPlotWidget
from .sea_sun_tech_config import SstDeviceConfig
from .sea_sun_tech_hhl import HHL, pop_channel_sequence

description = 'Device to connect to Sea and Sun Technology CTD and MSS devices'


logging.basicConfig(stream=sys.stderr)
logger = logging.getLogger('redvypr_devices.sea_sun_tech')
logger.setLevel(logging.DEBUG)

class DeviceBaseConfig(pydantic.BaseModel):
    publishes: bool = True
    subscribes: bool = True
    description: str = 'Sea and Sun Technology devices'
    gui_tablabel_display: str = 'Data'


class DeviceCustomConfig(pydantic.BaseModel):
    input_type: typing.Literal["serial","datastream","file"] = pydantic.Field(default = "serial", description='The input data for the device')
    input_datastream: RedvyprAddress = pydantic.Field(default = RedvyprAddress("data@"), description='The redvypr address for the input_type "datastream"')
    input_serial: SerialDeviceConfig = pydantic.Field(
        default_factory=SerialDeviceConfig,
        description='The serial device config for the input_type "serial"')
    input_file: Path = pydantic.Field(default=".",description="Path of the input file")
    #sst_device: typing.Optional[SstDeviceConfig] = pydantic.Field(default = None, description='The device config')
    prbfile: typing.Optional[Path] = pydantic.Field(default=None,description="Path to the .prb file")
    probe_type: typing.Literal["mss","ctm"] = pydantic.Field(default="ctm",description="Type of the sensor probe")
    dt_poll_serial: float = pydantic.Field(default=0.01,description="Polling interval for the serial port")
    raw_data_device_offset: int = pydantic.Field(default=0,description="Offset of the device")


redvypr_devicemodule = True



def read_serial(config, data_queue, data_queue_in):
    # Setup serial connection
    baud = config["input_serial"]["baud"]
    bits_per_byte = 10
    port = config["input_serial"]["comport_device"]
    ser = serial.Serial(
        port=port,
        baudrate=baud,
        parity=serial.PARITY_ODD,  # Odd Parity
        stopbits=serial.STOPBITS_ONE,  # Standard: 1 Stopbit
        bytesize=serial.EIGHTBITS,  # 8 Datenbits
        timeout=1
    )
    if False:
        baud = 2400
        bits_per_byte = 10
        prbfile = "CTM1215.prb"
        ser = serial.Serial(
            port='/dev/ttyUSB1',  # Gerätedatei
            baudrate=baud,  # Baudrate
            parity=serial.PARITY_ODD,  # Odd Parity
            stopbits=serial.STOPBITS_ONE,  # Standard: 1 Stopbit
            bytesize=serial.EIGHTBITS,  # 8 Datenbits
            timeout=1
        )
    if False:
        baud = 614400
        bits_per_byte = 10
        prbfile = "MSS038_optode_mod.prb"
        ser = serial.Serial(
            port='/dev/ttyUSB1',  # Gerätedatei
            baudrate=baud,  # Baudrate MSS
            parity=serial.PARITY_ODD,  # Odd Parity
            stopbits=serial.STOPBITS_ONE,  # Standard: 1 Stopbit
            bytesize=serial.EIGHTBITS,  # 8 Datenbits
            timeout=0.1
        )

    dt_per_byte = bits_per_byte / baud

    if not ser.is_open:
        ser.open()

    nread = 512
    while True:
        current_time = time.time()
        data = ser.read(nread)
        # Relative Zeiten mit NumPy berechnen (rückwärts vom letzten Byte)
        relative_times = np.arange(len(data) - 1, -1,
                                   -1) * dt_per_byte  # [47*dt, 46*dt, ..., 0*dt]

        # Absolute Zeitstempel (als Liste)
        data_time = (current_time - relative_times).tolist()
        #data_time = [time.time()] * len(data)
        data_queue.put([data,data_time])
        try:
            data_queue_in.get_nowait()
            return
        except:
            pass



def start(device_info, config=None, dataqueue=None, datainqueue=None, statusqueue=None):
    """

    """
    funcname = __name__ + '.start()'
    logger.debug(funcname + ':Starting Sea Sun Tech device')
    print('Starting',config)

    # Setup serial connection
    if True:
        prbfile = config["prbfile"]
        if "mss" in config["probe_type"].lower():
            print("Configuring a MSS probe")
            shear_sensitivities = {'SHE1': 3.90e-4, 'SHE2': 4.05e-4}
            ctd_cfg = SstDeviceConfig.from_prb(prbfile,
                                               shear_sensitivities=shear_sensitivities)

            n_buf_process = 1000
            flag_concatenate_data = True
        else:
            print("Configuring a CTD probe")
            ctd_cfg = SstDeviceConfig.from_prb(prbfile)
            n_buf_process = 8
            flag_concatenate_data = False

        sensors_by_channel = {}
        for k, s in ctd_cfg.sensors.items():
            sensors_by_channel[s.channel] = s
        print("Probe cfg", ctd_cfg)
        device_offset = config["raw_data_device_offset"]
        packetid = f"sst_{ctd_cfg.name}"
        print(f"Device offset:{device_offset}")

    # Setup serial connection
    if False:
        prbfile = "CTM1215.prb"
        ctd_cfg = SstDeviceConfig.from_prb(prbfile)
        sensors_by_channel = {}
        for k, s in ctd_cfg.sensors.items():
            sensors_by_channel[s.channel] = s
        print("CTD cfg", ctd_cfg)
        device_offset = 0
    if False:
        prbfile = "MSS038_optode.prb"
        shear_sensitivities = {'SHE1': 3.90e-4, 'SHE2': 4.05e-4}
        ctd_cfg = SstDeviceConfig.from_prb(prbfile, shear_sensitivities=shear_sensitivities)
        sensors_by_channel = {}
        for k, s in ctd_cfg.sensors.items():
            sensors_by_channel[s.channel] = s
        print("CTD cfg", ctd_cfg)
        device_offset = -32768

    # Create the serial reader thread
    if True:
        data_queue = queue.Queue()
        data_read_serial_in = queue.Queue()
        read_process = threading.Thread(target=read_serial, args=(config, data_queue, data_read_serial_in))
        read_process.start()
    else:
        data_queue = multiprocessing.Queue()
        data_read_serial_in = multiprocessing.Queue()
        read_process = multiprocessing.Process(target=read_serial, args=(config, data_queue, data_read_serial_in))
        read_process.start()


    print("Creating hhl object")
    channel_sequence = None
    data_test_sequence = b''
    hhl = HHL()
    print("Starting loop")
    data_send_cat = None
    while True:
        try:
            data = datainqueue.get_nowait()
        except:
            data = None
            pass
        if (data is not None):
            command = check_for_command(data, thread_uuid=device_info['thread_uuid'])
            if (command is not None):
                logger.debug('Got a command: {:s}'.format(str(data)))
                #print('Command', command)
                if command == 'stop':
                    sstr = funcname + ': Command is for me: {:s}'.format(str(command))
                    logger.debug(sstr)
                    data_read_serial_in.put("Stop")
                    try:
                        statusqueue.put_nowait(sstr)
                    except:
                        pass
                    return



        decoded_data_all = []
        channels_all = []
        if True:
            if not data_queue.empty():
                data_buf = data_queue.get()
                hhl.add_to_buffer(data_buf[0], data_time=data_buf[1])

                if channel_sequence is None:
                    data_test_sequence += data_buf[0]
                    print("Testing for HHL device")
                    if len(data_test_sequence) > 500:
                        channel_sequence = hhl.inspect_rawdata(data_test_sequence)
                        if channel_sequence:
                            data_decoded = hhl.decode_rawdata(data_test_sequence)
                            print("Decoded data", data_decoded)

            if channel_sequence:
                if len(hhl.buffer) > n_buf_process:
                    decoded_data = hhl.process_buffer()
                    decoded_data_all.extend(decoded_data)
                    itest = 0
                    print("Processing", len(hhl.buffer),len(decoded_data_all),len(channel_sequence))
                    while len(decoded_data_all) > len(channel_sequence):
                        data_send = create_datadict(packetid=packetid)
                        itest += 1
                        if itest > 1000:
                            print("Problem, stopping")
                            break

                        channel_sequence_data = pop_channel_sequence(decoded_data_all,
                                                                     channel_sequence)
                        print("Got sequence", channel_sequence_data)
                        if channel_sequence_data is None:
                            break
                        else:
                            for i_ch, ch_data in enumerate(channel_sequence_data):
                                print("ch_data",ch_data)
                                chnum = ch_data[0]
                                chdata = ch_data[1]
                                chtime = ch_data[2]
                                if chnum == 0:
                                    data_send['t'] = chtime
                                if chnum in sensors_by_channel:
                                    chname = sensors_by_channel[chnum].name
                                    #print(f"Processing channel {chnum} ({chname})")
                                    try:
                                        data = sensors_by_channel[chnum].raw_to_units(chdata,offset=device_offset)
                                        #print(f"Data:{data}")
                                        data_send[chname] = data
                                    except:
                                        pass

                            # Concatenate data
                            if flag_concatenate_data:
                                if data_send_cat is None:
                                    data_send_cat = create_datadict(
                                        packetid=packetid)
                                    for k in data_send.keys():
                                        data_send_cat[k] = [data_send[k]]
                                else:
                                    for k in data_send.keys():
                                        data_send_cat[k].append(data_send[k])

                                    #print(data_send_cat)
                                    #print(len(data_send_cat["t"]))
                                    if len(data_send_cat['t']) > 250:
                                        print("Sending cat data")
                                        dataqueue.put(data_send_cat)
                                        #dataqueue.put(data_send)
                                        data_send_cat = None
                                #print(f"Publishing sequence:{data_send}")
                            else:
                                dataqueue.put(data_send)

                #print("Done processing")

        #time.sleep(config["dt_poll_serial"])
        time.sleep(0.001)


import typing
from pathlib import Path
from PyQt6 import QtWidgets, QtCore, QtGui


class RedvyprDeviceWidget(RedvyprdevicewidgetSimple):
    """
    Main widget for Redvypr device configuration.

    Features:
    - Dynamic Input Type switching (Serial, Datastream, File).
    - Conditional visibility for Serial Poll settings.
    - Dynamic ComboBox for 'probe_type' using Pydantic Literal metadata.
    - Persistent bottom alignment for Offset and Probe tools.
    - Global 'config_changed' signal for configuration updates.
    """

    def __init__(self, config: "DeviceCustomConfig" = None, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.config = config or DeviceCustomConfig()

        # Ensure layout exists
        if not self.layout:
            self.setLayout(QtWidgets.QVBoxLayout())

        self._setup_custom_ui()
        self._sync_config_to_ui()

        self.device.new_data.connect(self._new_data)

    def _setup_custom_ui(self):
        """Creates the UI elements and handles the layout structure."""
        self.group_custom = QtWidgets.QGroupBox("Device Configuration")
        self.custom_layout = QtWidgets.QVBoxLayout(self.group_custom)
        self.custom_layout.setSpacing(10)

        # --- TOP SECTION: Input Type & Serial Poll ---
        top_row = QtWidgets.QHBoxLayout()
        top_row.addWidget(QtWidgets.QLabel("Input Type:"))
        self.combo_input_type = QtWidgets.QComboBox()
        self.combo_input_type.addItems(["serial", "datastream", "file"])
        top_row.addWidget(self.combo_input_type)

        top_row.addSpacing(20)

        self.lbl_poll = QtWidgets.QLabel("Serial Poll (s):")
        self.spin_poll = QtWidgets.QDoubleSpinBox()
        self.spin_poll.setRange(0.001, 10.0)
        self.spin_poll.setSingleStep(0.01)
        self.spin_poll.setDecimals(3)
        top_row.addWidget(self.lbl_poll)
        top_row.addWidget(self.spin_poll)
        top_row.addStretch()

        self.custom_layout.addLayout(top_row)

        # --- MIDDLE SECTION: Serial Configuration Widget ---
        self.serial_widget = SerialDeviceWidget(config=self.config.input_serial)
        self.custom_layout.addWidget(self.serial_widget)

        # --- THE STRETCH (Pushes everything below to the bottom) ---
        self.custom_layout.addStretch(1)

        # --- BOTTOM SECTION: Probe Type, Offset & PRB Selection ---
        line = QtWidgets.QFrame()
        line.setFrameShape(QtWidgets.QFrame.Shape.HLine)
        line.setFrameShadow(QtWidgets.QFrame.Shadow.Sunken)
        self.custom_layout.addWidget(line)

        bottom_row = QtWidgets.QHBoxLayout()

        # Dynamic Probe Type from Pydantic Literal
        bottom_row.addWidget(QtWidgets.QLabel("Probe Type:"))
        self.combo_probe_type = QtWidgets.QComboBox()

        # Extract Literal values from DeviceCustomConfig (Pydantic v2)
        try:
            probe_field = DeviceCustomConfig.model_fields["probe_type"]
            allowed_probes = typing.get_args(probe_field.annotation)
            self.combo_probe_type.addItems(allowed_probes)
        except Exception:
            # Fallback if Pydantic access fails
            self.combo_probe_type.addItems(["ctm2", "mss"])

        self.combo_probe_type.setFixedWidth(80)
        bottom_row.addWidget(self.combo_probe_type)

        bottom_row.addSpacing(15)

        # Device Offset
        bottom_row.addWidget(QtWidgets.QLabel("Device Offset:"))
        self.combo_offset = QtWidgets.QComboBox()
        self.combo_offset.setEditable(True)
        self.combo_offset.addItems(["0", "-32768"])
        self.combo_offset.setValidator(QtGui.QIntValidator())
        self.combo_offset.setFixedWidth(100)
        bottom_row.addWidget(self.combo_offset)

        bottom_row.addSpacing(20)

        # Probe File Selection & Scan
        self.btn_prb = QtWidgets.QPushButton("Select .prb File")
        self.btn_scan_prb = QtWidgets.QPushButton("Scan prb file")
        self.lbl_prb_path = QtWidgets.QLabel("None")
        self.lbl_prb_path.setStyleSheet("color: gray; font-style: italic;")

        bottom_row.addWidget(self.btn_prb)
        bottom_row.addWidget(self.btn_scan_prb)
        bottom_row.addWidget(self.lbl_prb_path)

        bottom_row.addStretch()
        self.custom_layout.addLayout(bottom_row)

        # Add the entire group to the main layout
        self.layout.addWidget(self.group_custom)

        # --- SIGNAL CONNECTIONS ---

        # Specific logic handlers
        self.combo_input_type.currentTextChanged.connect(self._on_input_type_changed)
        self.combo_probe_type.currentTextChanged.connect(self._on_probe_type_changed)
        self.combo_offset.currentTextChanged.connect(self._on_offset_changed)
        self.spin_poll.valueChanged.connect(self._on_poll_changed)
        self.btn_prb.clicked.connect(self._on_select_prb)
        self.btn_scan_prb.clicked.connect(self._on_scan_prb)

        # Global config changed printer
        self.combo_input_type.currentTextChanged.connect(self.config_changed)
        self.combo_probe_type.currentTextChanged.connect(self.config_changed)
        self.combo_offset.currentTextChanged.connect(self.config_changed)
        self.spin_poll.valueChanged.connect(lambda: self.config_changed())
        self.serial_widget.config_changed.connect(lambda: self.config_changed())

    def config_changed(self, *args):
        """Triggered on any configuration change."""
        print("config changed")
        # Update the device object with the latest state
        if hasattr(self, 'device'):
            self.device.custom_config = self.config
            print(f"Current Config: {self.device.custom_config}")

    def _sync_config_to_ui(self):
        """Loads data from the config object into the UI widgets."""
        self.blockSignals(True)
        self.serial_widget.blockSignals(True)

        c = self.config
        self.combo_input_type.setCurrentText(c.input_type)
        self.combo_probe_type.setCurrentText(c.probe_type)
        self.combo_offset.setCurrentText(str(c.raw_data_device_offset))
        self.spin_poll.setValue(c.dt_poll_serial)

        if c.prbfile:
            path_obj = Path(c.prbfile)
            self.lbl_prb_path.setText(path_obj.name)
            self.lbl_prb_path.setToolTip(str(c.prbfile))
        else:
            self.lbl_prb_path.setText("Not set")

        self._update_visibility(c.input_type)

        self.serial_widget.blockSignals(False)
        self.blockSignals(False)

    def _update_visibility(self, input_type: str):
        """Toggles serial-specific fields."""
        is_serial = (input_type == "serial")
        self.lbl_poll.setVisible(is_serial)
        self.spin_poll.setVisible(is_serial)
        self.serial_widget.setVisible(is_serial)

    # --- EVENT HANDLERS ---

    def _on_input_type_changed(self, text: str):
        self.config.input_type = text
        self._update_visibility(text)

    def _on_probe_type_changed(self, text: str):
        self.config.probe_type = text

    def _on_offset_changed(self, text: str):
        try:
            self.config.raw_data_device_offset = int(text)
        except ValueError:
            pass

    def _on_poll_changed(self, value: float):
        self.config.dt_poll_serial = value

    def _on_select_prb(self):
        file_path, _ = QtWidgets.QFileDialog.getOpenFileName(
            self, "Select PRB File", "", "Probe Files (*.prb);;All Files (*)"
        )
        if file_path:
            self.config.prbfile = Path(file_path)
            self.lbl_prb_path.setText(self.config.prbfile.name)
            self.lbl_prb_path.setToolTip(file_path)
            self.config_changed()

    def _on_scan_prb(self):
        """Dummy handler for scanning logic."""
        if not self.config.prbfile:
            return
        print(f"DEBUG: Scanning PRB file at {self.config.prbfile}...")

    def _new_data(self, new_data_list):
        print("Got new data",len(new_data_list))

