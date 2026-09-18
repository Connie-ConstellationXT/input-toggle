# Input Toggle

Terminal UI for managing game input devices on Linux. It finds devices by current USB identity and readable type, so changing `/dev/input/event*` numbers after a reboot does not require editing scripts.

## Start

```sh
cd '/home/conneh/actual/NIXOS HIVE/input-toggle'
sudo python3 input-toggle.py
```

Useful shortcuts:

```sh
sudo python3 input-toggle.py --search Thrustmaster
sudo python3 input-toggle.py --search F710
sudo python3 input-toggle.py --type 'Joystick / game controller'
```

For NixOS, `nix-shell` in this folder provides Python, evdev, systemd tools, and `modprobe` for remapping.

## Install from a NixOS flake

Add this repository as an input in your system flake. For a local checkout:

```nix
inputs.input-toggle.url = "path:/home/conneh/actual/NIXOS HIVE/input-toggle";
```

Then accept `input-toggle` in `outputs`, include its module in `nixosSystem`, and enable it in your configuration. This uses NixOS system configuration only; Home Manager is not needed.

```nix
# flake.nix: add input-toggle alongside your other inputs
outputs = { nixpkgs, input-toggle, ... }: {
  nixosConfigurations.nixos = nixpkgs.lib.nixosSystem {
    # ...
modules = [
  ./configuration.nix
  input-toggle.nixosModules.default
];
  };
};
```

```nix
# configuration.nix
programs.input-toggle.enable = true;
```

`nixos-rebuild switch --flake .#nixos` installs `input-toggle` system-wide and loads `uinput` at boot for virtual-controller remapping. To omit automatic `uinput` loading:

```nix
programs.input-toggle.enableUinput = false;
```

For a published repository, replace the local URL with `github:OWNER/input-toggle`. The package is also available directly as `inputs.input-toggle.packages.${pkgs.system}.default`.

## Features and uses

| Feature | Use case |
| --- | --- |
| Disable a driver | Hide the T-Rudder from a Unity game that treats pedals as unwanted camera input. Re-enable it later for Elite Dangerous. |
| Root-only physical input | Keep a controller enabled while preventing ordinary applications from opening its individual input nodes. Original user/group permissions and ACLs can be restored. |
| F710 replacement controller | Shadow the physical F710 and expose a virtual controller with SwapSticks, merged triggers, or both. |
| T-Rudder replacement controller | In Warframe, use the pedals as a smooth forward/backward analog stick for Yareli's Merulina K-Drive. |
| Live discovery | Find a bound or unbound supported device after reconnecting or rebooting, without a hardcoded USB port or event number. |

## Controls

| Key | Action |
| --- | --- |
| Tab / Shift+Tab | Filter by readable device type |
| / | Search name, type, USB ID, or interface ID |
| Up / Down or j / k | Select an interface |
| Space | Disable or enable its kernel driver |
| p | Make physical input nodes root-only, or restore their saved permissions and ACLs |
| r | Choose, change, or stop a compatible replacement remapper |
| q / Escape | Quit; changes remain in effect |

Rows are green for enabled devices, red for disabled or root-only devices, and amber for a running replacement, mixed access, or an uncertain remapper state. Text labels remain useful in monochrome terminals.

Disabling or restricting a keyboard, pointer, key interface, or unknown HID device shows an explicit warning with its name and USB interface. Only lowercase `y` confirms; every other key cancels.

## Common workflows

### Keep T-Rudder out of a game

Search for `Thrustmaster`, select the T-Rudder, press Space, then `q`. Its `usbhid` interface is detached and the physical input nodes disappear. Reopen the app later and press Space to restore it.

### Use the T-Rudder for smooth Yareli K-Drive movement

Yareli rides Merulina, which uses K-Drive movement controls. Search for `Thrustmaster`, select the T-Rudder, press `r`, then `1`. The pedal's continuous axis becomes the virtual controller's forward/backward left-stick axis, giving smooth movement instead of keyboard-style on/off input. The legacy `TRUDDER_PATH` in `Yareli_continuous_throttle.py` is overridden, so an event-number change after reboot is safe.

Press `r`, then `0` to stop Yareli and leave the pedals disabled. Press `r`, then `e` to stop Yareli and restore native pedal input and saved access permissions.

### Use a remapped F710

Put the F710 in XInput (`X`) mode. Search for `F710`, select it, then press `r`.

| Choice | Virtual controller |
| --- | --- |
| 1 | SwapSticks |
| 2 | Merged triggers into signed `ABS_MISC` |
| 3 | SwapSticks plus merged triggers |
| 0 | Stop remapping and leave the F710 disabled |
| e | Stop remapping and restore native F710 input |

The menu starts the selected remapper as a transient systemd service. You can quit Input Toggle and launch a game; the amber `SHADOWED` entry shows that it remains active. Reopen Input Toggle to switch profile or stop it. F710 scripts also receive the current event node rather than their old hardcoded `DEVICE_PATH` value.

### Give root-only access to a device

Select an enabled device and press `p` before opening the game. The app saves the original ownership, mode, and POSIX ACL of its individual `event*`, `js*`, and `mouse*` nodes, then makes them root-owned `0600`. Press `p` again to restore the saved access.

This blocks new non-root opens only. It cannot revoke an input handle already opened by a game or desktop service, and it does not block raw USB, `hidraw`, or `/dev/input/mice`. Use Space when the physical device must disappear completely.

## Persistence and recovery

Driver and access changes survive quitting the UI. Replugging, rebinding, and rebooting recreate device nodes with normal system defaults. Remappers stop at reboot or unplug; start a profile again after boot.

Temporary recovery records live in `/run/input-toggle/` until reboot. Do not remove `access.json` while a device is root-only: it contains the original ACLs needed for exact restoration.

```sh
# Restore interfaces the app detached
sudo python3 input-toggle.py --restore

# Restore saved input-node permissions and ACLs
sudo python3 input-toggle.py --restore-access

# Browse without changing anything
python3 input-toggle.py --list
```

Stop a replacement using `r` before running either bulk recovery command. If a remapper fails, it releases its exclusive grab; its saved root-only permissions still block new normal-user opens until restored.

## Included remappers

`remappers/mergetriggers/` contains copied Mergetriggers source scripts, their helpers, requirements, and evdev 1.9.2 copies for CPython 3.12/3.13 on Linux x86-64. The original source project was left unchanged. `remappers/runner.py` supplies the selected device’s live event node, validates its USB identity, grabs physical input, and creates the virtual output.

For a different Python version or architecture, use `nix-shell` or install `remappers/mergetriggers/requirements.txt` into the Python environment used to start Input Toggle.

If a remapper does not start, inspect its transient service:

```sh
sudo systemctl list-units --all 'input-toggle-remap-*'
sudo journalctl -u 'input-toggle-remap-*' -n 80 --no-pager
```
