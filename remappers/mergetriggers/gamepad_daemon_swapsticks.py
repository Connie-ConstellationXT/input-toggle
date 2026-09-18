#!/usr/bin/env python3

from evdev import InputDevice, UInput, ecodes as e

DEVICE_PATH = "/dev/input/event3"  # Change this to your F710 device

# Xbox 360 Controller identifiers for proper XInput recognition
XBOX360_VENDOR = 0x045e   # Microsoft
XBOX360_PRODUCT = 0x028e  # Xbox 360 Controller
XBOX360_VERSION = 0x0114  # Standard version

# Capabilities matching real Xbox 360 controller exactly
capabilities = {
    e.EV_KEY: [
        e.BTN_A, e.BTN_B, e.BTN_X, e.BTN_Y,
        e.BTN_TL, e.BTN_TR,           # LB, RB
        e.BTN_SELECT, e.BTN_START,    # Back, Start
        e.BTN_THUMBL, e.BTN_THUMBR,   # L-stick, R-stick press
        e.BTN_MODE,                   # Guide button
    ],
    e.EV_ABS: [
        (e.ABS_X,   (0, -32768, 32767, 16, 128, 0)),  # Left stick X (fuzz=16, flat=128)
        (e.ABS_Y,   (0, -32768, 32767, 16, 128, 0)),  # Left stick Y (fuzz=16, flat=128)
        (e.ABS_RX,  (0, -32768, 32767, 16, 128, 0)),  # Right stick X (fuzz=16, flat=128)
        (e.ABS_RY,  (0, -32768, 32767, 16, 128, 0)),  # Right stick Y (fuzz=16, flat=128)
        (e.ABS_Z,   (0, 0, 255, 0, 0, 0)),           # Left trigger (0-255)
        (e.ABS_RZ,  (0, 0, 255, 0, 0, 0)),           # Right trigger (0-255)
        (e.ABS_HAT0X, (0, -1, 1, 0, 0, 0)),          # D-pad X
        (e.ABS_HAT0Y, (0, -1, 1, 0, 0, 0)),          # D-pad Y
    ],
    # Note: FF (Force Feedback) capabilities removed - declaring them without handling
    # FF_UPLOAD/FF_ERASE events causes blocking when games send rumble commands
}

def main():
    input_dev = InputDevice(DEVICE_PATH)
    print(f"Reading from: {input_dev.name}")
    
    # Create UInput device with Xbox 360 controller identity
    output_dev = UInput(
        capabilities,
        name="Xbox 360 Controller",
        vendor=XBOX360_VENDOR,
        product=XBOX360_PRODUCT,
        version=XBOX360_VERSION,
        bustype=e.BUS_USB,
        phys="usb-virtual-gamepad"
    )
    print("Created virtual device: Xbox 360 Controller (XInput compatible)")

    # D-pad state tracking - Xbox 360 uses HAT only, not discrete buttons
    # Some games expect HAT axes for d-pad, not BTN_DPAD_* buttons

    try:
        for event in input_dev.read_loop():
            
            if event.type == e.EV_ABS:
                if event.code == e.ABS_X:
                    output_dev.write(e.EV_ABS, e.ABS_RX, event.value)
                elif event.code == e.ABS_Y:
                    output_dev.write(e.EV_ABS, e.ABS_RY, event.value)
                elif event.code == e.ABS_RX:
                    output_dev.write(e.EV_ABS, e.ABS_X, event.value)
                elif event.code == e.ABS_RY:
                    output_dev.write(e.EV_ABS, e.ABS_Y, event.value)
                elif event.code in (e.ABS_HAT0X, e.ABS_HAT0Y):
                    # Pass through D-pad as HAT axes only (XInput standard)
                    output_dev.write(e.EV_ABS, event.code, event.value)
                else:
                    output_dev.write(event.type, event.code, event.value)
            elif event.type == e.EV_KEY:
                # Filter out D-pad button events if input sends them
                # Xbox 360 uses HAT axes for d-pad, not discrete buttons
                if event.code in (e.BTN_DPAD_UP, e.BTN_DPAD_DOWN, e.BTN_DPAD_LEFT, e.BTN_DPAD_RIGHT):
                    continue
                output_dev.write(event.type, event.code, event.value)
            else:
                output_dev.write(event.type, event.code, event.value)
            output_dev.syn()
    except KeyboardInterrupt:
        print("\nStopping...")
    finally:
        output_dev.close()
        input_dev.close()

if __name__ == "__main__":
    main()
