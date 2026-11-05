"""Run backend and WinUI bridge offline checks from any working directory."""
from pathlib import Path
import os
import subprocess
import sys


if __name__ == '__main__':
    project = Path(__file__).resolve().parents[1]
    environment = dict(os.environ, PYTHONDONTWRITEBYTECODE='1')
    checks = sorted(Path(__file__).parent.glob('check_*.py'))
    bridge = project / 'prototypes' / 'DayNest.Glass'
    checks += [bridge / name for name in ('check_bridge.py', 'check_calendar_sync.py',
               'check_event_actions.py', 'check_pin_tracking.py', 'check_pins.py')]
    failed = []
    for check in checks:
        print(f'Running {check.name}', flush=True)
        result = subprocess.run([sys.executable, '-B', str(check)], cwd=project, env=environment)
        if result.returncode:
            failed.append(check.name)
    print(f'{len(checks) - len(failed)}/{len(checks)} checks passed.')
    if failed:
        print('Failed: ' + ', '.join(failed))
        raise SystemExit(1)
