#!/usr/bin/env python3


from evdev import InputDevice, UInput, ecodes as e
from dpad_util import emit_dpad_buttons
from trigger_util import merged_triggers


DEVICE_PATH = "/dev/input/event11"  # Change this to your F710 device

capabilities = {
    e.EV_KEY: [
        e.BTN_A, e.BTN_B, e.BTN_X, e.BTN_Y,
        e.BTN_TL, e.BTN_TR,           # LB, RB
        e.BTN_SELECT, e.BTN_START,    # Back, Start
        e.BTN_THUMBL, e.BTN_THUMBR,   # L-stick, R-stick press
        e.BTN_MODE,                   # Guide button
        e.BTN_DPAD_UP, e.BTN_DPAD_DOWN, e.BTN_DPAD_LEFT, e.BTN_DPAD_RIGHT
    ],
    e.EV_ABS: [
        (e.ABS_X,   (0, -32768, 32767, 16, 128, 0)),  # Left stick X (fuzz=16, flat=128)
        (e.ABS_Y,   (0, -32768, 32767, 16, 128, 0)),  # Left stick Y (fuzz=16, flat=128)
        (e.ABS_RX,  (0, -32768, 32767, 16, 128, 0)),  # Right stick X (fuzz=16, flat=128)
        (e.ABS_RY,  (0, -32768, 32767, 16, 128, 0)),  # Right stick Y (fuzz=16, flat=128)
        (e.ABS_MISC, (0, -32767, 32767, 0, 0, 0)), # Merged triggers as "mystery" axis
        (e.ABS_HAT0X, (0, -1, 1, 0, 0, 0)),        # D-pad X
        (e.ABS_HAT0Y, (0, -1, 1, 0, 0, 0)),        # D-pad Y
    ]
}

def main():
    input_dev = InputDevice(DEVICE_PATH)
    print(f"Reading from: {input_dev.name}")
    output_dev = UInput(capabilities, name="F710-SwapSticks+TriggerMystery", bustype=e.BUS_USB)
    print("Created virtual device: F710-SwapSticks+TriggerMystery")

    left_trigger = 0
    right_trigger = 0
    dpad_state = {e.BTN_DPAD_UP: 0, e.BTN_DPAD_DOWN: 0, e.BTN_DPAD_LEFT: 0, e.BTN_DPAD_RIGHT: 0}

    try:
        for event in input_dev.read_loop():
            if event.type == e.EV_ABS:
                # Swap left and right stick axes
                if event.code == e.ABS_X:
                    output_dev.write(e.EV_ABS, e.ABS_RX, event.value)
                elif event.code == e.ABS_Y:
                    output_dev.write(e.EV_ABS, e.ABS_RY, event.value)
                elif event.code == e.ABS_RX:
                    output_dev.write(e.EV_ABS, e.ABS_X, event.value)
                elif event.code == e.ABS_RY:
                    output_dev.write(e.EV_ABS, e.ABS_Y, event.value)
                elif event.code == e.ABS_Z:
                    left_trigger = event.value
                elif event.code == e.ABS_RZ:
                    right_trigger = event.value
                elif event.code in (e.ABS_HAT0X, e.ABS_HAT0Y):
                    output_dev.write(e.EV_ABS, event.code, event.value)
                    emit_dpad_buttons(output_dev, dpad_state, event.code, event.value)
                    output_dev.syn()
                    continue
                else:
                    output_dev.write(event.type, event.code, event.value)
                    output_dev.syn()
                    continue
                # Only emit merged axis if a trigger event
                if event.code in (e.ABS_Z, e.ABS_RZ):
                    merged_value = merged_triggers(left_trigger, right_trigger)
                    output_dev.write(e.EV_ABS, e.ABS_MISC, merged_value)
            elif event.type == e.EV_KEY:
                # Forward all button events
                output_dev.write(event.type, event.code, event.value)
            output_dev.syn()
    except KeyboardInterrupt:
        print("\nStopping...")
    finally:
        output_dev.close()
        input_dev.close()

if __name__ == "__main__":
    main()
