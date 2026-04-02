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
from redvypr.widgets.standard_device_widgets import RedvyprdevicewidgetSimple
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
    sst_device: typing.Optional[SstDeviceConfig] = pydantic.Field(default = None, description='The device config')
    prbfile: typing.Optional[Path] = pydantic.Field(default=None,description="Path to the .prb file")
    dt_poll_serial: float = pydantic.Field(default=0.01,description="Polling interval for the serial port")


redvypr_devicemodule = True



def read_serial(config, data_queue, data_queue_in):
    # Setup serial connection
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
    else:
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
    if False:
        prbfile = "CTM1215.prb"
        ctd_cfg = SstDeviceConfig.from_prb(prbfile)
        sensors_by_channel = {}
        for k, s in ctd_cfg.sensors.items():
            sensors_by_channel[s.channel] = s
        print("CTD cfg", ctd_cfg)
        device_offset = 0
    else:
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


        n_buf_process = 1000
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
                        data_send = {}
                        itest += 1
                        if itest > 1000:
                            print("Problem, stopping")
                            break

                        channel_sequence_data = pop_channel_sequence(decoded_data_all,
                                                                     channel_sequence)
                        #print("Got sequence", channel_sequence_data)
                        if channel_sequence_data is None:
                            break
                        else:
                            for i_ch, ch_data in enumerate(channel_sequence_data):

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
                            if data_send_cat is None:
                                data_send_cat = {}
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
                            #dataqueue.put(data_send)

                #print("Done processing")

        #time.sleep(config["dt_poll_serial"])
        time.sleep(0.001)


class RedvyprDeviceWidget(RedvyprdevicewidgetSimple):
    def __init__(self,*args,**kwargs):
        super().__init__(*args,**kwargs)

