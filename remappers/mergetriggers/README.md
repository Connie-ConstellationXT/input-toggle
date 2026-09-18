# Gamepad Daemons for Logitech F710

This repo contains Python scripts for creating virtual gamepad devices with custom features using your Logitech F710 on Linux (NixOS-friendly).

## Features

- **gamepad_daemon.py**: Combines both triggers into a single Z axis (xboxdrv --trigger-as-zaxis style).
- **gamepad_daemon_swapsticks.py**: Swaps left and right analog sticks.
- **gamepad_daemon_swapsticks_and_triggerz.py**: Swaps sticks and combines triggers into a single Z axis.

## Usage (NixOS)

1. Open a terminal in this project’s root directory.
2. Enter the Nix shell:
   ```bash
   nix-shell
   ```
3. Run the daemon of your choice:
   - In VS Code: `code .`
   - Or from the terminal:
     ```bash
     ./gamepad_daemon.py
     ./gamepad_daemon_swapsticks.py
     ./gamepad_daemon_swapsticks_and_triggerz.py
     ```

## Hiding the Original Device

If you want to hide the original device from games, revoke read permissions for other users (and possibly groups) on your input device (e.g. `/dev/input/event11`). For example:

```bash
sudo chmod o-r /dev/input/event11
```

Then run the Python script as a user (such as root) that still has read access to the device:

```bash
sudo ./gamepad_daemon_swapsticks.py
```

---

- All scripts require root (or appropriate permissions) to access input devices and create virtual devices.
- Device path may need to be changed in each script (`DEVICE_PATH`).
- No external dependencies except Python 3 and evdev (handled by Nix shell).