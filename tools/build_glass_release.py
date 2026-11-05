"""Build a self-contained Windows 11 x64 WinUI portable release (no personal data)."""
import argparse
import hashlib
import importlib.metadata
import json
from pathlib import Path
import shutil
import subprocess
import sys
import zipfile

ROOT = Path(__file__).resolve().parents[1]


def run(*args):
    subprocess.run(list(map(str, args)), cwd=ROOT, check=True)


def build(version, crt, crt_licenses, replace=False):
    if sys.platform != 'win32': raise RuntimeError('Build on Windows x64')
    # Unique staging avoids deleting existing builds or release artifacts.
    import uuid
    stage = ROOT / 'dist' / ('glass-' + uuid.uuid4().hex)
    stage.mkdir(parents=True)
    bundle = stage / 'DayNest'
    run('dotnet', 'publish', ROOT / 'prototypes/DayNest.Glass/DayNest.Glass.csproj', '-c', 'Release',
        '-r', 'win-x64', '--self-contained', 'true', '-p:Platform=x64', '-p:PublishSingleFile=false',
        '-p:PublishTrimmed=false', '-p:DebugType=None', '-p:DebugSymbols=false', '-p:Version=' + version, '-o', bundle, '--nologo')
    run(sys.executable, '-m', 'PyInstaller', '--noconfirm', '--clean', '--log-level', 'WARN',
        '--name', 'DayNest.Bridge', '--console', '--onedir', '--paths', ROOT,
        '--hidden-import', 'dateutil.zoneinfo', '--distpath', stage / 'python',
        '--workpath', stage / 'work', '--specpath', stage,
        ROOT / 'prototypes/DayNest.Glass/calendar_bridge.py')
    shutil.copytree(stage / 'python/DayNest.Bridge', bundle / 'backend')
    licenses = bundle / 'licenses'; licenses.mkdir()
    if not all((crt / name).is_file() for name in ('msvcp140.dll', 'vcruntime140.dll')):
        raise RuntimeError('Supply the x64 Microsoft.VC*.CRT redistributable directory from Visual Studio')
    for path in crt.glob('*.dll'): shutil.copy2(path, bundle / path.name)
    for name in ('Redist.txt', 'ThirdPartyNotices.txt'):
        shutil.copy2(crt_licenses / name, licenses / ('VisualCpp-' + name))
    shutil.copy2(ROOT / 'LICENSE', bundle / 'LICENSE')
    shutil.copy2(Path(sys.base_prefix) / 'LICENSE.txt', licenses / 'Python-LICENSE.txt')
    for package in ('python-dateutil', 'six', 'pyinstaller'):
        distribution = importlib.metadata.distribution(package)
        found = [p for p in distribution.files or [] if '.dist-info' in str(p) and p.name.upper().startswith(('LICENSE', 'COPYING'))]
        if not found: raise RuntimeError('Missing license: ' + package)
        for i, path in enumerate(found): shutil.copy2(distribution.locate_file(path), licenses / f'{package}-{i}.txt')
    for name in ('tcl8.6', 'tk8.6'):
        source = Path(sys.base_prefix) / 'tcl' / name / 'license.terms'
        if not source.exists(): source = ROOT / 'packaging/licenses' / (name + '-license.terms')
        if not source.exists(): raise RuntimeError('Missing license: ' + name)
        shutil.copy2(source, licenses / (name + '-license.terms'))
    assets = json.loads((ROOT / 'prototypes/DayNest.Glass/obj/project.assets.json').read_text(encoding='utf-8'))
    for library in assets['libraries']:
        for folder in assets['packageFolders']:
            package = Path(folder) / library.lower()
            for path in package.glob('*'):
                if path.is_file() and path.name.lower().startswith(('license', 'notice', 'thirdpartynotice')):
                    shutil.copy2(path, licenses / (library.replace('/', '-') + '-' + path.name))
    (bundle / 'README.txt').write_text(
        f'DayNest {version} — WinUI 玻璃日历\n\n'
        '要求：Windows 11 x64（build 22000 或更新）。无需单独安装 Python、.NET 或 Windows App SDK。\n'
        '完整解压后双击 DayNest.Glass.exe，不要只移动单个 EXE。\n'
        '桌面模式按 Win+D 查看；按住顶部三横线拖动。关闭主窗口即退出。\n'
        '恢复普通窗口：运行 DayNest.Glass.exe --normal-window。\n'
        '首次使用在设置中填写日历账户；iCloud 使用 App 专用密码。\n'
        '账户和日程保存在 %APPDATA%\\DayNest；外观和位置在 %LOCALAPPDATA%\\DayNest。\n'
        '与原版共享账户/缓存，请先退出原版；不支持同时进行写入。\n'
        '支持单次非全天日程新增/编辑，删除含确认；重复日程请在日历服务中修改。\n'
        '此版本未进行代码签名。\n'
        '许可证：GPL-3.0-only；依赖许可见 licenses。\n'
        '完整源代码及构建脚本：https://github.com/LeoStr4nge/DayNest\n', encoding='utf-8-sig')
    manifest = dict(version=version, commit=subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip(),
                    python=sys.version.split()[0], dependencies={p: importlib.metadata.version(p) for p in ('python-dateutil', 'six', 'pyinstaller')})
    (bundle / 'BUILD.json').write_text(json.dumps(manifest, indent=2), encoding='utf-8')
    release = ROOT / 'release'; release.mkdir(exist_ok=True)
    portable = release / f'DayNest-{version}-WinUI-Portable-win-x64.zip'
    if portable.exists() and not replace: raise RuntimeError('Artifact exists; review it first or explicitly use --replace')
    temporary = release / (portable.name + '.' + uuid.uuid4().hex + '.tmp')
    assert temporary.resolve().parent == release.resolve() == portable.resolve().parent
    with zipfile.ZipFile(temporary, 'w', zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
        for path in sorted(bundle.rglob('*')):
            if path.is_file(): archive.write(path, path.relative_to(stage))
    temporary.replace(portable)
    (release / 'SHA256SUMS.txt').write_text(hashlib.sha256(portable.read_bytes()).hexdigest() + '  ' + portable.name + '\n', encoding='ascii')
    print(json.dumps(dict(bundle=str(bundle), archive=str(portable), sha256=hashlib.sha256(portable.read_bytes()).hexdigest())))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--version', default='2.0.0')
    parser.add_argument('--crt-dir', type=Path, required=True, help='Visual Studio x64 Microsoft.VC*.CRT redistributable directory')
    parser.add_argument('--crt-license-dir', type=Path, required=True, help='Visual Studio Licenses/<locale> directory')
    parser.add_argument('--replace', action='store_true', help='Replace a reviewed, unpublished artifact')
    args = parser.parse_args()
    build(args.version, args.crt_dir.resolve(), args.crt_license_dir.resolve(), args.replace)
