#!/usr/bin/env python3
"""Temporarily detach USB HID input interfaces using a curses UI."""
import argparse
import curses
import fcntl
import json
import os
from pathlib import Path
import re
import signal
import sys
import textwrap

USB = Path('/sys/bus/usb/devices')
DRIVER = Path('/sys/bus/usb/drivers/usbhid')
STATE = Path('/run/input-toggle/state.json')
TYPES = {'JOYSTICK': 'Joystick / game controller', 'KEYBOARD': 'Keyboard',
         'MOUSE': 'Mouse', 'TOUCHPAD': 'Touchpad', 'TOUCHSCREEN': 'Touchscreen',
         'TABLET': 'Tablet', 'KEY': 'Buttons / keys', 'ACCELEROMETER': 'Accelerometer'}
FILTERS = ['All', *TYPES.values(), 'Other HID']
LOAD_BEARING = {'Keyboard', 'Mouse', 'Touchpad', 'Touchscreen', 'Tablet', 'Buttons / keys'}


def read(path):
    try:
        return path.read_text().strip()
    except OSError:
        return ''


def identity(interface):
    parent = interface.resolve().parent
    return [read(parent / k) for k in ('idVendor', 'idProduct', 'serial', 'busnum', 'devnum')]


def scan(saved=None):
    saved = saved or {}
    devices = []
    for interface in sorted(USB.glob('*:*')):
        driver = (interface / 'driver').resolve().name
        old = saved.get(interface.name)
        if old and old['identity'] != identity(interface):
            old = None
        unbound = not (interface / 'driver').exists()
        if driver != 'usbhid' and not (unbound and read(interface / 'bInterfaceClass') == '03'):
            continue
        names, kinds = set(), set()
        if read(interface / 'bInterfaceSubClass') == '01':
            boot_type = {'01': 'Keyboard', '02': 'Mouse'}.get(read(interface / 'bInterfaceProtocol'))
            if boot_type:
                kinds.add(boot_type)
        for node in interface.glob('*/input/input*'):
            name = read(node / 'name')
            if name:
                names.add(name)
            for event in node.glob('event*'):
                props = read(Path('/run/udev/data') / ('c' + read(event / 'dev')))
                for key, label in TYPES.items():
                    if f'E:ID_INPUT_{key}=1' in props.splitlines():
                        kinds.add(label)
            if list(node.glob('js*')):
                kinds.add(TYPES['JOYSTICK'])
        parent = interface.resolve().parent
        vid, pid, *_ = identity(interface)
        # USB ID from the supplied T-Rudder notes; works even without udev tags.
        if (vid, pid) == ('044f', 'b679'):
            kinds.add(TYPES['JOYSTICK'])
        if old and unbound:
            names.update([old['name']])
            kinds.update(old['types'])
        devices.append({'id': interface.name, 'identity': identity(interface),
                        'name': ' / '.join(sorted(names)) or read(parent / 'product') or 'USB HID device',
                        'types': sorted(kinds) or ['Other HID'], 'disabled': driver != 'usbhid'})
    return devices


def filtered(devices, category, query):
    return [d for d in devices if (category == 'All' or category in d['types'])
            and query.casefold() in (' '.join([d['name'], d['id'], *d['identity'], *d['types']])).casefold()]


class Controller:
    def __init__(self):
        try:
            saved = json.loads(read(STATE) or '{}')
        except ValueError:
            saved = {}
        self.saved = {k: v for k, v in saved.items()
                      if isinstance(v, dict) and isinstance(v.get('identity'), list)
                      and isinstance(v.get('name'), str) and isinstance(v.get('types'), list)
                      and all(isinstance(t, str) for t in v['types'])} if isinstance(saved, dict) else {}

    def save(self):
        temp = STATE.with_suffix('.tmp')
        temp.write_text(json.dumps(self.saved, indent=2))
        temp.replace(STATE)

    def toggle(self, device, confirmed=False):
        if os.geteuid() != 0:
            raise RuntimeError('Run with sudo to enable or disable devices.')
        interface = USB / device['id']
        if not re.fullmatch(r'\d+-[\d.]+:\d+\.\d+', device['id']):
            raise RuntimeError('Invalid USB interface ID.')
        if identity(interface) != device['identity']:
            raise RuntimeError('Device changed; refresh and select it again.')
        if device['disabled']:
            if (interface / 'driver').exists():
                raise RuntimeError('Device already has a driver; refresh and select it again.')
            if read(interface / 'bInterfaceClass') != '03':
                raise RuntimeError('Device is no longer a USB HID interface.')
            (DRIVER / 'bind').write_text(device['id'])
            self.saved.pop(device['id'], None)
            self.save()
            return
        if needs_confirmation(device) and not confirmed:
            raise RuntimeError('Protected keyboard, pointer, key, or unknown interface requires confirmation.')
        if (interface / 'driver').resolve() != DRIVER.resolve():
            raise RuntimeError('Device is no longer attached to usbhid.')
        self.saved[device['id']] = device
        self.save()  # Record recovery information before detaching.
        (DRIVER / 'unbind').write_text(device['id'])

    def restore(self, key):
        device = self.saved[key]
        interface = USB / key
        if not re.fullmatch(r'\d+-[\d.]+:\d+\.\d+', key):
            raise RuntimeError('Invalid saved USB interface ID.')
        if interface.exists() and identity(interface) == device['identity']:
            if not (interface / 'driver').exists():
                (DRIVER / 'bind').write_text(key)
        del self.saved[key]
        self.save()

    def restore_all(self):
        errors = []
        for key in list(self.saved):
            try:
                self.restore(key)
            except (OSError, RuntimeError) as exc:
                errors.append(f'{key}: {exc}')
        return errors


def needs_confirmation(device):
    return not device['disabled'] and bool(set(device['types']) & (LOAD_BEARING | {'Other HID'}))


def confirm_disable(screen, device):
    """Only lowercase y confirms; never hide details behind truncation."""
    screen.timeout(-1)
    try:
        height, width = screen.getmaxyx()
        details = ["ARE YOU ABSOLUTELY SURE YOU KNOW WHAT YOU'RE DOING?",
                   'Device: ' + device['name'], 'Types: ' + ', '.join(device['types']),
                   f'USB: {device["identity"][0]}:{device["identity"][1]}   Interface: {device["id"]}',
                   'Disables ALL input functions on this interface, including any keyboard or pointer.',
                   'You may lose control of this computer. Quitting will NOT re-enable it.',
                   'Use another input device or unplug/reconnect this device to recover.',
                   'Press lowercase y to disable. ANY other key cancels.']
        lines = [part for detail in details for part in textwrap.wrap(
            ''.join(c if c.isprintable() else '?' for c in detail), max(1, width - 1))]
        fits = width >= 30 and height >= len(lines) + 2
        screen.erase()
        if fits:
            for y, line in enumerate(lines):
                screen.addnstr(y, 0, line, width - 1)
        elif height and width > 1:
            screen.addnstr(0, 0, 'Terminal too small. Any key cancels.', width - 1)
        screen.refresh()
        key = screen.get_wch()
        return fits and key == 'y'
    finally:
        screen.timeout(1000)


def ui(screen, controller, args):
    curses.curs_set(0)
    screen.timeout(1000)
    category = FILTERS.index(args.type)
    query, selected, message = args.search, 0, 'Select a device, then press Space to toggle.'
    while True:
        devices = filtered(scan(controller.saved), FILTERS[category], query)
        selected = min(selected, max(0, len(devices) - 1))
        screen.erase()
        height, width = screen.getmaxyx()
        def line(y, text, attr=0):
            if 0 <= y < height and width > 1:
                screen.addnstr(y, 0, ''.join(c if c.isprintable() else '?' for c in text), width - 1, attr)
        line(0, 'INPUT TOGGLE  |  USB HID devices', curses.A_BOLD)
        line(1, f'Type: {FILTERS[category]}   Search: {query or "(none)"}   {len(devices)} interfaces')
        line(2, 'Tab: type  /: search  Up/Down: select  Space: toggle  q: quit')
        page = max(1, height - 8)
        start = (selected // page) * page
        for row, device in enumerate(devices[start:start + page], 4):
            status = 'DISABLED' if device['disabled'] else 'enabled '
            line(row, f'{status}  {device["name"]}  [{", ".join(device["types"])}]  {device["id"]}',
                 curses.A_REVERSE if start + row - 4 == selected else 0)
        if not devices:
            line(4, 'No matching devices. Try another type or clear the search.')
        if devices:
            d = devices[selected]
            line(height - 3, f'USB {d["identity"][0]}:{d["identity"][1]}  Interface {d["id"]}  (one row per interface)')
        line(height - 2, message)
        line(height - 1, 'Disabled devices stay disabled after quitting. Reopen this app to enable them.')
        screen.refresh()
        key = screen.getch()
        if key in (ord('q'), 27):
            return
        if key in (curses.KEY_DOWN, ord('j')):
            selected = min(selected + 1, max(0, len(devices) - 1))
        elif key in (curses.KEY_UP, ord('k')):
            selected = max(0, selected - 1)
        elif key in (9, curses.KEY_BTAB):
            category = (category + (-1 if key == curses.KEY_BTAB else 1)) % len(FILTERS)
            selected = 0
        elif key == ord('/'):
            screen.timeout(-1)
            curses.curs_set(1)
            try:
                while True:
                    screen.move(1, 0)
                    screen.clrtoeol()
                    line(1, 'Search (Enter to finish): ' + query)
                    screen.refresh()
                    char = screen.get_wch()
                    if char in ('\n', '\r', '\x1b'):
                        break
                    if char in (curses.KEY_BACKSPACE, '\x7f', '\b'):
                        query = query[:-1]
                    elif isinstance(char, str) and char.isprintable():
                        query += char
            finally:
                curses.curs_set(0)
                screen.timeout(1000)
            selected = 0
        elif key == ord(' ') and devices:
            try:
                device = devices[selected]
                confirmed = False
                if needs_confirmation(device):
                    confirmed = confirm_disable(screen, device)
                    if not confirmed:
                        message = 'Cancelled; device unchanged.'
                        continue
                controller.toggle(device, confirmed=confirmed)
                message = 'Device enabled.' if devices[selected]['disabled'] else 'Device disabled. You can quit and reopen this app to enable it later.'
            except (OSError, RuntimeError) as exc:
                message = str(exc)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--search', default='', help='Initial name or USB ID search')
    parser.add_argument('--type', choices=FILTERS, default='All', help='Initial readable device type')
    parser.add_argument('--list', action='store_true', help='List devices without changing anything')
    parser.add_argument('--restore', action='store_true', help='Restore devices saved by a previous run')
    args = parser.parse_args()
    lock = None
    if os.geteuid() == 0 and not args.list:
        STATE.parent.mkdir(mode=0o700, exist_ok=True)
        lock = (STATE.parent / 'lock').open('w')
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            parser.exit(1, 'Another input-toggle instance is running.\n')
    controller = Controller()
    if args.list:
        for d in filtered(scan(controller.saved), args.type, args.search):
            print(f'{d["id"]:16} {"disabled" if d["disabled"] else "enabled":8} {d["name"]} [{", ".join(d["types"])}]')
        return 0
    if args.restore and os.geteuid() != 0:
        parser.exit(1, 'Use sudo for --restore.\n')
    def stop(signum, frame):
        raise KeyboardInterrupt
    for sig in (signal.SIGTERM, signal.SIGHUP):
        signal.signal(sig, stop)
    errors = []
    try:
        if args.restore:
            errors = controller.restore_all()
            for error in errors:
                print('Restore failed: ' + error, file=sys.stderr)
        else:
            curses.wrapper(ui, controller, args)
    except KeyboardInterrupt:
        pass
    finally:
        if lock is not None:
            lock.close()
    return 1 if errors else 0


if __name__ == '__main__':
    sys.exit(main())
