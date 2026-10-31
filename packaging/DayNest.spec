from pathlib import Path

project = Path(SPECPATH).parent
a = Analysis(
    [str(project / 'DayNest.pyw')],
    pathex=[str(project)],
    binaries=[],
    datas=[(str(project / 'assets' / 'DayNest.ico'), 'assets')],
    hiddenimports=['dateutil.zoneinfo'],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=['PIL', 'pytest'],
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz, a.scripts, [],
    exclude_binaries=True,
    name='DayNest',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    version=str(project / 'build' / 'version_info.txt'),
    icon=str(project / 'assets' / 'DayNest.ico'),
    contents_directory='_internal',
)
coll = COLLECT(exe, a.binaries, a.datas, strip=False, upx=False, name='DayNest')
