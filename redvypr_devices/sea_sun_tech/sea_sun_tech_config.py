from typing import Literal, Union, Optional, Annotated
import logging
import sys
from typing import cast
from pathlib import Path
import configparser
import numpy as np
from pydantic import BaseModel, Field

# Setup logging module
# TODO should handle this more gracefully, having debug level logging everywhere is annoying
# logging.basicConfig(stream=sys.stderr, level=logging.DEBUG)
logger = logging.getLogger("redvypr_devices.sea_sun_tech_definitions")
logger.setLevel(logging.DEBUG)


# Define standard names for sensors
mss_standard_ctd_sensornames = {}
mss_standard_ctd_sensornames["press"] = ["PRESS", "P250", "P1000"]
mss_standard_ctd_sensornames["temp"] = ["TEMP", "NTC"]
mss_standard_ctd_sensornames["cond"] = ["COND"]



def read_prb_file(filename):
    encodings = ['utf-8', 'Windows-1252', 'ISO-8859-1']  # Häufige Kodierungen
    content = None

    for encoding in encodings:
        try:
            with open(filename, 'r', encoding=encoding) as f:
                content = f.read().lstrip()  # Leerzeilen/Leerzeichen entfernen
            break  # Erfolg: Schleife verlassen
        except UnicodeDecodeError:
            continue  # Nächste Kodierung probieren

    if content is None:
        raise ValueError(
            f"Konnte die Datei {filename} mit keiner der Kodierungen lesen: {encodings}")

    # ConfigParser-Objekt erstellen
    config = configparser.ConfigParser(
        interpolation=None,
        delimiters=('='),
        strict=False)

    config.optionxform = str
    config.read_string(content)


    # Abschnitte und Schlüssel ausgeben
    config_dict = {}
    for section in config.sections():
        print(f"[{section}]")
        config_dict[section] = {}
        for key, value in config[section].items():
            print(f"{key} = {value}")
            config_dict[section][key] = value
        print()

    print("Processing sensors")
    config_sensors = {}

    print(config.sections())
    for key, value in config["Sensors"].items():
        print(f"{key} = {value}")
        print("vtmp",value.split())
        parts = value.split()
        if len(parts) < 7:  # Mindestens 7 Teile erwartet
            continue

        # Extrahiere die Felder
        channel = int(parts[0])
        caltype = parts[1]          # z. B. "N"
        property = parts[2]        # z. B. "COUNT"
        unit = parts[3]             # z. B. "_"
        poly = list(map(float, parts[4:]))  # Rest als Floats (Polynomkoeffizienten)

        # Speichere im Dictionary
        config_sensors[channel] = {
            'sst_channel_map': key,
            'caltype': caltype,
            'name': property,
            'unit': unit,
            'coeff': poly
        }

    print("sensors keys",config_sensors.keys())
    config_dict["Sensors"] = config_sensors
    return config_dict





class SstSensor(BaseModel):
    name: str
    coefficients: list[float]
    channel: int
    unit: str = Field(default="")
    calibration_type: Literal[None]  # ["N", "SHE", "P", "SHH", "NFC", "V04", "N24"]


class SstSensorNotImplemented(SstSensor):
    """
    Fallback class for unsupported calibration types in SST sensors.
    Raises NotImplementedError when raw_to_units is called.
    """

    calibration_type: str = Field(..., description="Unsupported calibration type")

    def raw_to_units(self, rawdata, offset=0):
        raise NotImplementedError(
            f"Calibration type '{self.calibration_type}' is not implemented for this sensor."
        )


class SstSensorPoly(SstSensor):
    calibration_type: Literal["N"] = Field(default="N")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._p = np.polynomial.Polynomial(self.coefficients)

    def raw_to_units(self, rawdata, offset=0):
        data = self._p(rawdata + offset)
        return data


class SstShearSensor(SstSensor):
    sensitivity: float
    serial_number: str = Field(default="")
    reference_temperature: float = Field(default=-9999)
    calibration_date: str = Field(default="")
    calibration_type: Literal["SHE"] = Field(default="SHE")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.coefficients = [None, None]
        self.coefficients[0] = 1.47133e-6 / self.sensitivity
        self.coefficients[1] = 2.94266e-6 / self.sensitivity
        self._p = np.polynomial.Polynomial(self.coefficients)

    def raw_to_units(self, rawdata, offset=0):
        data = self._p(rawdata - offset)  # The shear sensors have the negative offset
        return data


class SstSensorPressure(SstSensor):
    calibration_type: Literal["P"] = Field(default="P")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._p = np.polynomial.Polynomial(self.coefficients[:-1])

    def raw_to_units(self, rawdata, offset=0):
        #print("Processing pressure sensor")
        data = self._p(rawdata + offset) - self.coefficients[-1]
        #print(f"{min(data)},{max(data)},{self._p},{self.coefficients[-1]}")
        return data


class SstSensorNTC(SstSensor):
    """
    Steinhart/Hart NTC Polynomial
    """

    calibration_type: Literal["SHH"] = Field(default="SHH")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._p = np.polynomial.Polynomial(self.coefficients[:-1])

    def raw_to_units(self, rawdata, offset):
        data = self._p(np.log(rawdata + offset))
        data = 1 / data - 273.15  # Kelvin to degC
        return data


class SstSensorTurb(SstSensor):
    """
    Convert rawdata turbidity to NFC
    """

    calibration_type: Literal["NFC"] = Field(default="NFC")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._p = np.polynomial.Polynomial(self.coefficients[:-1])

    def raw_to_units(self, rawdata, offset):
        p = np.polynomial.Polynomial(self.coefficients[:-2])
        data = p(rawdata + offset) * self.coefficients[-1] + self.coefficients[-2]
        return data


class SstSensorOptode(SstSensor):
    """
    Convert oxygen optode rawdata to physical units
    """

    calibration_type: Literal["V04"] = Field(default="V04")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._p1 = np.polynomial.Polynomial(
            self.coefficients[0:2]
        )  # Convert data to mV
        self._p2 = np.polynomial.Polynomial(
            self.coefficients[-2:]
        )  # 0 Point correction with B0 and B1

    def raw_to_units(self, rawdata, offset):
        data_mV = self._p1(rawdata + offset)
        data = self._p2(data_mV)
        return data


class SstSensorOptodeInternalTemp(SstSensor):
    calibration_type: Literal["N24"] = Field(default="N24")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._p = np.polynomial.Polynomial(self.coefficients)

    def raw_to_units(self, rawdata, offset=0):
        data = self._p(rawdata + offset)
        return data



class SstDeviceConfig(BaseModel):
    sn: str = Field(
        default='', description="The serialnumber of the device"
    )
    model_type: str = Field(
        default='', description="The device model"
    )
    name: str = Field(
        default='', description="The device name"
    )
    dataformat: str = Field(
        default='', description="The raw dataformat"
    )

    baudstr: str = Field(
        default='', description="The baudstr as in the prb file"
    )

    offset: int = Field(
        default=0, description="16bit offset, typically 0, older devices have -32768"
    )
    sampling_freq: float = Field(
        default=-999.0,
        description="The sampling frequency [Hz] of the device",
    )
    sensors: dict[
        str,
        Annotated[
            Union[
                SstSensor,
                SstSensorPoly,
                SstShearSensor,
                SstSensorPressure,
                SstSensorNTC,
                SstSensorTurb,
                SstSensorOptode,
                SstSensorOptodeInternalTemp,
            ],
            Field(discriminator="calibration_type"),
        ],
    ] = Field(
        default={}, description="A dictionary of the sensors mounted to the probe"
    )
    sensornames_ctd: dict[
        Union[Literal["cond"], Literal["temp"], Literal["press"]],
        str,
    ] = Field(
        default={"cond": "", "temp": "", "press": ""},
        description="A dictionary to link standard ctd names to the names of the config",
    )
    pressure_sensorname: Optional[str] = Field(
        default=None,
        description="The sensorname of the pressure sensor, if None a best guess will be made",
    )

    def init_sensors_from_dict(
            self,
            sensors,
            shear_sensitivities=None,
    ):
        # Fill in sensors from header
        for ch,sensor_dict in sensors.items():
            #print("ch",ch,sensor_dict,type(sensor_dict))
            sensorname = sensor_dict["name"]
            unit = sensor_dict["unit"]
            caltype = sensor_dict["caltype"].upper()
            logger.debug(
                "Checking Channel:{}, sensorname:{}, caltype:{}".format(
                    ch, sensorname, caltype
                )
            )
            if caltype == "N":  # Polynom
                if sensorname.upper().startswith("SHE"):
                    logger.debug("\tAdding shear sensor {}".format(sensorname))
                    if shear_sensitivities is None:
                        sensitivity = np.nan
                    else:
                        sensitivity = shear_sensitivities[sensorname]
                    self.sensors[sensorname] = SstShearSensor(
                        channel=ch,
                        name=sensorname,
                        coefficients=sensor_dict["coeff"],
                        unit=unit,
                        sensitivity=sensitivity,
                    )
                else:
                    logger.debug(
                        "\tAdding standard polynomial sensor {}".format(sensorname)
                    )
                    self.sensors[sensorname] = SstSensorPoly(
                        channel=ch,
                        name=sensorname,
                        coefficients=sensor_dict["coeff"],
                        unit=unit,
                    )
            elif caltype == "SHH":
                logger.debug("\tAdding NTC sensor {}".format(sensorname))
                self.sensors[sensorname] = SstSensorNTC(
                    channel=ch,
                    name=sensorname,
                    coefficients=sensor_dict["coeff"],
                    unit=unit,
                )
            elif caltype == "P":  # Pressure
                logger.debug("\tAdding pressure sensor {}".format(sensorname))
                self.sensors[sensorname] = SstSensorPressure(
                    channel=ch,
                    name=sensorname,
                    coefficients=sensor_dict["coeff"],
                    unit=unit,
                )
            elif caltype == "V04":  # Oxygen
                logger.debug("\tAdding oxygen optode sensor {}".format(sensorname))
                self.sensors[sensorname] = SstSensorOptode(
                    channel=ch,
                    name=sensorname,
                    coefficients=sensor_dict["coeff"],
                    unit=unit,
                )
            elif caltype == "N24":  # Internal temperature of oxygensensor
                logger.debug(
                    "\tAdding oxygen optode temperature sensor {}".format(sensorname)
                )
                self.sensors[sensorname] = SstSensorOptodeInternalTemp(
                    channel=ch,
                    name=sensorname,
                    coefficients=sensor_dict["coeff"],
                    unit=unit,
                )
            elif caltype == "NFC":  # Turbidity etc.
                logger.debug("\tAdding NFC sensor {}".format(sensorname))
                self.sensors[sensorname] = SstSensorTurb(
                    channel=ch,
                    name=sensorname,
                    coefficients=sensor_dict["coeff"],
                    unit=unit,
                )

            else:
                logger.debug(f"\tsensor {sensorname} not implemented")
                self.sensors[sensorname] = SstSensorNotImplemented(
                    calibration_type=sensorname,
                    channel=ch,
                    name=sensorname,
                    coefficients=sensor_dict["coeff"],
                    unit=unit,
                )

    @classmethod
    def from_srd_mrd(
        cls,
        filename: str | Path,
        shear_sensitivities: dict[str, float],
        offset: int = 0,
    ):
        """
        Creating a MssDeviceConfig from a mrd file
        """
        raise NotImplementedError

    @classmethod
    def from_prb(cls, filename, offset=0, shear_sensitivities = None):
        """
        Creating a SstDeviceConfig from a prb file
        """
        config = read_prb_file(filename=filename)
        self = cls()
        self.init_sensors_from_dict(config["Sensors"], shear_sensitivities = shear_sensitivities)
        self.model_type = config["Probe"]["Typ"]
        self.sn = config["Probe"]["SerialNumber"]
        self.name = config["Probe"]["Name"]
        self.dataformat = config["Baud"]["DataFormat"]
        self.baudstr = config["Baud"]["COM"]



        return self




class MssDeviceConfig(SstDeviceConfig):
    sampling_freq: float = Field(
        default=1024.0,
        description="The sampling frequency [Hz] of the microstructure probe",
    )
    gain_utemp: float = Field(
        default=1.5,
        description="Gain of the NTC highpass pre-emphasis differentiator",
    )
    pspd_rel_method: Literal["pressure", "constant", "external"] = Field(
        default="pressure",
        description="Method for the platform speed relative to the seawater, this is needed to calculate wavenumbers from the sampled data",
    )
    pspd_rel_constant_vel: Optional[float] = Field(
        default=None,
        description='Constant velocity [m/s] used as pspd_rel, if defined by "pspd_rel_method"',
    )

    @classmethod
    def from_mrd(
        cls,
        filename: str | Path,
        shear_sensitivities: dict[str, float],
        offset: int = 0,
    ):
        """
        Creating a MssDeviceConfig from a mrd file
        """
        self = cls()
        self.offset = offset
        logger.debug("Opening file:{}".format(filename))
        mrd_file = open(filename, "rb")
        data = mss_mrd.read_mrd(filestream=mrd_file, header_only=True)
        logger.debug("Closing file:{}".format(filename))
        mrd_file.close()
        header_raw = data["header"]
        header = mss_mrd.parse_header(header_raw)
        # Check for CTD sensors and link names
        for ctd_sensor in self.sensornames_ctd.keys():
            sensorname_mss = self.sensornames_ctd[ctd_sensor]
            if len(sensorname_mss) == 0:
                logger.debug("Searching for sensor of {}".format(ctd_sensor))
                sensornames = [
                    header["mss"]["channels"][ch]["name"]
                    for ch in header["mss"]["channels"]
                ]
                sensornames_casefold = [
                    header["mss"]["channels"][ch]["name"].casefold()
                    for ch in header["mss"]["channels"]
                ]
                for k in mss_standard_ctd_sensornames[
                    ctd_sensor
                ]:  # Loop over the standard names
                    if k.casefold() in sensornames_casefold:
                        index_sensor = sensornames_casefold.index(k.casefold())
                        sensorname_mss = sensornames[index_sensor]
                        logger.debug(
                            "\tFound MSS sensor {} for {}".format(
                                sensorname_mss, ctd_sensor
                            )
                        )
                        self.sensornames_ctd[ctd_sensor] = sensorname_mss
                        break

        # Fill in sensors from header
        for ch in header["mss"]["channels"]:
            sensor_dict = header["mss"]["channels"][ch]
            sensorname = sensor_dict["name"]
            unit = sensor_dict["unit"]
            caltype = sensor_dict["caltype"].upper()
            logger.debug(
                "Checking Channel:{}, sensorname:{}, caltype:{}".format(
                    ch, sensorname, caltype
                )
            )
            if caltype == "N":  # Polynom
                if sensorname.upper().startswith("SHE"):
                    logger.debug("\tAdding shear sensor {}".format(sensorname))
                    sensitivity = shear_sensitivities[sensorname]
                    self.sensors[sensorname] = SstShearSensor(
                        channel=ch,
                        name=sensorname,
                        coefficients=sensor_dict["coeff"],
                        unit=unit,
                        sensitivity=sensitivity,
                    )
                else:
                    logger.debug(
                        "\tAdding standard polynomial sensor {}".format(sensorname)
                    )
                    self.sensors[sensorname] = SstSensorPoly(
                        channel=ch,
                        name=sensorname,
                        coefficients=sensor_dict["coeff"],
                        unit=unit,
                    )
            elif caltype == "SHH":
                logger.debug("\tAdding NTC sensor {}".format(sensorname))
                self.sensors[sensorname] = SstSensorNTC(
                    channel=ch,
                    name=sensorname,
                    coefficients=sensor_dict["coeff"],
                    unit=unit,
                )
            elif caltype == "P":  # Pressure
                logger.debug("\tAdding pressure sensor {}".format(sensorname))
                self.sensors[sensorname] = SstSensorPressure(
                    channel=ch,
                    name=sensorname,
                    coefficients=sensor_dict["coeff"],
                    unit=unit,
                )
            elif caltype == "V04":  # Oxygen
                logger.debug("\tAdding oxygen optode sensor {}".format(sensorname))
                self.sensors[sensorname] = SstSensorOptode(
                    channel=ch,
                    name=sensorname,
                    coefficients=sensor_dict["coeff"],
                    unit=unit,
                )
            elif caltype == "N24":  # Internal temperature of oxygensensor
                logger.debug(
                    "\tAdding oxygen optode temperature sensor {}".format(sensorname)
                )
                self.sensors[sensorname] = SstSensorOptodeInternalTemp(
                    channel=ch,
                    name=sensorname,
                    coefficients=sensor_dict["coeff"],
                    unit=unit,
                )
            elif caltype == "NFC":  # Turbidity etc.
                logger.debug("\tAdding NFC sensor {}".format(sensorname))
                self.sensors[sensorname] = SstSensorTurb(
                    channel=ch,
                    name=sensorname,
                    coefficients=sensor_dict["coeff"],
                    unit=unit,
                )
        # print('Header', header['channels'])

        return self


