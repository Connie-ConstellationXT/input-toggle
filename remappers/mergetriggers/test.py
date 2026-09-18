from evdev import UInput, ecodes as e

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
        (e.ABS_X,   (0, -32768, 32767, 0, 0, 0)),  # Left stick X
        (e.ABS_Y,   (0, -32768, 32767, 0, 0, 0)),  # Left stick Y
        (e.ABS_RX,  (0, -32768, 32767, 0, 0, 0)),  # Right stick X
        (e.ABS_RY,  (0, -32768, 32767, 0, 0, 0)),  # Right stick Y
        (e.ABS_Z,   (0, -32767, 32767, 0, 0, 0)),  # Combined triggers axis
        (e.ABS_HAT0X, (0, -1, 1, 0, 0, 0)),        # D-pad X
        (e.ABS_HAT0Y, (0, -1, 1, 0, 0, 0)),        # D-pad Y
    ]
}

ui = UInput(capabilities, name="XInput Virtual Gamepad (Combined Trigger Axis)", bustype=e.BUS_USB)
print("Created XInput-compatible virtual gamepad with combined trigger axis (ABS_Z)")
input("Press Enter to exit and remove the device...")
ui.close()