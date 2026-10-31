"""Build the Windows x64 onedir, portable ZIP and Inno Setup installer."""
import argparse
import ast
import hashlib
import importlib.metadata
import json
from pathlib import Path
import shutil
import struct
import subprocess
import sys
import zipfile


ROOT = Path(__file__).resolve().parents[1]


def app_version():
    for node in ast.parse((ROOT / 'daynest.py').read_text(encoding='utf-8')).body:
        if isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id == 'APP_VERSION' for t in node.targets):
            return ast.literal_eval(node.value)
    raise RuntimeError('APP_VERSION is missing')


def run(*command):
    subprocess.run([str(part) for part in command], cwd=ROOT, check=True)


def copy_licenses(bundle):
    shutil.copy2(ROOT / 'LICENSE', bundle / 'LICENSE')
    destination = bundle / 'licenses'
    destination.mkdir(exist_ok=True)
    python_license = Path(sys.base_prefix) / 'LICENSE.txt'
    if not python_license.is_file():
        raise RuntimeError('Python runtime license was not found')
    shutil.copy2(python_license, destination / 'Python-LICENSE.txt')
    for package in ('python-dateutil', 'six', 'pyinstaller'):
        distribution = importlib.metadata.distribution(package)
        candidates = [path for path in distribution.files or []
                      if '.dist-info' in str(path) and path.name.upper().startswith(('LICENSE', 'COPYING'))]
        if not candidates:
            raise RuntimeError(f'{package} license was not found')
        for index, relative in enumerate(candidates):
            shutil.copy2(distribution.locate_file(relative), destination / f'{package}-LICENSE-{index}.txt')
    tcl = Path(sys.base_prefix) / 'tcl'
    for name in ('tcl8.6', 'tk8.6'):
        license_file = tcl / name / 'license.terms'
        if not license_file.is_file():
            license_file = ROOT / 'packaging' / 'licenses' / f'{name}-license.terms'
        if not license_file.is_file():
            raise RuntimeError(f'{name} license was not found')
        shutil.copy2(license_file, destination / f'{name}-license.terms')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--iscc', required=True, type=Path, help='Path to Inno Setup ISCC.exe')
    parser.add_argument('--skip-tests', action='store_true')
    args = parser.parse_args()
    if sys.platform != 'win32' or struct.calcsize('P') != 8:
        parser.error('Build with 64-bit Python on Windows')
    if not args.iscc.is_file():
        parser.error('ISCC.exe was not found')
    version = app_version()
    if not args.skip_tests:
        run(sys.executable, '-B', ROOT / 'tests' / 'run_checks.py')
    build = ROOT / 'build'
    build.mkdir(exist_ok=True)
    if not (ROOT / 'assets' / 'DayNest.ico').is_file():
        run(sys.executable, ROOT / 'tools' / 'generate_icon.py')
    numeric = tuple(int(part) for part in version.split('.')) + (0,)
    strings = {'CompanyName': 'DayNest contributors', 'FileDescription': 'DayNest Desktop Calendar',
               'FileVersion': version, 'InternalName': 'DayNest', 'OriginalFilename': 'DayNest.exe',
               'ProductName': 'DayNest', 'ProductVersion': version}
    version_data = ('VSVersionInfo(ffi=FixedFileInfo(filevers=' + repr(numeric) + ', prodvers=' + repr(numeric) +
                    ', mask=0x3f, flags=0, OS=0x40004, fileType=1, subtype=0, date=(0,0)), '
                    'kids=[StringFileInfo([StringTable("040904B0", [' +
                    ','.join(f'StringStruct({key!r}, {value!r})' for key, value in strings.items()) +
                    '])]), VarFileInfo([VarStruct("Translation", [1033, 1200])])])')
    (build / 'version_info.txt').write_text(version_data, encoding='utf-8')
    run(sys.executable, '-m', 'PyInstaller', '--noconfirm', '--clean', '--log-level', 'WARN', '--distpath', ROOT / 'dist',
        '--workpath', build / 'pyinstaller', ROOT / 'packaging' / 'DayNest.spec')
    bundle = ROOT / 'dist' / 'DayNest'
    copy_licenses(bundle)
    shutil.copy2(ROOT / 'README.md', bundle / 'README.md')
    report = build / 'frozen-check.json'
    report.unlink(missing_ok=True)
    run(bundle / 'DayNest.exe', '--self-test', report)
    checked = json.loads(report.read_text(encoding='utf-8'))
    if not checked.get('ok') or not checked.get('frozen'):
        raise RuntimeError(f'Frozen runtime check failed: {checked}')
    run(args.iscc.resolve(), '/Q', f'/DAppVersion={version}', ROOT / 'packaging' / 'DayNest.iss')
    release = ROOT / 'release'
    portable = release / f'DayNest-{version}-Portable-win-x64.zip'
    with zipfile.ZipFile(portable, 'w', compression=zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
        for path in sorted(bundle.rglob('*')):
            if path.is_file():
                archive.write(path, path.relative_to(bundle.parent))
    artifacts = [release / f'DayNest-{version}-Setup-win-x64.exe', portable]
    (release / 'SHA256SUMS.txt').write_text('\n'.join(
        f'{hashlib.sha256(path.read_bytes()).hexdigest()}  {path.name}' for path in artifacts) + '\n', encoding='ascii')
    print('Release artifacts:')
    for path in artifacts:
        print(f'  {path.name}: {path.stat().st_size / 1024 / 1024:.1f} MiB')


if __name__ == '__main__':
    main()
