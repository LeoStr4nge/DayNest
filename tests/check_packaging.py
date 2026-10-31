"""Source and frozen startup commands without modifying real startup entries."""
from pathlib import Path
import subprocess
import sys
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import daynest as m

with patch.object(sys, 'frozen', False, create=True):
    command = m.launch_command(True)
    assert Path(command[0]).name.lower() in ('pythonw.exe', 'python.exe')
    assert Path(command[1]).name == 'DayNest.pyw'
    assert command[-1] == '--restore-window'

with patch.object(sys, 'frozen', True, create=True), patch.object(sys, 'executable', r'C:\Program Files\DayNest\DayNest.exe'):
    assert m.launch_command() == [sys.executable]
    assert m.launch_command(True) == [sys.executable, '--restore-window']
    app = m.App.__new__(m.App)
    with patch.object(m.winreg, 'CreateKey') as create, patch.object(m.winreg, 'SetValueEx') as write:
        app.set_autostart(True)
        assert write.call_args.args[-1] == subprocess.list2cmdline([sys.executable])
        assert write.call_args.args[1] == 'DayNest'

with patch.object(sys, 'argv', ['DayNest.exe', '--restore-window']), \
     patch.object(m, 'SingleInstance') as guard, patch.object(m, 'App') as app, \
     patch.object(m, 'load_config', return_value={}), patch.object(m, 'save_config') as save:
    guard.return_value.acquire.return_value = True
    assert m.main() == 0
    save.assert_called_once_with({'desktop': False})
    app.return_value.run.assert_called_once()
assert (Path(m.__file__).parent / 'assets' / 'DayNest.ico').is_file()
for enabled in (False, True):
    with patch.object(sys, 'frozen', True, create=True), \
         patch.object(m, 'load_config', return_value={'desktop': False, 'autostart': enabled}), \
         patch.object(m, 'load_cache', return_value={}), patch.object(m.App, 'set_autostart') as startup:
        app = m.App()
        if enabled:
            startup.assert_called_once_with(True)
        else:
            startup.assert_not_called()
        app.root.destroy()
print('Packaging entrypoint, restore flag, icon and autostart checks passed.')
