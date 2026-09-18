import importlib.util
from pathlib import Path
import tempfile
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


if __name__ == '__main__':
    unittest.main()
