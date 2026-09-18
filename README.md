# Input Toggle

A Python curses terminal interface for temporarily disabling USB HID input interfaces, including the Thrustmaster T-Rudder. Uses Python's standard library; no pip packages required.

Open a terminal and run:

```sh
cd '/home/conneh/actual/NIXOS HIVE/input-toggle'
sudo python3 input-toggle.py --search 'Thrustmaster'
```

Enter your sudo password if prompted (the terminal will not display it as you type). Select the T-Rudder with the arrow keys, press **Space** to disable it, then **q** to quit. Run the same command again and press **Space** to re-enable it when you want to play Elite Dangerous.

Or, from this folder, start filtered to controllers:

```sh
sudo python3 input-toggle.py --type 'Joystick / game controller'
```

- **Tab / Shift+Tab**: cycle human-readable device types.
- **/**: edit the name, type, or USB ID search; Backspace clears characters, Enter finishes.
- **Up / Down** (or **j / k**): select an interface.
- **Space**: disable or re-enable it.
- **q / Escape**: quit, leaving devices in their current state.

Disable the pedals, quit, and play your game. When you want the pedals back, reopen the program with sudo, select the disabled T-Rudder, and press Space to enable it. Disabled interfaces remain visible across app launches. The list refreshes every second. Run without sudo for browsing only, or use `python3 input-toggle.py --list` for plain text output.

The program detaches the selected interface from `usbhid`, hiding its input devices system-wide. It discovers current USB paths automatically. One row represents one interface, which may contain several input nodes. Disabling keyboards, mice, touchpads, touchscreens, tablets, key interfaces, or unknown HID types opens an extra confirmation showing the device name, types, USB ID, and interface. Only lowercase **y** confirms immediately, without Enter. Every other key cancels immediately, including uppercase Y, Enter, Space, Escape, and arrow keys. If the terminal is too small to display the details, confirmation is unavailable; enlarge it and try again. The prompt explains that you may lose input control and can recover using another input device or by unplugging/reconnecting the affected device. Enabling does not require this confirmation. Classification uses local udev input tags, joystick nodes, and the T-Rudder USB ID `044f:b679`.

Quitting, Ctrl+C, and closing the terminal leave disabled devices disabled. To explicitly re-enable all devices disabled by this app, run:

```sh
sudo python3 input-toggle.py --restore
```

Discovery reads live USB interface descriptors and driver bindings from sysfs on every refresh. An unbound HID interface appears as disabled even if it was detached outside this app or all saved records are missing or corrupt. “Disabled” means no interface driver is attached; the app cannot determine why. Selecting it and pressing Space attempts to bind `usbhid`; incompatible devices report the kernel error.

Records in `/run/input-toggle/` are optional for discovery and individual re-enabling. They preserve richer device names/types after unbinding and track which devices the explicit `--restore` command should restore. `--restore` only restores recorded devices; use the UI to enable an unrecorded interface. Records survive program crashes and disappear at reboot. Without records, product names and boot keyboard/mouse types come from USB descriptors; the T-Rudder is recognized by USB ID, while other devices may appear as `Other HID` until enabled. Unplugging/replugging or rebooting also restores normal driver attachment. There are no persistent udev rules or system configuration changes. Recovery checks the USB connection identity before rebinding; errors retain the record for another attempt. Only one privileged instance can run at a time.

On NixOS, if Python is not already installed, obtain it through `nix-shell -p python3`, then run `sudo "$(command -v python3)" input-toggle.py --search Thrustmaster`.

Run the simulated-device tests:

```sh
python3 -m unittest discover -s tests -v
```

Implementation follows the kernel's [USB interface unbinding guidance](https://cdn.kernel.org/doc/html/latest/driver-api/usb/power-management.html): detach the interface driver, not the parent USB device.

The live discovery fields are documented in the kernel’s [USB sysfs ABI](https://github.com/torvalds/linux/blob/master/Documentation/ABI/testing/sysfs-bus-usb).
