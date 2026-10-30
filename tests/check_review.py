import importlib.util
from pathlib import Path
from datetime import date, datetime, timedelta, timezone
from concurrent.futures import ThreadPoolExecutor
from tempfile import TemporaryDirectory
import json
import queue
import threading
import tkinter as tk
from unittest.mock import MagicMock, patch

spec = importlib.util.spec_from_file_location('calendar_app', Path(__file__).resolve().parents[1] / 'daynest.py')
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)

with TemporaryDirectory(dir=Path(__file__).parent) as directory:
    target = Path(directory) / 'config.json'
    m.atomic_write(target, '{"original": true}', 'utf-8')
    with patch.object(Path, 'replace', side_effect=OSError('simulated interruption')):
        try:
            m.atomic_write(target, '{"new": true}', 'utf-8')
        except OSError:
            pass
    assert json.loads(target.read_text()) == {'original': True}
    assert not list(Path(directory).glob('*.tmp'))
    with ThreadPoolExecutor(max_workers=4) as pool:
        list(pool.map(lambda n: m.atomic_write(target, json.dumps({'value': n}), 'utf-8'), range(20)))
    assert isinstance(json.loads(target.read_text())['value'], int)
    assert not list(Path(directory).glob('*.tmp'))
    target.write_text('incomplete {', encoding='utf-8')
    with patch.object(m, 'CONFIG_FILE', target):
        assert m.load_config()['username'] == ''

app = m.App.__new__(m.App)
app.closed = threading.Event()
app.callbacks = queue.Queue()
app.root = MagicMock()
completed = []
worker = threading.Thread(target=lambda: app.post(completed.append, 'done'))
worker.start()
worker.join()
assert not completed and not app.root.after.called
app.drain_callbacks()
assert completed == ['done']
app.closed.set()
app.post(completed.append, 'late')
assert app.callbacks.empty()

app.config = {'username': 'new-account'}
app.cache = {}
app.cache_lock = threading.Lock()
app.sync_token = current_token = object()
app.finish = MagicMock()
app.sync_failed = MagicMock()
with patch.object(m, 'save_cache') as save:
    app.apply_sync(object(), 'old-account', [], [], 1, 1)
    app.apply_sync_error(object(), 'old-account', 'stale error')
    assert not app.cache and not save.called and not app.sync_failed.called
    app.apply_sync(current_token, 'new-account', [], [], 1, 1)
    assert app.cache['username'] == 'new-account' and app.finish.call_count == 1

today = date.today()
start = datetime.combine(today, datetime.min.time(), m.LOCAL_TZ)
event = (start - timedelta(hours=2), '跨天日程', '个人', False, {'duration_seconds': 4 * 3600})
app.month_cache = {today.strftime('%Y-%m'): {'events': m.serialize_events([event])}}
with patch.object(m, 'deserialize_events', wraps=m.deserialize_events) as decode:
    first = app.month_events(today)
    for _ in range(100):
        assert app.month_events(today) is first
    assert decode.call_count == 1
    app.month_cache[today.strftime('%Y-%m')] = {'events': []}
    assert app.month_events(today) == []
    assert decode.call_count == 2

raw = '\r\n'.join(['BEGIN:VCALENDAR', 'BEGIN:VEVENT', 'UID:repeat', 'DTSTART:20261001T090000Z',
                    'DTEND:20261001T100000Z', 'SUMMARY:例会', 'RRULE:FREQ=DAILY;COUNT=5',
                    'EXDATE:20261002T090000Z', 'EXDATE:20261003T090000Z',
                    'RDATE:20261001T090000Z,20261007T090000Z', 'END:VEVENT',
                    'BEGIN:VEVENT', 'UID:repeat', 'RECURRENCE-ID:20261004T090000Z',
                    'DTSTART:20261004T140000Z', 'DTEND:20261004T150000Z', 'SUMMARY:改期例会', 'END:VEVENT',
                    'BEGIN:VEVENT', 'UID:repeat', 'RECURRENCE-ID:20261005T090000Z',
                    'STATUS:CANCELLED', 'END:VEVENT', 'END:VCALENDAR'])
found = m.parse_events(raw, '个人', datetime(2026, 10, 1, tzinfo=timezone.utc),
                        datetime(2026, 10, 8, tzinfo=timezone.utc))
assert sorted(e[0].astimezone(timezone.utc).strftime('%d %H') for e in found) == ['01 09', '04 14', '07 09']
assert all(datetime.fromisoformat(e[4]['end']) > e[0] for e in found)
timed = '\r\n'.join(['BEGIN:VCALENDAR', 'BEGIN:VEVENT', 'UID:duration',
                      'DTSTART:20261001T230000Z', 'DURATION:PT3H', 'END:VEVENT', 'END:VCALENDAR'])
found = m.parse_events(timed, '个人', datetime(2026, 10, 1, tzinfo=timezone.utc), datetime(2026, 10, 3, tzinfo=timezone.utc))
assert found[0][4]['duration_seconds'] == 3 * 3600

root = tk.Tk()
m.apply_theme(root)
root.geometry('360x580')
app = m.App.__new__(m.App)
app.root = root
app.config = {}
app.pins = []
app.month_cache = {}
app.events = []
app.build()
root.update()
app.render([event])
tag_count = len(app.listbox.tag_names())
command_count = len(app.listbox._tclCommands)
for _ in range(25):
    app.render([event])
assert len(app.listbox.tag_names()) == tag_count
assert len(app.listbox._tclCommands) == command_count
assert '跨天日程' in app.listbox.get('1.0', 'end')
app.save_pins = lambda: None
app.toggle_pin(event)
root.update()
cards = app.pins_frame.winfo_children()
app.render_pins()
assert cards == app.pins_frame.winfo_children()
root.destroy()
print('Atomic writes, callback isolation, stale results, decode reuse, recurrence exceptions and UI resource checks passed.')
