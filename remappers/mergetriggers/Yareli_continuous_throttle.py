#!/usr/bin/env python3

# Yareli_continuous_throttle.py
# Forwards ABS_Z from T-Rudder as left stick up/down (ABS_Y) on a virtual XInput-compatible gamepad

from evdev import InputDevice, UInput, ecodes as e
import sys

# Change this to your T-Rudder device event path
TRUDDER_PATH = "/dev/input/event7"

# Virtual gamepad capabilities (minimal XInput-like)
capabilities = {
    e.EV_KEY: [
        e.BTN_A, e.BTN_B, e.BTN_X, e.BTN_Y,
        e.BTN_TL, e.BTN_TR,
        e.BTN_SELECT, e.BTN_START,
        e.BTN_THUMBL, e.BTN_THUMBR,
        e.BTN_MODE,
        e.BTN_DPAD_UP, e.BTN_DPAD_DOWN, e.BTN_DPAD_LEFT, e.BTN_DPAD_RIGHT
    ],
    e.EV_ABS: [
        (e.ABS_X,   (0, -32768, 32767, 16, 128, 0)),
        (e.ABS_Y,   (0, -32768, 32767, 16, 128, 0)),  # Left stick Y (output)
        (e.ABS_RX,  (0, -32768, 32767, 16, 128, 0)),
        (e.ABS_RY,  (0, -32768, 32767, 16, 128, 0)),
        (e.ABS_Z,   (0, 0, 255, 0, 0, 0)),
        (e.ABS_RZ,  (0, 0, 255, 0, 0, 0)),
        (e.ABS_HAT0X, (0, -1, 1, 0, 0, 0)),
        (e.ABS_HAT0Y, (0, -1, 1, 0, 0, 0)),
    ]
}

def scale_trudder_z(value, in_min=0, in_max=1023, out_min=-32768, out_max=32767):
    # Scale T-Rudder ABS_Z (0-1023) to gamepad ABS_Y (-32768 to 32767)
    return int((value - in_min) * (out_max - out_min) / (in_max - in_min) + out_min)

def main():
    dev = None
    ui = None
    try:
        dev = InputDevice(TRUDDER_PATH)
        ui = UInput(capabilities, name="Yareli_continuous_throttle", bustype=e.BUS_USB)
        print("Virtual device created: Yareli_continuous_throttle")

        for event in dev.read_loop():
            if event.type == e.EV_ABS and event.code == e.ABS_Z:
                scaled = scale_trudder_z(event.value)
                ui.write(e.EV_ABS, e.ABS_Y, -scaled)
                ui.syn()
    except Exception as ex:
        print(f"Error: {ex}")
    except KeyboardInterrupt:
        print("\nInterrupted, closing devices...")
    finally:
        if ui:
            ui.close()
        if dev:
            dev.close()

if __name__ == "__main__":
    main()
