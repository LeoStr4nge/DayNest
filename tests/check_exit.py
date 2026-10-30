"""Verify process exit, not only that the Tk window was destroyed."""
from pathlib import Path
import importlib.util
import subprocess
import sys
import threading
import time
from unittest.mock import MagicMock, patch


def child(source, mode):
    spec = importlib.util.spec_from_file_location('daynest_exit_test', source)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    started, written = threading.Event(), threading.Event()
    client = MagicMock()
    client.discover.return_value = [('https://caldav.icloud.com/test/', 'Test')]
    def events(*_args):
        started.set()
        if mode != 'write':
            time.sleep(30)  # Represents a network read that cannot be interrupted.
        return []
    def put(*_args, **_kwargs):
        time.sleep(0.2)
        written.set()
    client.events.side_effect = events
    client.put_event.side_effect = put
    with patch.object(m, 'load_config', return_value={'username': 'test', 'password': 'fake', 'desktop': False}), \
         patch.object(m, 'load_cache', return_value={}), patch.object(m, 'save_config'), \
         patch.object(m, 'save_cache'), patch.object(m, 'get_logger', return_value=MagicMock()), \
         patch.object(m, 'unprotect', return_value='fake'), patch.object(m, 'CalDAV', return_value=client):
        app = m.App()
        app.root.withdraw()
        app.calendars = client.discover.return_value
        if mode == 'write':
            app.event_form()
            dialog = next(iter(app.modal_windows))
            def descendants(widget):
                for widget_child in widget.winfo_children():
                    yield widget_child
                    yield from descendants(widget_child)
            widgets = list(descendants(dialog))
            next(w for w in widgets if isinstance(w, m.ttk.Entry)).insert(0, 'Exit test')
            next(w for w in widgets if isinstance(w, m.ttk.Button) and w.cget('text') == '保存到 iCloud').invoke()
            app.close()
            assert app.close_requested and not app.closed.is_set()
        else:
            if mode == 'month':
                app.load_month(m.date.today().replace(day=1))
            else:
                app.refresh()
            def close_when_started():
                if not started.is_set():
                    app.root.after(20, close_when_started)
                    return
                print('BLOCKED_READ_STARTED', flush=True)
                (app.close if hasattr(app, 'close') else app.root.destroy)()
            app.root.after(20, close_when_started)
        app.run()
        if mode == 'write':
            assert written.is_set()
        print('MAINLOOP_EXITED', flush=True)


if __name__ == '__main__':
    if len(sys.argv) > 1 and sys.argv[1] == '--child':
        child(Path(sys.argv[2]), sys.argv[3])
    else:
        source = Path(__file__).resolve().parents[1] / 'daynest.py'
        if len(sys.argv) > 2 and sys.argv[1] == '--baseline':
            baseline = Path(sys.argv[2])
            process = subprocess.Popen([sys.executable, '-B', __file__, '--child', str(baseline), 'read'],
                                       stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
            try:
                output, error = process.communicate(timeout=4)
                raise AssertionError(f'Expected original process to linger: {output} {error}')
            except subprocess.TimeoutExpired:
                process.kill()
                output, error = process.communicate()
                assert 'BLOCKED_READ_STARTED' in output and 'MAINLOOP_EXITED' in output, error
                print('Original behavior reproduced: window closed, process still alive after 4 seconds.')
        for mode in ('read', 'month', 'write'):
            t0 = time.monotonic()
            result = subprocess.run([sys.executable, '-B', __file__, '--child', str(source), mode],
                                    capture_output=True, text=True, timeout=4)
            assert result.returncode == 0, result.stdout + result.stderr
            assert 'MAINLOOP_EXITED' in result.stdout
            print(f'{mode}: process exited in {time.monotonic() - t0:.2f}s.')
