"""Manage controller remappers as transient system services that outlive the TUI."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parent
RUNNER = ROOT / 'remappers' / 'runner.py'
PROFILES = {
    'swapsticks': ('SwapSticks', 'gamepad_daemon_swapsticks.py', ('046d', 'c21f'), 'DEVICE_PATH'),
    'merged-triggers': ('Merged triggers', 'gamepad_daemon.py', ('046d', 'c21f'), 'DEVICE_PATH'),
    'swapsticks-triggers': ('SwapSticks + merged triggers', 'gamepad_daemon_swapsticks_and_triggerz.py', ('046d', 'c21f'), 'DEVICE_PATH'),
    'yareli-throttle': ('Yareli continuous throttle', 'Yareli_continuous_throttle.py', ('044f', 'b679'), 'TRUDDER_PATH'),
}


def profiles_for(device):
    identity = tuple(device['identity'][:2])
    return [key for key, profile in PROFILES.items() if profile[2] == identity]


def supported(device):
    return bool(profiles_for(device))


def service_name(device):
    connection = json.dumps([device['id'], device['identity']], sort_keys=True)
    digest = hashlib.sha256(connection.encode()).hexdigest()[:16]
    return 'input-toggle-remap-' + digest + '.service'


def command(args, timeout=20):
    try:
        result = subprocess.run(args, capture_output=True, text=True, timeout=timeout)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise RuntimeError(str(exc)) from exc
    if result.returncode:
        raise RuntimeError((result.stderr or result.stdout).strip() or f'{args[0]} failed')
    return result.stdout


class RemapperController:
    def __init__(self, controller, access, scan):
        self.controller, self.access, self.scan = controller, access, scan

    def current(self, device):
        for live in self.scan(self.controller.saved):
            if live['id'] == device['id'] and live['identity'] == device['identity']:
                return live
        raise RuntimeError('Controller disconnected or changed. Refresh and select it again.')

    def status(self, device):
        if not supported(device):
            return None
        if not shutil.which('systemctl'):
            return None
        try:
            result = subprocess.run(
                ['systemctl', 'show', service_name(device), '--property=ActiveState',
                 '--property=Description', '--property=LoadState'],
                capture_output=True, text=True, timeout=2)
        except (OSError, subprocess.TimeoutExpired):
            # No usable system manager means this app could not have started a
            # managed replacement in the current environment.
            return None
        properties = dict(line.split('=', 1) for line in result.stdout.splitlines() if '=' in line)
        if properties.get('LoadState') == 'not-found':
            return None
        if result.returncode:
            return None
        description = properties.get('Description', '')
        if not description.startswith('Input Toggle remapper: '):
            return None
        profile = description.removeprefix('Input Toggle remapper: ')
        label = PROFILES.get(profile, (profile,))[0]
        state = properties.get('ActiveState', 'unknown')
        return {'state': state, 'profile': profile, 'label': label}

    @staticmethod
    def require_root():
        if os.geteuid() != 0:
            raise RuntimeError('Run with sudo to manage remappers.')

    def stop_service(self, device):
        self.require_root()
        status = self.status(device)
        if status and status['state'] == 'unknown':
            raise RuntimeError('Cannot determine remapper state; check systemctl first.')
        if status:
            command(['systemctl', 'stop', service_name(device)], timeout=8)

    def start(self, device, profile):
        self.require_root()
        if profile not in profiles_for(device):
            raise RuntimeError('That replacement is not compatible with this controller.')
        if not shutil.which('systemd-run') or not shutil.which('systemctl'):
            raise RuntimeError('Remapping requires systemd-run and systemctl.')
        # Check imports and uinput before stopping an existing working remapper.
        command([sys.executable, str(RUNNER), '--check'], timeout=10)
        device = self.current(device)
        self.stop_service(device)
        was_disabled = device['disabled']
        had_access_snapshot = self.access.tracked(device)
        restricted_here = False
        try:
            if was_disabled:
                if had_access_snapshot:
                    self.access.restore(device['id'])  # The unbound interface has no old nodes left.
                    had_access_snapshot = False
                self.controller.toggle(device)
            deadline = time.monotonic() + 4
            while True:
                live = self.current(device)
                events = [name for name in live['nodes'] if name.startswith('event')]
                if events:
                    break
                if time.monotonic() >= deadline:
                    raise RuntimeError('No controller event node appeared after enabling the driver.')
                time.sleep(0.1)
            if len(events) != 1:
                raise RuntimeError('Expected one controller event node; refusing to select an ambiguous source.')
            # Let udev finish its initial ownership/ACL setup before taking the snapshot.
            if shutil.which('udevadm'):
                command(['udevadm', 'settle', '--timeout=3'], timeout=4)
            live = self.current(device)
            if not self.access.tracked(live):
                self.access.toggle(live)
                restricted_here = True
            if not self.access.status(live).startswith('root-only'):
                raise RuntimeError('Physical input is not root-only. Restore/reapply permissions with p first.')
            uid = int(os.environ.get('SUDO_UID', str(os.getuid())))
            gid = int(os.environ.get('SUDO_GID', str(os.getgid())))
            unit = service_name(device)
            # A failed transient unit may remain loaded until explicitly reset.
            try:
                subprocess.run(['systemctl', 'reset-failed', unit], capture_output=True, timeout=3)
            except subprocess.TimeoutExpired as exc:
                raise RuntimeError('systemctl reset-failed timed out') from exc
            command(['systemd-run', '--quiet', '--collect', '--unit=' + unit,
                     '--description=Input Toggle remapper: ' + profile,
                     '--property=Type=notify', '--property=NotifyAccess=main',
                     '--property=TimeoutStartSec=12s', '--property=TimeoutStopSec=3s',
                     '--property=Restart=no', '--property=KillMode=control-group',
                     '--setenv=PATH=' + os.environ.get('PATH', '/run/current-system/sw/bin'),
                     '--setenv=PYTHONPATH=' + os.environ.get('PYTHONPATH', ''),
                     sys.executable, str(RUNNER), '--profile', profile,
                     '--interface', device['id'], '--identity', json.dumps(device['identity']),
                     '--event', events[0], '--uid', str(uid), '--gid', str(gid)], timeout=18)
            status = self.status(device)
            if not status or status['state'] != 'active':
                raise RuntimeError('Remapper did not stay active. Inspect journalctl -u ' + unit)
            return 'Shadowed with ' + PROFILES[profile][0] + '. You can quit; the remapper keeps running.'
        except BaseException as exc:
            # Stop any partially started process before putting the physical device back.
            errors = []
            try:
                self.stop_service(device)
            except (RuntimeError, OSError) as failure:
                errors.append(str(failure))
            if not errors:
                try:
                    live = self.current(device)
                    if was_disabled and not live['disabled']:
                        self.controller.toggle(live)
                    if restricted_here and not had_access_snapshot:
                        self.access.restore(device['id'])
                except (RuntimeError, OSError) as failure:
                    errors.append(str(failure))
            if errors:
                raise RuntimeError(f'{exc}; recovery needs attention: ' + '; '.join(errors)) from exc
            raise

    def stop(self, device, enable_native=False):
        self.stop_service(device)
        live = self.current(device)
        if enable_native:
            if live['disabled']:
                self.controller.toggle(live)
            if self.access.tracked(live):
                self.access.restore(live['id'])
            return 'Remapper stopped; native driver and saved permissions restored.'
        if not live['disabled']:
            self.controller.toggle(live)
        if self.access.tracked(live):
            self.access.restore(live['id'])  # Drop snapshots of nodes removed by unbinding.
        return 'Remapper stopped; physical controller disabled.'
