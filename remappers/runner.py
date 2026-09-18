#!/usr/bin/env python3
"""Run a copied profile on the exact selected controller interface."""
import argparse
import importlib
import importlib.util
import json
import os
from pathlib import Path
import signal
import socket
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = Path(__file__).resolve().parent / 'mergetriggers'
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(SCRIPTS))
from remapping import PROFILES


def load_evdev():
    try:
        return importlib.import_module('evdev')
    except ImportError:
        vendor = SCRIPTS / 'vendor' / f'python{sys.version_info.major}.{sys.version_info.minor}'
        sys.path.insert(0, str(vendor))
        try:
            return importlib.import_module('evdev')
        except ImportError as exc:
            raise RuntimeError('evdev is unavailable for this Python. Run from the provided nix-shell '
                               'or install remappers/mergetriggers/requirements.txt.') from exc


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--check', action='store_true')
    parser.add_argument('--profile', choices=PROFILES)
    parser.add_argument('--interface')
    parser.add_argument('--identity')
    parser.add_argument('--event')
    parser.add_argument('--uid', type=int)
    parser.add_argument('--gid', type=int)
    args = parser.parse_args()
    evdev = load_evdev()
    if not Path('/dev/uinput').exists():
        result = subprocess.run(['modprobe', 'uinput'], capture_output=True, text=True, timeout=5)
        if result.returncode:
            raise RuntimeError('Cannot load uinput: ' + result.stderr.strip())
    if not os.access('/dev/uinput', os.W_OK):
        raise RuntimeError('/dev/uinput is not writable. Run input-toggle with sudo.')
    if args.check:
        print('evdev and uinput available')
        return
    if any(value is None for value in (args.profile, args.interface, args.identity, args.event, args.uid, args.gid)):
        parser.error('profile, interface, identity, event, uid and gid are required')
    app = importlib.import_module('input-toggle')
    source = app.USB / args.interface
    expected_identity = json.loads(args.identity)
    if app.identity(source) != expected_identity or args.event not in app.input_files(source):
        raise RuntimeError('Source controller changed before the remapper started.')
    evpath = app.DEV_INPUT / args.event
    label, script, expected_usb_id, path_variable = PROFILES[args.profile]
    spec = importlib.util.spec_from_file_location('selected_profile', SCRIPTS / script)
    profile = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(profile)
    opened = []
    outputs = []

    def physical_device(path):
        if Path(path) != evpath or app.identity(source) != expected_identity:
            raise RuntimeError('Refusing to open a different physical controller.')
        device = evdev.InputDevice(str(evpath))
        opened.append(device)
        info = os.fstat(device.fd)
        expected_dev = app.read(app.node_sysfs(source, args.event) / 'dev')
        if expected_dev != f'{os.major(info.st_rdev)}:{os.minor(info.st_rdev)}':
            raise RuntimeError('Physical input node changed.')
        if (device.info.vendor, device.info.product) != tuple(int(value, 16) for value in expected_usb_id):
            raise RuntimeError('Selected input does not match the chosen replacement profile.')
        device.grab()
        return device

    def virtual_device(*positional, **keywords):
        # A unique phys value avoids confusing this output with a physical Xbox pad.
        keywords['phys'] = f'input-toggle/{args.interface}/{args.profile}'
        output = evdev.UInput(*positional, **keywords)
        outputs.append(output)
        if output.device is None:
            raise RuntimeError('Virtual controller has no event node.')
        event_name = Path(output.device.path).name
        sysfs_input = (Path('/sys/class/input') / event_name / 'device').resolve()
        if app.read(sysfs_input / 'phys') != keywords['phys']:
            raise RuntimeError('Virtual controller identity mismatch.')
        subprocess.run(['udevadm', 'settle', '--timeout=3'], check=True, capture_output=True, timeout=4)
        # Give the launching user access to both evdev and joydev output nodes.
        for node in sysfs_input.iterdir():
            if not node.name.startswith(('event', 'js')):
                continue
            fd = app.AccessController().open_node(node.name)
            try:
                info = os.fstat(fd)
                if app.read(node / 'dev') != f'{os.major(info.st_rdev)}:{os.minor(info.st_rdev)}':
                    raise RuntimeError('Virtual input node changed.')
                app.remove_acl(fd)
                os.fchown(fd, args.uid, args.gid)
                os.fchmod(fd, 0o660)
            finally:
                os.close(fd)
        # Type=notify lets the UI wait for a real, accessible virtual output.
        address = os.environ.get('NOTIFY_SOCKET')
        if address:
            if address.startswith('@'):
                address = '\0' + address[1:]
            with socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM) as notify:
                notify.sendto(b'READY=1\nSTATUS=Physical controller grabbed; virtual output ready', address)
        print(f'Shadowing {evpath} with {label} for UID {args.uid}', flush=True)
        return output

    def stop(signum, frame):
        raise KeyboardInterrupt

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    setattr(profile, path_variable, str(evpath))
    profile.InputDevice = physical_device
    profile.UInput = virtual_device
    try:
        profile.main()
    finally:
        for output in outputs:
            output.close()
        for device in opened:
            device.close()


if __name__ == '__main__':
    try:
        main()
    except KeyboardInterrupt:
        pass
    except Exception as exc:
        print(f'Remapper failed: {exc}', file=sys.stderr, flush=True)
        sys.exit(1)
