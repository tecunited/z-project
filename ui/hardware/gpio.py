import RPi.GPIO as GPIO
import time
import logging

logger = logging.getLogger(__name__)

BUTTON_MAP = {
    19: "UP",
    6:  "DOWN",
    26: "LEFT",
    5:  "RIGHT",
    13: "PRESS",
    21: "KEY1",
    20: "KEY2",
    16: "KEY3",
}

def setup():
    GPIO.setmode(GPIO.BCM)
    GPIO.setwarnings(False)
    for pin in BUTTON_MAP:
        GPIO.setup(pin, GPIO.IN, pull_up_down=GPIO.PUD_UP)
    logger.info("GPIO initialized")

def cleanup():
    GPIO.cleanup()
    logger.info("GPIO cleaned up")

def get_pressed() -> str | None:
    for pin, name in BUTTON_MAP.items():
        if GPIO.input(pin) == GPIO.LOW:
            return name
    return None

def wait_for_release():
    """Wait until all buttons are released."""
    while get_pressed() is not None:
        time.sleep(0.02)
    time.sleep(0.05)

def wait_for_press(timeout: float = 0.05) -> str | None:
    pressed = get_pressed()
    if pressed:
        time.sleep(0.05)  # debounce
        # Wait for release before returning
        wait_for_release()
        return pressed
    return None