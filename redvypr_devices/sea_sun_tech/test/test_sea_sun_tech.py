from redvypr_devices import sea_sun_tech
from redvypr_devices.sea_sun_tech.sea_sun_tech_config import SstDeviceConfig

prbfile = "CTM1215.prb"

ctd_cfg = SstDeviceConfig.from_prb(prbfile)
print("CTD cfg",ctd_cfg)