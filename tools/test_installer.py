"""Install, diagnose and uninstall with separate test identity and shortcuts."""
import argparse
import ctypes
import json
import os
from pathlib import Path
import subprocess
import tempfile
import time
import winreg


def installed_record_exists():
    path = r'Software\Microsoft\Windows\CurrentVersion\Uninstall\DayNest.PackagingTest_is1'
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, path, 0, winreg.KEY_READ | winreg.KEY_WOW64_64KEY):
            return True
    except FileNotFoundError:
        return False


def startup_value():
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r'Software\Microsoft\Windows\CurrentVersion\Run') as key:
            return winreg.QueryValueEx(key, 'DayNest')
    except FileNotFoundError:
        return None


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('installer', type=Path)
    args = parser.parse_args()
    if installed_record_exists():
        raise SystemExit('A packaging test is already installed; refusing to overwrite it.')
    root = Path(__file__).resolve().parents[1]
    build = root / 'build'
    build.mkdir(exist_ok=True)
    startup_before = startup_value()
    programs_buffer = ctypes.create_unicode_buffer(32768)
    if ctypes.windll.shell32.SHGetFolderPathW(None, 2, None, 0, programs_buffer) != 0:
        raise RuntimeError('Unable to locate the current-user Start menu')
    shortcuts = [Path(programs_buffer.value) / (name + '.lnk') for name in
                 ('DayNest Packaging Test', 'DayNest Packaging Test - 恢复普通窗口')]
    if any(path.exists() for path in shortcuts):
        raise SystemExit('Test shortcut paths are already occupied.')
    with tempfile.TemporaryDirectory(prefix='installer-test-', dir=build) as temporary:
        temporary = Path(temporary)
        target = temporary / 'DayNest'
        report = temporary / 'runtime.json'
        appdata = temporary / 'userdata'
        sentinel = appdata / 'DayNest' / 'keep.txt'
        sentinel.parent.mkdir(parents=True)
        sentinel.write_text('Keep user settings when uninstalling.', encoding='utf-8')
        env = dict(os.environ, APPDATA=str(appdata))
        uninstaller = target / 'unins000.exe'
        try:
            subprocess.run([str(args.installer.resolve()), '/VERYSILENT', '/SUPPRESSMSGBOXES', '/NORESTART',
                            '/SP-', '/TESTINSTALL=1', f'/DIR={target}', f'/LOG={temporary / "install.log"}'],
                           env=env, check=True, timeout=90)
            assert installed_record_exists()
            assert all(path.is_file() for path in shortcuts)
            exe = target / 'DayNest.exe'
            assert exe.is_file() and (target / '_internal' / 'python311.dll').is_file()
            subprocess.run([str(exe), '--self-test', str(report)], env=env, check=True, timeout=30)
            checked = json.loads(report.read_text(encoding='utf-8'))
            assert checked['ok'] and checked['frozen']
            assert checked['launch_command'] == [str(exe)]
            assert checked['restore_command'] == [str(exe), '--restore-window']
        finally:
            if uninstaller.is_file():
                subprocess.run([str(uninstaller), '/VERYSILENT', '/SUPPRESSMSGBOXES', '/NORESTART', '/TESTINSTALL=1'],
                               env=env, check=True, timeout=90)
        deadline = time.monotonic() + 20
        while (installed_record_exists() or (target / 'DayNest.exe').exists()) and time.monotonic() < deadline:
            time.sleep(0.1)
        assert not installed_record_exists()
        assert not any(path.exists() for path in shortcuts)
        assert startup_value() == startup_before
        assert not (target / 'DayNest.exe').exists()
        assert sentinel.read_text(encoding='utf-8') == 'Keep user settings when uninstalling.'
    result = {'install': True, 'frozen_runtime': True, 'uninstall': True, 'user_data_preserved': True,
              'shortcuts': True, 'existing_startup_preserved': True}
    (build / 'installer-check.json').write_text(json.dumps(result, indent=2), encoding='utf-8')
    print('Installer, frozen runtime, uninstall and data preservation checks passed.')
