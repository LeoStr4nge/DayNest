from pathlib import Path
import subprocess
import sys

from daynest import load_config, save_config


if __name__ == '__main__':
    config = load_config()
    config['desktop'] = False
    save_config(config)
    subprocess.Popen([sys.executable, str(Path(__file__).with_name('DayNest.pyw'))])
