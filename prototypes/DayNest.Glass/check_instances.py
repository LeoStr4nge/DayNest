"""Actual-process WinUI lifetime/activation checks, with isolated locks and data."""
import concurrent.futures
import json
import subprocess
import sys
import tempfile
import time
import uuid
from pathlib import Path

EXE = Path(sys.argv[1] if len(sys.argv) > 1 else Path(__file__).parent / 'bin/InstanceReview/DayNest.Glass.exe').resolve()
SECONDARY = Path(sys.argv[2]).resolve() if len(sys.argv) > 2 else EXE


def read(path):
    try: return json.loads(path.read_text(encoding='utf-8'))
    except (OSError, ValueError): return {}


def wait_for(predicate, label, timeout=12):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        value = predicate()
        if value: return value
        time.sleep(.03)
    raise AssertionError('Timed out: ' + label)


def start(*args, secondary=False):
    return subprocess.Popen([str(SECONDARY if secondary else EXE), *map(str, args)], stdin=subprocess.PIPE,
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, text=True)


def finish(process):
    if process.poll() is None:
        try:
            process.stdin.write('exit\n'); process.stdin.flush()
            process.wait(timeout=4)
        except (OSError, subprocess.TimeoutExpired):
            process.terminate(); process.wait(timeout=5)
    process.stdin.close()


with tempfile.TemporaryDirectory(prefix='daynest-instance-check-') as directory:
    root = Path(directory)
    scope = uuid.uuid4().hex
    owner_report = root / 'owner.json'
    owner = start('--instance-probe', scope, 'hold', owner_report)
    try:
        wait_for(lambda: read(owner_report).get('acquired'), 'headless owner ready')
        def probe(role, name, *extra):
            report = root / (name + '.json')
            process = start('--instance-probe', scope, role, report, *extra, secondary=True)
            try: code = process.wait(timeout=10)
            finally: finish(process)
            return code, read(report)
        code, result = probe('try', 'duplicate')
        assert code == 3 and result['acquired'] is False
        # Burst launches all reach the same server and never start a second owner.
        with concurrent.futures.ThreadPoolExecutor(max_workers=6) as pool:
            outcomes = list(pool.map(lambda n: probe('notify', 'burst-' + str(n)), range(6)))
        assert all(code == 0 and result['delivered'] for code, result in outcomes), outcomes
        wait_for(lambda: read(owner_report).get('count') == 6, 'all activations delivered')
        assert probe('notify', 'normal', '--normal-window')[0] == 0
        wait_for(lambda: read(owner_report).get('normal'), 'normal-window request delivered')
        finish(owner)
        assert probe('try', 'after-close')[1]['acquired'], 'Normal exit must release lifetime lock'
        # Headless owner dies without cleanup; the same name must be reusable.
        owner_report.unlink()
        owner = start('--instance-probe', scope, 'hold', owner_report)
        wait_for(lambda: read(owner_report).get('acquired'), 'crash owner ready')
        owner.terminate(); owner.wait(timeout=5)
        assert probe('try', 'after-crash')[1]['acquired'], 'Crash must release lifetime lock'
    finally: finish(owner)
    # A request arriving before UI registration is retained, including recovery.
    owner_report.unlink()
    owner = start('--instance-probe', scope, 'hold-late', owner_report)
    try:
        wait_for(lambda: read(owner_report).get('acquired'), 'pending owner ready')
        assert probe('notify', 'pending', '--normal-window')[0] == 0
        assert read(owner_report)['count'] == 0
        owner.stdin.write('attach\n'); owner.stdin.flush()
        wait_for(lambda: read(owner_report).get('count') == 1 and read(owner_report).get('normal'), 'pending activation replayed')
    finally: finish(owner)
    print('PASS: real-process rejection, burst activation, early request replay, graceful exit and crash recovery.', flush=True)

    # Real WinUI startup/activation, fake month transport, no account/cache IO.
    # Each owner auto-closes in eight seconds even if the runner is stopped.
    def window_case(name, flags, minimized=False, settings=False, early=False):
        report = root / (name + '.json')
        test_scope = uuid.uuid4().hex
        process = start('--instance-window-check', test_scope, report, *flags)
        participants = [process]
        try:
            if early:
                participants += [start('--instance-window-check', test_scope, report, secondary=True) for _ in range(3)]
                winner = wait_for(lambda: read(report).get('pid'), 'concurrent startup winner')
                process = next(p for p in participants if p.pid == winner)
                clients = [p for p in participants if p != process]
                try:
                    for client in clients: assert client.wait(timeout=10) == 0
                finally:
                    for client in clients: finish(client)
            initial = wait_for(lambda: read(report) if 'pid' in read(report) and (not settings or read(report).get('settingsOpen')) else None, name + ' window ready')
            if early:
                initial = wait_for(lambda: read(report) if read(report).get('activationCount', 0) >= 1 else None, 'startup activation')
                assert initial['pid'] == process.pid
            if minimized: assert initial['minimized'] is True
            if settings: assert initial['settingsOpen'] is True
            expected_desktop = not ('--normal-window' in flags)
            assert initial['desktop'] is expected_desktop
            baseline = initial['activationCount']
            duplicate = start('--instance-window-check', test_scope, report, secondary=True)
            try: assert duplicate.wait(timeout=10) == 0
            finally: finish(duplicate)
            try:
                state = wait_for(lambda: read(report) if read(report).get('activationCount', 0) >= baseline + 1 else None, name + ' activation')
            except AssertionError as error:
                raise AssertionError(str(error) + ': ' + str(read(report)) + ', owner exit=' + str(process.poll())) from error
            assert state['pid'] == process.pid and process.poll() is None
            assert state['desktop'] is expected_desktop and not state['minimized'] and state['visible']
            if settings: assert state['settingsOpen'], 'Duplicate launch must not discard the open dialog'
            recovery = start('--instance-window-check', test_scope, report, '--normal-window', secondary=True)
            try: assert recovery.wait(timeout=10) == 0
            finally: finish(recovery)
            try:
                state = wait_for(lambda: read(report) if read(report).get('activationCount', 0) >= baseline + 2 and not read(report).get('settingsOpen') and not read(report).get('desktop') else None,
                                 name + ' ordinary window recovery')
            except AssertionError as error:
                raise AssertionError(str(error) + ': ' + str(read(report))) from error
            assert state['pid'] == process.pid and not state['desktop'] and state['shownInSwitchers'] and state['visible']
            assert process.poll() is None
        finally:
            try: process.wait(timeout=12)
            finally:
                for participant in participants: finish(participant)
        assert process.returncode == 0, 'The UI owner must exit gracefully'
        release_report = root / (name + '-release.json')
        verifier = start('--instance-probe', test_scope, 'try', release_report, secondary=True)
        try: assert verifier.wait(timeout=10) == 0 and read(release_report)['acquired']
        finally: finish(verifier)
    window_case('desktop', [])
    window_case('minimized', ['--normal-window', '--instance-start-minimized'], minimized=True)
    window_case('settings', ['--instance-open-settings-check'], settings=True)
    window_case('early', [], early=True)
    print('PASS: real WinUI duplicate activation, minimized restore, desktop recovery and settings preservation/cancel.', flush=True)

print('All instance checks passed; all child processes closed. No personal calendar data or settings were modified.')
