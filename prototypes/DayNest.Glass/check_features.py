"""Run isolated native WinUI feature checks and always close the test process."""
from pathlib import Path
import subprocess
import tempfile
import uuid
import sys

exe = Path(sys.argv[1] if len(sys.argv) > 1 else Path(__file__).parent / 'bin/ParityReview/DayNest.Glass.exe').resolve()
report = exe.parent / 'features-check.txt'
report.unlink(missing_ok=True)
with tempfile.TemporaryDirectory(prefix='daynest-features-') as temporary:
    process = subprocess.Popen([str(exe), '--instance-window-check', uuid.uuid4().hex,
                               str(Path(temporary) / 'window.json'), '--features-check', '--normal-window'],
                              stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        assert process.wait(timeout=20) == 0
        outcome = report.read_text(encoding='utf-8')
        assert outcome.startswith('PASS:'), outcome
        print(outcome)
    finally:
        if process.poll() is None:
            process.terminate(); process.wait(timeout=5)
print('All feature-check windows closed; real startup entries, preferences and calendar data were not changed.')
