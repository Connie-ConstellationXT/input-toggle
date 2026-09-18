import importlib.util
from pathlib import Path
import tempfile
import struct
import unittest
from unittest.mock import patch, Mock

spec = importlib.util.spec_from_file_location('input_toggle', Path(__file__).resolve().parents[1] / 'input-toggle.py')
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)


class DeviceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        root = Path(self.temp.name)
        self.usb = root / 'devices'
        self.driver = root / 'drivers/usbhid'
        self.driver.mkdir(parents=True)
        parent = self.usb / '1-2'
        self.interface = parent / '1-2:1.0'
        self.interface.mkdir(parents=True)
        (self.usb / '1-2:1.0').symlink_to(self.interface)
        for key, value in {'idVendor': '044f', 'idProduct': 'b679', 'devnum': '3', 'busnum': '1', 'product': 'Thrustmaster T-Rudder'}.items():
            (parent / key).write_text(value)
        (self.interface / 'driver').symlink_to(self.driver)
        (self.interface / 'bInterfaceClass').write_text('03')
        for key, value in {'USB': self.usb, 'DRIVER': self.driver, 'STATE': root / 'state.json'}.items():
            p = patch.object(m, key, value)
            p.start()
            self.addCleanup(p.stop)
        p = patch.object(m.os, 'geteuid', return_value=0)
        p.start()
        self.addCleanup(p.stop)
        self.controller = m.Controller()

    def test_discover_and_filter(self):
        devices = m.scan({})
        self.assertEqual(len(m.filtered(devices, 'Joystick / game controller', 't-RUDDER')), 1)
        self.assertEqual(m.filtered(devices, 'Keyboard', ''), [])

    def test_disable_retains_metadata_and_restore(self):
        device = m.scan({})[0]
        self.controller.toggle(device)
        self.assertEqual((self.driver / 'unbind').read_text(), device['id'])
        (self.interface / 'driver').unlink()
        recovered = m.Controller()
        disabled = m.scan(recovered.saved)[0]
        self.assertTrue(disabled['disabled'])
        self.assertIn('Joystick / game controller', disabled['types'])
        recovered.toggle(disabled)
        self.assertEqual((self.driver / 'bind').read_text(), device['id'])
        self.assertEqual(recovered.saved, {})

    def test_keyboard_protected(self):
        device = m.scan({})[0]
        device['types'].append('Keyboard')
        with self.assertRaisesRegex(RuntimeError, 'Protected'):
            self.controller.toggle(device)
        self.assertFalse((self.driver / 'unbind').exists())

    def test_stateless_unbound_discovery_and_enable(self):
        (self.interface / 'driver').unlink()
        for cache in ('', 'broken json', '[]', '{"bad": {}}'):
            m.STATE.write_text(cache)
            controller = m.Controller()
            device = m.scan(controller.saved)[0]
            self.assertTrue(device['disabled'])
            self.assertEqual(device['name'], 'Thrustmaster T-Rudder')
            self.assertIn('Joystick / game controller', device['types'])
            controller.toggle(device)
            self.assertEqual((self.driver / 'bind').read_text(), '1-2:1.0')

    def test_unbound_non_hid_and_other_driver_excluded(self):
        (self.interface / 'driver').unlink()
        (self.interface / 'bInterfaceClass').write_text('08')
        self.assertEqual(m.scan(), [])
        (self.interface / 'bInterfaceClass').write_text('03')
        other = self.driver.parent / 'other'
        other.mkdir()
        (self.interface / 'driver').symlink_to(other)
        self.assertEqual(m.scan(), [])

    def test_boot_keyboard_classification_without_cache(self):
        (self.interface / 'driver').unlink()
        (self.interface / 'bInterfaceSubClass').write_text('01')
        (self.interface / 'bInterfaceProtocol').write_text('01')
        self.assertIn('Keyboard', m.scan()[0]['types'])

    def test_confirmed_keyboard_disable(self):
        device = m.scan()[0]
        device['types'] = ['Keyboard', 'Mouse']
        self.controller.toggle(device, confirmed=True)
        self.assertEqual((self.driver / 'unbind').read_text(), device['id'])

    def test_confirmation_only_lowercase_y_and_shows_device(self):
        device = m.scan()[0]
        for key in ['y', 'Y', 'n', ' ', '\n', '\r', '\x1b', '\t', '\x7f', m.curses.KEY_UP, m.curses.KEY_BACKSPACE]:
            screen = Mock()
            screen.getmaxyx.return_value = (40, 100)
            screen.get_wch.return_value = key
            self.assertEqual(m.confirm_disable(screen, device), key == 'y')
            screen.get_wch.assert_called_once_with()
            rendered = ' '.join(call.args[2] for call in screen.addnstr.call_args_list)
            self.assertIn('Thrustmaster T-Rudder', rendered)
            self.assertIn('1-2:1.0', rendered)
            self.assertIn('044f:b679', rendered)

    def test_small_terminal_cannot_confirm(self):
        screen = Mock()
        screen.getmaxyx.return_value = (4, 20)
        screen.get_wch.return_value = 'y'
        self.assertFalse(m.confirm_disable(screen, m.scan()[0]))

    def test_exit_keeps_disabled_device_for_next_launch(self):
        def disable_and_quit(*args):
            self.controller.toggle(m.scan({})[0])
            (self.interface / 'driver').unlink()
        with patch.object(m.sys, 'argv', ['input-toggle.py']), \
                patch.object(m.curses, 'wrapper', side_effect=disable_and_quit), \
                patch.object(m.signal, 'signal'):
            self.assertEqual(m.main(), 0)
        reopened = m.Controller()
        self.assertTrue(m.scan(reopened.saved)[0]['disabled'])
        self.assertFalse((self.driver / 'bind').exists())
        reopened.toggle(m.scan(reopened.saved)[0])
        self.assertEqual((self.driver / 'bind').read_text(), '1-2:1.0')

    def test_ctrl_c_does_not_restore(self):
        self.controller.toggle(m.scan({})[0])
        (self.interface / 'driver').unlink()
        with patch.object(m.sys, 'argv', ['input-toggle.py']), \
                patch.object(m.curses, 'wrapper', side_effect=KeyboardInterrupt), \
                patch.object(m.signal, 'signal'):
            self.assertEqual(m.main(), 0)
        self.assertIn('1-2:1.0', m.Controller().saved)
        self.assertFalse((self.driver / 'bind').exists())

    def test_explicit_restore_command(self):
        self.controller.toggle(m.scan({})[0])
        (self.interface / 'driver').unlink()
        with patch.object(m.sys, 'argv', ['input-toggle.py', '--restore']), \
                patch.object(m.signal, 'signal'):
            self.assertEqual(m.main(), 0)
        self.assertEqual(m.Controller().saved, {})
        self.assertEqual((self.driver / 'bind').read_text(), '1-2:1.0')

    def test_replaced_device_not_rebound(self):
        self.controller.toggle(m.scan({})[0])
        (self.interface / 'driver').unlink()
        (self.interface.parent / 'devnum').write_text('4')
        self.assertEqual(self.controller.restore_all(), [])
        self.assertFalse((self.driver / 'bind').exists())

    def test_failed_restore_keeps_recovery_record(self):
        self.controller.toggle(m.scan({})[0])
        (self.interface / 'driver').unlink()
        (self.driver / 'bind').mkdir()
        self.assertEqual(len(self.controller.restore_all()), 1)
        self.assertIn('1-2:1.0', m.Controller().saved)


    def setup_access(self):
        dev = Path(self.temp.name) / 'dev-input'
        dev.mkdir()
        self.dev = dev
        for name in ('event7', 'js1'):
            node = self.interface / 'input/input50' / name
            node.mkdir(parents=True)
            (node / 'dev').write_text('0:0')  # Regular files stand in for character devices.
            (dev / name).touch()
            (dev / name).chmod(0o660)
        for obj, key, value in [(m, 'DEV_INPUT', dev), (m.stat, 'S_ISCHR', lambda mode: True)]:
            patcher = patch.object(obj, key, value)
            patcher.start()
            self.addCleanup(patcher.stop)
        patcher = patch.object(m.os, 'fchown')  # Tests never change real ownership.
        self.chown = patcher.start()
        self.addCleanup(patcher.stop)
        self.access = m.AccessController()
        return m.scan()[0]

    def test_f710_xpad_discovery_disable_and_stateless_rebind(self):
        parent = self.interface.parent
        for key, value in {'idVendor': '046d', 'idProduct': 'c21f', 'product': 'Logitech Gamepad F710'}.items():
            (parent / key).write_text(value)
        (self.interface / 'bInterfaceClass').write_text('ff')
        (self.interface / 'bInterfaceNumber').write_text('00')
        (self.interface / 'driver').unlink()
        xpad = self.driver.parent / 'xpad'
        xpad.mkdir()
        (self.interface / 'driver').symlink_to(xpad)
        node = self.interface / 'input/input25/event25'
        node.mkdir(parents=True)
        (node.parent / 'name').write_text('Logitech Gamepad F710')
        device = m.scan()[0]
        self.assertEqual(device['nodes'], ['event25'])
        self.assertEqual(device['driver'], 'xpad')
        self.assertIn('Joystick / game controller', device['types'])
        self.controller.toggle(device)
        self.assertEqual((xpad / 'unbind').read_text(), device['id'])
        (self.interface / 'driver').unlink()
        m.STATE.unlink()
        device = m.scan()[0]
        self.assertTrue(device['disabled'])
        m.Controller().toggle(device)
        self.assertEqual((xpad / 'bind').read_text(), device['id'])
        self.assertFalse((self.driver / 'bind').exists())

    def test_permission_roundtrip_preserves_real_posix_acl(self):
        device = self.setup_access()
        entries = [(1, 6, 0xffffffff), (2, 6, m.os.getuid()), (4, 4, 0xffffffff),
                   (16, 6, 0xffffffff), (32, 0, 0xffffffff)]
        acl = struct.pack('<I', 2) + b''.join(struct.pack('<HHI', *entry) for entry in entries)
        path = self.dev / 'event7'
        m.os.setxattr(path, 'system.posix_acl_access', acl)
        self.access.toggle(device)
        for name in device['nodes']:
            self.assertEqual(m.stat.S_IMODE((self.dev / name).stat().st_mode), 0o600)
        fd = m.os.open(path, m.os.O_RDONLY)
        try:
            self.assertIsNone(m.acl_bytes(fd))
        finally:
            m.os.close(fd)
        self.assertTrue(any(call.args[1:] == (0, -1) for call in self.chown.call_args_list))
        reopened = m.AccessController()
        self.assertTrue(reopened.tracked(device))
        reopened.toggle(device)
        self.assertEqual(m.os.getxattr(path, 'system.posix_acl_access'), acl)
        self.assertEqual(m.stat.S_IMODE(path.stat().st_mode), 0o660)
        self.assertEqual(m.stat.S_IMODE((self.dev / 'js1').stat().st_mode), 0o660)
        self.assertEqual(m.AccessController().saved, {})

    def test_permission_failure_rolls_back_all_nodes(self):
        device = self.setup_access()
        original = m.os.fchmod
        def fail_second(fd, mode):
            if mode == 0o600 and m.os.fstat(fd).st_ino == (self.dev / 'js1').stat().st_ino:
                raise OSError('simulated failure')
            return original(fd, mode)
        with patch.object(m.os, 'fchmod', side_effect=fail_second):
            with self.assertRaisesRegex(OSError, 'simulated failure'):
                self.access.toggle(device)
        self.assertEqual(m.AccessController().saved, {})
        for name in device['nodes']:
            self.assertEqual(m.stat.S_IMODE((self.dev / name).stat().st_mode), 0o660)

    def test_restore_failure_keeps_permission_snapshot(self):
        device = self.setup_access()
        self.access.toggle(device)
        with patch.object(self.access, 'restore_fd', side_effect=OSError('failed')):
            self.assertEqual(len(self.access.restore_all()), 1)
        self.assertTrue(m.AccessController().tracked(device))

    def test_permissions_never_restore_onto_reused_node(self):
        device = self.setup_access()
        self.access.toggle(device)
        (self.dev / 'event7').rename(self.dev / 'old-event7')
        (self.dev / 'event7').touch(mode=0o640)
        self.access.toggle(device)
        self.assertEqual(m.stat.S_IMODE((self.dev / 'event7').stat().st_mode), 0o640)

    def test_permissions_reject_symlink_without_mutation(self):
        device = self.setup_access()
        (self.dev / 'js1').unlink()
        (self.dev / 'js1').symlink_to(self.dev / 'event7')
        with self.assertRaises(OSError):
            self.access.toggle(device)
        self.assertFalse(self.access.path.exists())
        self.assertEqual(m.stat.S_IMODE((self.dev / 'event7').stat().st_mode), 0o660)

    def test_permissions_keyboard_requires_confirmation(self):
        device = self.setup_access()
        device['types'] = ['Keyboard']
        with self.assertRaisesRegex(RuntimeError, 'confirmation'):
            self.access.toggle(device)
        self.access.toggle(device, confirmed=True)
        self.assertTrue(self.access.tracked(device))
        self.access.toggle(device)  # Restoration never needs confirmation.
        self.assertFalse(self.access.tracked(device))

    def test_permission_state_corruption_not_overwritten(self):
        self.setup_access()
        self.access.path.write_text('broken json')
        with self.assertRaisesRegex(RuntimeError, 'preserve it'):
            m.AccessController()
        self.assertEqual(self.access.path.read_text(), 'broken json')

    def test_explicit_restore_access_command(self):
        device = self.setup_access()
        self.access.toggle(device)
        with patch.object(m.sys, 'argv', ['input-toggle.py', '--restore-access']), \
                patch.object(m.signal, 'signal'):
            self.assertEqual(m.main(), 0)
        self.assertEqual(m.AccessController().saved, {})
        self.assertEqual(m.stat.S_IMODE((self.dev / 'js1').stat().st_mode), 0o660)


if __name__ == '__main__':
    unittest.main()
