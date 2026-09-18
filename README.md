# Input Toggle

A curses terminal app for temporarily disabling USB input interfaces or restricting their input nodes to root. Supports USB HID (`usbhid`) and Xbox-compatible controllers (`xpad`), including the Thrustmaster T-Rudder and Logitech F710. The basic toggles require Linux and Python 3. Remapping also uses python-evdev, uinput, and systemd; local evdev copies are included, with a Nix shell for other Python versions.

## Run

```sh
cd '/home/conneh/actual/NIXOS HIVE/input-toggle'
sudo python3 input-toggle.py
```

Enter your sudo password if prompted (nothing is displayed as you type). To start with a device search or type filter:

```sh
sudo python3 input-toggle.py --search Thrustmaster
sudo python3 input-toggle.py --search F710
sudo python3 input-toggle.py --type 'Joystick / game controller'
```

On NixOS, if Python is unavailable, run `nix-shell -p python3`, then `sudo "$(command -v python3)" input-toggle.py` from this folder.

## Controls

| Key | Action |
| --- | --- |
| Tab / Shift+Tab | Cycle readable device types |
| / | Edit name, type, or USB ID search; Backspace deletes, Enter finishes |
| Up / Down or j / k | Select an interface |
| Space | Disable or enable the interface's driver |
| p | Restrict input access to root, or restore saved permissions |
| r | Choose an F710 replacement remapper, stop it, or return to native input |
| q / Escape | Quit, leaving changes in place |

Disabling or restricting keyboards, pointers, key interfaces, and unknown HID types shows an extra confirmation with the device name, types, USB ID, and interface. **Only lowercase `y` confirms. Every other key cancels immediately.** Enabling or restoring permissions needs no extra confirmation. A terminal too small to show the warning cannot confirm it.

## Two ways to keep a controller out of a game

**Disable the interface:** select the T-Rudder or F710, press **Space**, then **q**. The interface is detached from its driver, and its input nodes disappear. Play your game. Reopen the app and press **Space** to enable it before playing Elite Dangerous. The app discovers the current USB path rather than relying on a hardcoded port.

**Keep it enabled, restrict access:** select an enabled device, press **p**, then **q**. The app saves each node's original owner, group, permission bits, and full POSIX access ACL before changing anything. It then makes the interface's individual `/dev/input/event*`, `js*`, and `mouse*` nodes root-owned with mode `0600`, removing extended ACL grants. This blocks non-root read **and write** access. Press **p** again after reopening the app to restore the exact saved permissions and ACLs, including user and group grants.

Rows are **green** when enabled, **red** when disabled or root-only, and **amber** when shadowed by a running remapper. Amber shadowed rows include the profile name, such as `SHADOWED: SwapSticks`. Mixed permissions and uncertain remapper status also use amber, with explicit text. Terminals with only eight colors use yellow for amber; monochrome terminals retain the status labels.

The selected row’s access details show `normal`, `root-only`, or `mixed`; `(saved)` means a permission snapshot is available. `unavailable` means an expected node cannot be inspected. The USB interface, driver, and node names also appear below the list.

Apply root-only access **before launching the game**. Permissions prevent new opens; they do not revoke already-open handles. Existing games, desktop input services, and programs with elevated privileges can still receive input. This is specifically a `/dev/input` permission change: it does not block raw USB, `/dev/hidraw`, or the shared `/dev/input/mice` aggregate. Use driver disabling when you need the interface removed altogether.

Changes remain after quitting, Ctrl+C, or closing the terminal. Replugging, rebooting, or rebinding recreates device nodes with system defaults. Device management services such as udev/logind can also change permissions later; this app does not install persistent rules or a background enforcement service. Recheck the access column if that happens.

## Shadow the F710 with a Python remapper

Put the F710’s switch in **X** (XInput) mode, then run:

```sh
sudo python3 input-toggle.py --search F710
```

Select the F710 (enabled, root-only, or disabled) and press **r**:

| Choice | Replacement |
| --- | --- |
| 1 | SwapSticks: swap left/right sticks, with an Xbox 360 virtual identity |
| 2 | Merged triggers: one signed `ABS_MISC` axis, retaining the original stick layout |
| 3 | SwapSticks + merged triggers |
| 0 | Stop the replacement and leave the physical F710 disabled |
| e | Stop the replacement and restore native input plus saved permissions |

Choose a profile, wait for the **amber SHADOWED** row, then press **q** and launch the game. Reopen the app and use **r** to switch profiles or stop remapping. **Space** on a shadowed row stops the replacement and disables the physical interface. Changing permissions with **p** is blocked while a replacement is active; use **r**, then **e**, to restore normal access.

The Python scripts need physical input events. If the F710 was unbound, the app rebinds `xpad`, waits for its input nodes, and restricts them to root. The selected script runs as root with an exclusive grab and creates a virtual controller whose event/joystick nodes are owned by the user who invoked sudo. Run the app using sudo from your normal user session so it knows which user should receive the virtual device.

Each remapper runs as a transient systemd service, identified by the current USB connection. Closing the app or terminal leaves it running. Reopening the app checks the live service rather than trusting a remembered PID. The service reports ready only after grabbing the source and creating an accessible virtual output. Startup failures attempt to return the physical controller to its prior disabled/access state. Switching profiles destroys the old virtual controller and creates a new one; relaunch games that do not handle this well.

Remappers do not auto-restart after failure, unplugging, or reboot. A failed remapper releases its grab; existing physical-device handles may receive input again, while the saved root-only permissions still block new non-root opens. The row stops claiming it is shadowed. Reopen the app to start a profile again or restore native access. The copied profiles do not implement force feedback.

Source scripts, their local helpers, dependency metadata, and evdev 1.9.2 (including its license) were copied into [`remappers/mergetriggers/`](remappers/mergetriggers/). The original project was left unchanged. The runner supplies the selected event path, so its operation does not depend on the scripts’ old hardcoded event numbers. The unrelated T-Rudder/Yareli and diagnostic scripts are included as source references, but are not F710 menu choices.

Bundled evdev extensions are for Linux x86-64 CPython 3.12 and 3.13. A matching installed evdev is preferred; otherwise the runner uses the matching bundled copy. For a different interpreter, use the provided Nix shell:

```sh
nix-shell
sudo "$(command -v python3)" input-toggle.py --search F710
```

Or install `remappers/mergetriggers/requirements.txt` in a virtual environment and launch the app with that environment’s Python. Root-only/driver toggles still work without evdev. The app loads the `uinput` kernel module on remapper startup if needed; it does not install permanent system services or udev rules.

For service diagnostics:

```sh
sudo systemctl list-units --all 'input-toggle-remap-*'
sudo journalctl -u 'input-toggle-remap-*' -n 80 --no-pager
```

Stop remappers through **r** before using the bulk recovery commands below. If you manually stop a service with systemctl, its physical input remains root-only; reopen the app and press **p** to restore its saved permissions.

## Discovery and recovery

Discovery reads current USB descriptors and driver bindings on every refresh. Bound `usbhid` and `xpad` interfaces are listed. Unbound HID interfaces and the F710's XInput interface can be found without saved state. Other previously disabled `xpad` interfaces use the recorded driver when available. “Disabled” means no interface driver is attached; the app cannot determine why.

The F710 in XInput mode uses `xpad`, with input nodes directly below the USB interface. Both that layout and HID's nested input layout are supported. The device is recognized as a joystick/game controller in either supported mode.

Records live in `/run/input-toggle/` and survive app restarts until reboot:

- `state.json` caches names/types and remembers interfaces detached by this app. Live discovery and individual HID/F710 re-enabling work without it. Without cached tags, some unbound devices appear as `Other HID`.
- `access.json` stores original node permissions and ACLs. **Keep this file until you restore access.** Original permissions cannot be reconstructed statelessly after they have been overwritten. If records are missing, unplug/reconnect to obtain your system's default permissions. Corrupt permission records are reported rather than silently overwritten.

Explicit recovery commands, run from this folder:

```sh
# Re-enable interfaces recorded as disabled by this app:
sudo python3 input-toggle.py --restore

# Restore recorded input-node permissions and ACLs:
sudo python3 input-toggle.py --restore-access
```

Restoration checks USB connection identity, sysfs input paths, and node identity to avoid applying an old snapshot to another device. Removed or replaced nodes are skipped. Failed permission changes attempt rollback; failed restorations retain their snapshot for retry. Only one privileged instance runs at a time.

Run without sudo to browse, or list devices as plain text:

```sh
python3 input-toggle.py --list
```

## Tests

```sh
python3 -m unittest discover -s tests -v
```

Hardware remapping is intended to be checked in your own shell. Existing tests use simulated USB devices and temporary files. Permission tests exercise real mode and POSIX ACL changes on temporary files, with device-type checks and ownership changes mocked; they never change your hardware.

Implementation references: [USB interface unbinding](https://cdn.kernel.org/doc/html/latest/driver-api/usb/power-management.html), [USB sysfs ABI](https://github.com/torvalds/linux/blob/master/Documentation/ABI/testing/sysfs-bus-usb), [xpad's F710 entry](https://github.com/torvalds/linux/blob/master/drivers/input/joystick/xpad.c), and [POSIX ACL permission semantics](https://man7.org/linux/man-pages/man5/acl.5.html).
