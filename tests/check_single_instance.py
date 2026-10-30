"""Check real Windows mutex lifetime and startup isolation without user data."""
from pathlib import Path
import subprocess
import sys
import uuid
from unittest.mock import MagicMock, patch

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
        assert not guard.acquire()
        child.terminate()
        child.wait(timeout=5)
        assert guard.acquire(), 'Terminating the owner must release the mutex'
    finally:
        guard.close()
        if child.poll() is None:
            child.kill()
            child.wait(timeout=5)
        child.stdin.close()
        child.stdout.close()

    with patch.object(m, 'SingleInstance') as factory, \
         patch.object(m, 'App') as app, \
         patch.object(m, 'startup_message') as message, \
         patch.object(m, 'load_config', return_value={}) as load, \
         patch.object(m, 'save_config') as save:
        guard_mock = factory.return_value
        guard_mock.acquire.return_value = False
        assert m.main(restore_window=True) == 0
        app.assert_not_called()
        load.assert_not_called()
        save.assert_not_called()
        message.assert_called_once()
        guard_mock.close.assert_called_once()
        guard_mock.reset_mock()
        guard_mock.acquire.side_effect = OSError('mutex unavailable')
        assert m.main() == 1
        app.assert_not_called()
        guard_mock.close.assert_called_once()
        guard_mock.reset_mock()
        guard_mock.acquire.side_effect = None
        guard_mock.acquire.return_value = True
        assert m.main(restore_window=True) == 0
        save.assert_called_once_with({'desktop': False})
        app.return_value.run.assert_called_once()
        guard_mock.close.assert_called_once()
        guard_mock.reset_mock()
        app.return_value.run.side_effect = RuntimeError('startup failed')
        try:
            m.main()
        except RuntimeError:
            pass
        else:
            raise AssertionError('Expected startup failure')
        guard_mock.close.assert_called_once()
    print('Single-instance checks passed.')


if __name__ == '__main__':
    if len(sys.argv) > 1 and sys.argv[1] == '--hold':
        guard = m.SingleInstance(sys.argv[2])
        assert guard.acquire()
        print('LOCKED', flush=True)
        sys.stdin.read()
        guard.close()
    else:
        check()
