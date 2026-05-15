import logging
from luma.core.interface.serial import spi
from luma.oled.device import sh1106

logger = logging.getLogger(__name__)

_device = None

def get_device():
    global _device
    if _device is None:
        serial = spi(device=0, port=0)
        _device = sh1106(serial, rotate=0)
        logger.info("OLED initialized — SH1106 SPI rotate=0")
    return _device

def clear():
    from luma.core.render import canvas
    device = get_device()
    with canvas(device) as draw:
        draw.rectangle(device.bounding_box, fill="black")