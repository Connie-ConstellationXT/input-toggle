# trigger_util.py
# Utility for merging left/right triggers into a single axis value

def merged_triggers(left_trigger, right_trigger, out_min=-32767, out_max=32767):
    """
    Merge left and right trigger values (0-255 each) into a single signed axis value.
    Returns an int in the range [out_min, out_max].
    - Right trigger positive, left trigger negative, both zero = center.
    """
    if right_trigger > 0:
        merged = int((right_trigger / 255.0) * out_max)
    elif left_trigger > 0:
        merged = -int((left_trigger / 255.0) * abs(out_min))
    else:
        merged = 0
    return merged
