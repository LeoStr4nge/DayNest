"""Check real Windows mutex lifetime and startup isolation without user data."""
from pathlib import Path
import subprocess
import os
import signal
import sys
import uuid

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import daynest as m


def check():
    name = 'Local\\DayNest.Test.' + uuid.uuid4().hex
    guard = m.SingleInstance(name)
    other = m.SingleInstance(name)
    try:
        assert guard.acquire()
        assert not other.acquire()
        guard.close()
        assert other.acquire()
    finally:
        guard.close()
        other.close()

    child = subprocess.Popen([sys.executable, '-B', __file__, '--hold', name],
                             stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True)
    try:
        assert child.stdout.readline().strip() == 'LOCKED'
        owner_pid = int(child.stdout.readline().strip())
        assert not guard.acquire()
        # Windows venv python.exe may be a redirector process. Terminate the
        # actual child that owns the test mutex, not just the redirector.
        os.kill(owner_pid, signal.SIGTERM)
        child.wait(timeout=5)
        assert guard.acquire(), 'Terminating the owner must release the mutex'
    finally:
        guard.close()
        if child.poll() is None:
            child.kill()
            child.wait(timeout=5)
        child.stdin.close()
        child.stdout.close()
    print('Single-instance checks passed.')


if __name__ == '__main__':
    if len(sys.argv) > 1 and sys.argv[1] == '--hold':
        guard = m.SingleInstance(sys.argv[2])
        assert guard.acquire()
        print('LOCKED', flush=True)
        print(os.getpid(), flush=True)
        sys.stdin.read()
        guard.close()
    else:
        check()
