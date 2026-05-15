import logging
import smbus
import time

logger = logging.getLogger(__name__)

# ── Config ────────────────────────────────────────────────────────────────────

I2C_BUS  = 2
I2C_ADDR = 0x3a

# ── Voltage to capacity map ───────────────────────────────────────────────────

def voltage_to_percent(v: float) -> int:
    table = [
        (4.20, 100), (4.15, 95), (4.11, 90), (4.08, 85),
        (4.02, 80),  (3.98, 75), (3.95, 70), (3.91, 65),
        (3.87, 60),  (3.83, 55), (3.79, 50), (3.75, 45),
        (3.71, 40),  (3.67, 35), (3.63, 30), (3.59, 25),
        (3.55, 20),  (3.51, 15), (3.45, 10), (3.40, 5),
        (3.30, 3),   (3.20, 2),  (3.10, 1),
    ]
    for threshold, pct in table:
        if v >= threshold:
            return pct
    return 0

# ── Reader ────────────────────────────────────────────────────────────────────

def read_voltage() -> float | None:
    try:
        bus = smbus.SMBus(I2C_BUS)
        vcell_high = bus.read_byte_data(I2C_ADDR, 0x02)
        vcell_low  = bus.read_byte_data(I2C_ADDR, 0x03)
        vcell = ((vcell_high << 8) | vcell_low) >> 4
        return round(vcell * 1.25 / 1000, 3)
    except Exception as e:
        logger.warning(f"Battery voltage read failed: {e}")
        return None

# ── Charging detection ────────────────────────────────────────────────────────

_last_voltage  = None
_last_reading  = 0.0
_is_charging   = False

def is_charging() -> bool:
    global _last_voltage, _last_reading, _is_charging
    now = time.time()

    # Only re-check every 30 seconds
    if now - _last_reading < 30:
        return _is_charging

    v = read_voltage()
    if v is None:
        return _is_charging

    if _last_voltage is not None:
        _is_charging = v > _last_voltage + 0.01

    _last_voltage = v
    _last_reading = now
    return _is_charging

# ── Full status ───────────────────────────────────────────────────────────────

def get_battery_status() -> dict:
    v = read_voltage()
    if v is None:
        return {
            "voltage":   None,
            "percent":   None,
            "charging":  False,
            "available": False,
        }
    return {
        "voltage":   v,
        "percent":   voltage_to_percent(v),
        "charging":  is_charging(),
        "available": True,
    }

if __name__ == "__main__":
    status = get_battery_status()
    print(f"🔋 Battery: {status['voltage']}V  {status['percent']}%  "
          f"{'⚡ Charging' if status['charging'] else '🔋 On battery'}")