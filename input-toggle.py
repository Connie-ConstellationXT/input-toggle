#!/usr/bin/env python3
"""Toggle USB input drivers or root-only input access using a curses UI."""
import argparse
import base64
import curses
import errno
import fcntl
import json
import os
from pathlib import Path
import re
import signal
import stat
import sys
import textwrap

from remapping import PROFILES, RemapperController, profiles_for, supported as remapping_supported

USB = Path('/sys/bus/usb/devices')
DRIVER = Path('/sys/bus/usb/drivers/usbhid')
STATE = Path('/run/input-toggle/state.json')
DEV_INPUT = Path('/dev/input')
SUPPORTED_DRIVERS = {'usbhid', 'xpad'}
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


def input_nodes(interface):
    return sorted(set(interface.glob('*/input/input*')) | set(interface.glob('input/input*')))


def input_files(interface):
    return sorted({child.name for node in input_nodes(interface) for child in node.iterdir()
                   if re.fullmatch(r'(event|js|mouse)\d+', child.name)})


def node_sysfs(interface, name):
    matches = [node / name for node in input_nodes(interface) if (node / name).exists()]
    if len(matches) != 1:
        raise RuntimeError('Input node changed; refresh and try again.')
    return matches[0].resolve()


def binding_driver(interface, old=None):
    if (interface / 'driver').exists():
        return (interface / 'driver').resolve().name
    if read(interface / 'bInterfaceClass') == '03':
        return 'usbhid'
    if identity(interface)[:2] == ['046d', 'c21f'] and read(interface / 'bInterfaceNumber') == '00':
        return 'xpad'
    return (old or {}).get('driver', '')


def driver_path(name):
    if name not in SUPPORTED_DRIVERS:
        raise RuntimeError('Unsupported input driver.')
    return DRIVER.parent / name


def scan(saved=None):
    saved = saved or {}
    devices = []
    for interface in sorted(USB.glob('*:*')):
        old = saved.get(interface.name)
        if old and old['identity'] != identity(interface):
            old = None
        unbound = not (interface / 'driver').exists()
        driver = binding_driver(interface, old)
        if driver not in SUPPORTED_DRIVERS:
            continue
        names, kinds = set(), set()
        if read(interface / 'bInterfaceSubClass') == '01':
            boot_type = {'01': 'Keyboard', '02': 'Mouse'}.get(read(interface / 'bInterfaceProtocol'))
            if boot_type:
                kinds.add(boot_type)
        for node in input_nodes(interface):
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
        if driver == 'xpad':
            kinds.add(TYPES['JOYSTICK'])
        if old and unbound:
            names.update([old['name']])
            kinds.update(old['types'])
        devices.append({'id': interface.name, 'identity': identity(interface),
                        'name': ' / '.join(sorted(names)) or read(parent / 'product') or 'USB HID device',
                        'types': sorted(kinds) or ['Other HID'], 'disabled': unbound,
                        'driver': driver, 'nodes': input_files(interface)})
    return devices


def filtered(devices, category, query):
    return [d for d in devices if (category == 'All' or category in d['types'])
            and query.casefold() in (' '.join([d['name'], d['id'], *d['identity'], *d['types']])).casefold()]


def atomic_json(path, data):
    temp = path.with_suffix('.tmp')
    with temp.open('w') as stream:
        os.fchmod(stream.fileno(), 0o600)
        json.dump(data, stream, indent=2)
        stream.flush()
        os.fsync(stream.fileno())
    temp.replace(path)


def acl_bytes(fd):
    try:
        return os.getxattr(fd, 'system.posix_acl_access')
    except OSError as exc:
        if exc.errno in (errno.ENODATA, errno.ENOTSUP):
            return None
        raise


def remove_acl(fd):
    try:
        os.removexattr(fd, 'system.posix_acl_access')
    except OSError as exc:
        if exc.errno not in (errno.ENODATA, errno.ENOTSUP):
            raise


def fingerprint(info):
    return [info.st_dev, info.st_ino, info.st_rdev]


class AccessController:
    """Save original permissions before restricting; restore only the same nodes."""
    def __init__(self):
        self.path = STATE.parent / 'access.json'
        try:
            self.saved = json.loads(self.path.read_text())
            if not isinstance(self.saved, dict):
                raise ValueError('expected a mapping')
            for entry in self.saved.values():
                if (not isinstance(entry, dict) or not isinstance(entry.get('nodes'), list)
                        or not isinstance(entry.get('identity'), list)):
                    raise ValueError('invalid permission record')
                for record in entry['nodes']:
                    if (not isinstance(record, dict)
                            or not isinstance(record.get('name'), str)
                            or not isinstance(record.get('sysfs'), str)
                            or not isinstance(record.get('fingerprint'), list)
                            or any(not isinstance(record.get(k), int) for k in ('uid', 'gid', 'mode'))
                            or 'acl' not in record):
                        raise ValueError('invalid node permission record')
                    if record['acl'] is not None:
                        base64.b64decode(record['acl'], validate=True)
        except FileNotFoundError:
            self.saved = {}
        except PermissionError:
            if os.geteuid() == 0:
                raise
            self.saved = {}
        except (ValueError, TypeError) as exc:
            raise RuntimeError(f'Cannot read {self.path}; preserve it for permission recovery: {exc}') from exc

    def save(self):
        atomic_json(self.path, self.saved)

    def tracked(self, device):
        entry = self.saved.get(device['id'])
        return bool(entry and entry['identity'] == device['identity'])

    def status(self, device):
        if device['disabled']:
            return '-'
        modes = []
        for name in device['nodes']:
            try:
                info = (DEV_INPUT / name).stat()
                # ACL named users/groups cannot exceed the group mask in st_mode.
                modes.append(info.st_uid == 0 and not (info.st_mode & 0o044))
            except OSError:
                return 'unavailable'
        result = 'root-only' if modes and all(modes) else 'mixed' if any(modes) else 'normal' if modes else 'no nodes'
        return result + (' (saved)' if self.tracked(device) else '')

    def open_node(self, name):
        if not re.fullmatch(r'(event|js|mouse)\d+', name):
            raise RuntimeError('Invalid input node name.')
        fd = os.open(DEV_INPUT / name, os.O_RDONLY | os.O_NONBLOCK | os.O_NOFOLLOW | os.O_CLOEXEC)
        try:
            if not stat.S_ISCHR(os.fstat(fd).st_mode):
                raise RuntimeError('Input node is not a character device.')
            return fd
        except BaseException:
            os.close(fd)
            raise

    def toggle(self, device, confirmed=False):
        if os.geteuid() != 0:
            raise RuntimeError('Run with sudo to change input permissions.')
        if not re.fullmatch(r'\d+-[\d.]+:\d+\.\d+', device['id']):
            raise RuntimeError('Invalid USB interface ID.')
        interface = USB / device['id']
        if identity(interface) != device['identity']:
            raise RuntimeError('Device changed; refresh and select it again.')
        if self.tracked(device):
            self.restore(device['id'])
            return 'Original user/group permissions and ACLs restored.'
        if device['disabled'] or not (interface / 'driver').exists():
            raise RuntimeError('Enable the device before changing input permissions.')
        if needs_confirmation(device) and not confirmed:
            raise RuntimeError('Protected input interface requires confirmation.')
        names = input_files(interface)
        if not names:
            raise RuntimeError('This interface has no input nodes yet.')
        descriptors, records = [], []
        try:
            for name in names:
                sysfs = node_sysfs(interface, name)
                fd = self.open_node(name)
                descriptors.append(fd)
                info = os.fstat(fd)
                if read(sysfs / 'dev') != f'{os.major(info.st_rdev)}:{os.minor(info.st_rdev)}':
                    raise RuntimeError('Input node identity changed; try again.')
                acl = acl_bytes(fd)
                records.append({'name': name, 'fingerprint': fingerprint(info),
                                'sysfs': str(sysfs),
                                'uid': info.st_uid, 'gid': info.st_gid,
                                'mode': stat.S_IMODE(info.st_mode),
                                'acl': base64.b64encode(acl).decode() if acl is not None else None})
            if identity(interface) != device['identity'] or names != input_files(interface):
                raise RuntimeError('Device nodes changed; try again.')
            self.saved[device['id']] = {'identity': device['identity'], 'name': device['name'], 'nodes': records}
            self.save()  # Durable original ACLs before the first mutation.
            try:
                for fd in descriptors:
                    os.fchown(fd, 0, -1)
                    remove_acl(fd)
                    os.fchmod(fd, 0o600)
            except BaseException as exc:
                # A failed rollback keeps the original records for --restore-access.
                rollback_errors = []
                for fd, record in zip(descriptors, records):
                    try:
                        self.restore_fd(fd, record)
                    except OSError as rollback_error:
                        rollback_errors.append(str(rollback_error))
                if rollback_errors:
                    raise RuntimeError(f'{exc}; rollback incomplete. Run --restore-access: '
                                       + '; '.join(rollback_errors)) from exc
                del self.saved[device['id']]
                self.save()
                raise
        finally:
            for fd in descriptors:
                os.close(fd)
        return 'Root-only input access set. Start/restart the game now; existing handles stay open.'

    @staticmethod
    def restore_fd(fd, record):
        os.fchown(fd, record['uid'], record['gid'])
        remove_acl(fd)
        os.fchmod(fd, record['mode'])
        if record['acl'] is not None:
            os.setxattr(fd, 'system.posix_acl_access', base64.b64decode(record['acl'], validate=True))

    def restore(self, key):
        if os.geteuid() != 0:
            raise RuntimeError('Run with sudo to restore input permissions.')
        entry = self.saved[key]
        interface = USB / key
        if not re.fullmatch(r'\d+-[\d.]+:\d+\.\d+', key):
            raise RuntimeError('Invalid saved interface.')
        if not interface.exists() or identity(interface) != entry['identity']:
            del self.saved[key]  # The old nodes disappeared; never change a replacement device.
            self.save()
            return
        current = input_files(interface)
        for record in entry['nodes']:
            if record['name'] not in current:
                continue
            if str(node_sysfs(interface, record['name'])) != record['sysfs']:
                continue
            try:
                fd = self.open_node(record['name'])
            except FileNotFoundError:
                continue
            try:
                if fingerprint(os.fstat(fd)) == record['fingerprint']:
                    self.restore_fd(fd, record)
            finally:
                os.close(fd)
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
        atomic_json(STATE, self.saved)

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
            driver = binding_driver(interface, self.saved.get(device['id']))
            if driver != device['driver']:
                raise RuntimeError('Device driver changed; refresh and select it again.')
            (driver_path(driver) / 'bind').write_text(device['id'])
            self.saved.pop(device['id'], None)
            self.save()
            return
        if needs_confirmation(device) and not confirmed:
            raise RuntimeError('Protected keyboard, pointer, key, or unknown interface requires confirmation.')
        driver = driver_path(device['driver'])
        if (interface / 'driver').resolve() != driver.resolve():
            raise RuntimeError('Device driver changed; refresh and select it again.')
        self.saved[device['id']] = device
        self.save()  # Record recovery information before detaching.
        (driver / 'unbind').write_text(device['id'])

    def restore(self, key):
        device = self.saved[key]
        interface = USB / key
        if not re.fullmatch(r'\d+-[\d.]+:\d+\.\d+', key):
            raise RuntimeError('Invalid saved USB interface ID.')
        if interface.exists() and identity(interface) == device['identity']:
            if not (interface / 'driver').exists():
                (driver_path(binding_driver(interface, device)) / 'bind').write_text(key)
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


def confirm_disable(screen, device, access=False):
    """Only lowercase y confirms; never hide details behind truncation."""
    screen.timeout(-1)
    try:
        height, width = screen.getmaxyx()
        details = ["ARE YOU ABSOLUTELY SURE YOU KNOW WHAT YOU'RE DOING?",
                   'Device: ' + device['name'], 'Types: ' + ', '.join(device['types']),
                   f'USB: {device["identity"][0]}:{device["identity"][1]}   Interface: {device["id"]}',
                   ('Restricts input nodes to root only; user/group access will be removed.' if access else
                    'Disables ALL input functions on this interface, including any keyboard or pointer.'),
                   'You may lose control of this computer. Quitting will NOT re-enable it.',
                   'Use another input device or unplug/reconnect this device to recover.',
                   'Press lowercase y to proceed. ANY other key cancels.']
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



def row_colors():
    colors = {'green': 0, 'red': 0, 'amber': 0}
    if not curses.has_colors():
        return colors
    curses.start_color()
    background = -1
    try:
        curses.use_default_colors()
    except curses.error:
        background = curses.COLOR_BLACK
    amber = 214 if curses.COLORS >= 256 else curses.COLOR_YELLOW
    for pair, (key, foreground) in enumerate(
            [('green', curses.COLOR_GREEN), ('red', curses.COLOR_RED), ('amber', amber)], 1):
        curses.init_pair(pair, foreground, background)
        colors[key] = curses.color_pair(pair)
    return colors


def row_state(device, access_status, shadow):
    if shadow and shadow['state'] == 'active':
        return 'SHADOWED: ' + shadow['label'], 'amber'
    if shadow and shadow['state'] in ('activating', 'deactivating', 'unknown'):
        return 'REMAP ' + shadow['state'].upper(), 'amber'
    if shadow and shadow['state'] == 'failed':
        return 'REMAP FAILED', 'red'
    if device['disabled']:
        return 'DISABLED', 'red'
    if access_status.startswith('root-only'):
        return 'ROOT-ONLY', 'red'
    if access_status.startswith('mixed'):
        return 'MIXED ACCESS', 'amber'
    return 'ENABLED', 'green'


def choose_remapper(screen, device):
    if not remapping_supported(device):
        raise RuntimeError('No replacement profiles are available for this controller.')
    options = profiles_for(device)
    screen.timeout(-1)
    try:
        while True:
            height, width = screen.getmaxyx()
            screen.erase()
            fits = height >= 15 and width >= 65
            if fits:
                lines = ['REPLACEMENT DRIVER', device['name'],
                         'The physical driver stays bound, with input restricted to root.',
                         'The remapper grabs it and supplies a virtual controller.', '',
                         *[f'{index}. {PROFILES[key][0]}' for index, key in enumerate(options, 1)],
                         '', '0. Stop remapping and leave the physical controller disabled',
                         'e. Stop remapping and restore native input + saved permissions',
                         '', 'Choose a number / e. Escape or q cancels.',
                         'The remapper keeps running after you quit this app.']
                for y, text in enumerate(lines):
                    screen.addnstr(y, 0, text, width - 1)
            elif height and width > 1:
                screen.addnstr(0, 0, 'Enlarge terminal (65x15); Esc cancels.', width - 1)
            screen.refresh()
            key = screen.getch()
            if key in (27, ord('q')):
                return None
            if not fits or key == curses.KEY_RESIZE:
                continue
            if key == ord('0'):
                return 'stop-disabled'
            if key == ord('e'):
                return 'stop-native'
            if ord('1') <= key < ord('1') + len(options):
                return options[key - ord('1')]
            return None
    finally:
        screen.timeout(1000)


def ui(screen, controller, args):
    access = AccessController()
    remappers = RemapperController(controller, access, scan)
    colors = row_colors()
    curses.curs_set(0)
    screen.timeout(1000)
    category = FILTERS.index(args.type)
    query, selected, message = args.search, 0, 'Space: driver. p: permissions. r: replacement remapper.'
    while True:
        devices = filtered(scan(controller.saved), FILTERS[category], query)
        shadows = {d['id']: remappers.status(d) for d in devices}
        selected = min(selected, max(0, len(devices) - 1))
        screen.erase()
        height, width = screen.getmaxyx()
        def line(y, text, attr=0):
            if 0 <= y < height and width > 1:
                screen.addnstr(y, 0, ''.join(c if c.isprintable() else '?' for c in text), width - 1, attr)
        line(0, 'INPUT TOGGLE  |  USB input devices', curses.A_BOLD)
        line(1, f'Type: {FILTERS[category]}   Search: {query or "(none)"}   {len(devices)} interfaces')
        line(2, 'Tab: type  /: search  Up/Down  Space: driver  p: access  r: remap  q: quit')
        page = max(1, height - 9)
        start = (selected // page) * page
        for row, device in enumerate(devices[start:start + page], 4):
            status, color = row_state(device, access.status(device), shadows[device['id']])
            attr = colors[color] | (curses.A_REVERSE | curses.A_BOLD if start + row - 4 == selected else 0)
            line(row, f'{status}  {device["name"]}  [{", ".join(device["types"])}]  {device["id"]}', attr)
        if not devices:
            line(4, 'No matching devices. Try another type or clear the search.')
        if devices:
            d = devices[selected]
            nodes = ', '.join(d['nodes']) or 'none'
            line(height - 4, 'Access: ' + access.status(d) + '   Green: enabled / Red: disabled or restricted / Amber: shadowed')
            line(height - 3, f'USB {d["identity"][0]}:{d["identity"][1]}  Interface {d["id"]}  Driver {d["driver"]}  Nodes: {nodes}')
        line(height - 2, message)
        line(height - 1, 'Changes and remappers stay after quitting. r: choose / stop a replacement.')
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
        elif key == ord('r') and devices:
            try:
                device = devices[selected]
                choice = choose_remapper(screen, device)
                if choice is None:
                    message = 'Cancelled; remapper unchanged.'
                    continue
                screen.erase()
                line(0, 'Applying remapper selection; waiting for the controller...')
                screen.refresh()
                if choice.startswith('stop-'):
                    message = remappers.stop(device, enable_native=choice == 'stop-native')
                else:
                    message = remappers.start(device, choice)
            except (OSError, RuntimeError) as exc:
                message = str(exc)
        elif key == ord('p') and devices:
            try:
                device = devices[selected]
                shadow = shadows[device['id']]
                if shadow and shadow['state'] in ('active', 'activating', 'deactivating', 'unknown'):
                    raise RuntimeError('Stop the replacement through r before changing physical permissions.')
                confirmed = False
                if not access.tracked(device) and needs_confirmation(device):
                    confirmed = confirm_disable(screen, device, access=True)
                    if not confirmed:
                        message = 'Cancelled; permissions unchanged.'
                        continue
                message = access.toggle(device, confirmed=confirmed)
            except (OSError, RuntimeError) as exc:
                message = str(exc)
        elif key == ord(' ') and devices:
            try:
                device = devices[selected]
                shadow = shadows[device['id']]
                if shadow and shadow['state'] in ('active', 'activating', 'deactivating', 'unknown'):
                    message = remappers.stop(device)
                    continue
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
    parser.add_argument('--restore-access', action='store_true', help='Restore saved input permissions and ACLs')
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
    access = AccessController()
    remappers = RemapperController(controller, access, scan)
    if args.list:
        for d in filtered(scan(controller.saved), args.type, args.search):
            print(f'{d["id"]:16} {"disabled" if d["disabled"] else "enabled":8} {d["name"]} '
                  f'[{", ".join(d["types"])}] driver={d["driver"]} access={access.status(d)} '
                  f'nodes={",".join(d["nodes"]) or "-"} '
                  f'status={row_state(d, access.status(d), remappers.status(d))[0]}')
        return 0
    if (args.restore or args.restore_access) and os.geteuid() != 0:
        parser.exit(1, 'Use sudo for restoration.\n')
    def stop(signum, frame):
        raise KeyboardInterrupt
    for sig in (signal.SIGTERM, signal.SIGHUP):
        signal.signal(sig, stop)
    errors = []
    try:
        if args.restore or args.restore_access:
            for device in scan(controller.saved):
                shadow = remappers.status(device)
                if shadow and shadow['state'] in ('active', 'activating', 'deactivating', 'unknown'):
                    parser.exit(1, 'Stop active replacements through the r menu before bulk restoration.\n')
            errors = controller.restore_all() if args.restore else []
            if args.restore_access:
                errors.extend(access.restore_all())
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
