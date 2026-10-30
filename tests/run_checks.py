"""Run the offline Windows/Tk checks from any working directory."""
from pathlib import Path
import os
import subprocess
import sys


if __name__ == '__main__':
    project = Path(__file__).resolve().parents[1]
    environment = dict(os.environ, PYTHONDONTWRITEBYTECODE='1')
    checks = sorted(Path(__file__).parent.glob('check_*.py'))
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
