from evdev import ecodes as e

def emit_dpad_buttons(output_dev, dpad_state, code, value):
    """
    Emits BTN_DPAD_* events based on ABS_HAT0X/ABS_HAT0Y changes.
    Modifies dpad_state in-place.
    """
    if code == e.ABS_HAT0X:
        left = 1 if value < 0 else 0
        right = 1 if value > 0 else 0
        if left != dpad_state[e.BTN_DPAD_LEFT]:
            output_dev.write(e.EV_KEY, e.BTN_DPAD_LEFT, left)
            dpad_state[e.BTN_DPAD_LEFT] = left
        if right != dpad_state[e.BTN_DPAD_RIGHT]:
            output_dev.write(e.EV_KEY, e.BTN_DPAD_RIGHT, right)
            dpad_state[e.BTN_DPAD_RIGHT] = right
    elif code == e.ABS_HAT0Y:
        up = 1 if value < 0 else 0
        down = 1 if value > 0 else 0
        if up != dpad_state[e.BTN_DPAD_UP]:
            output_dev.write(e.EV_KEY, e.BTN_DPAD_UP, up)
            dpad_state[e.BTN_DPAD_UP] = up
        if down != dpad_state[e.BTN_DPAD_DOWN]:
            output_dev.write(e.EV_KEY, e.BTN_DPAD_DOWN, down)
            dpad_state[e.BTN_DPAD_DOWN] = down
