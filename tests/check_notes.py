import importlib.util
from pathlib import Path
from datetime import datetime, timedelta
import tkinter as tk
import queue
import threading
from unittest.mock import patch, MagicMock
from types import SimpleNamespace
from tkinter import font as tkfont

spec = importlib.util.spec_from_file_location('calendar_app', Path(__file__).resolve().parents[1] / 'daynest.py')
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)
start = datetime.now(m.LOCAL_TZ).replace(hour=17, minute=0, second=0, microsecond=0)
description = '第一行：准备资料；带上纸笔。\n' + '这是一条需要完整展示的很长的中文备注，' * 15 + '\n字面量 \\n 不应变成换行'
raw = m.fold_ics_lines(['BEGIN:VCALENDAR', 'VERSION:2.0', 'BEGIN:VEVENT', 'UID:test-notes',
                       'DTSTART:' + m.ics_time(start), 'DTEND:' + m.ics_time(start + timedelta(hours=1)),
                       'SUMMARY:测试备注', 'DESCRIPTION:' + m.escape_ics_text(description),
                       'BEGIN:VALARM', 'DESCRIPTION:提醒文字，不是日程备注', 'END:VALARM',
                       'END:VEVENT', 'END:VCALENDAR'])
events = m.parse_events(raw, '个人', start - timedelta(days=1), start + timedelta(days=1),
                        {'href': 'https://caldav.icloud.com/test.ics', 'etag': 'v1'})
event = events[0]
assert m.event_notes(event) == description
edited = m.edit_event_ics(raw, '修改标题', start, start + timedelta(hours=2))
assert m.parse_events(edited, '个人', start - timedelta(days=1), start + timedelta(days=1))[0][4]['description'] == description
for value in ('修改后的备注\n第二行，包含分号；和反斜杠\\', ''):
    edited = m.edit_event_ics(raw, '修改标题', start, start + timedelta(hours=2), value)
    parsed = m.parse_events(edited, '个人', start - timedelta(days=1), start + timedelta(days=1))[0]
    assert m.event_notes(parsed) == value
    assert 'DESCRIPTION:提醒文字，不是日程备注' in edited
    _, created = m.new_event_ics('新日程', start, start + timedelta(hours=1), value)
    assert m.event_notes(m.parse_events(created, '个人', start - timedelta(days=1), start + timedelta(days=1))[0]) == value

root = tk.Tk()
m.apply_theme(root)
root.geometry('360x580')
font = tkfont.Font(font=('Microsoft YaHei UI', 9))
preview = m.note_preview(description, font, 250)
assert preview.endswith('...') and '\n' not in preview
assert font.measure(preview) <= 250
app = m.App.__new__(m.App)
app.closed = threading.Event()
app.callbacks = queue.Queue()
app.root = root
app.config = {}
app.pins = []
app.events = events
app.month_cache = {}
app.desktop_mode = False
app.modal_windows = set()
app.save_pins = lambda: None
app.build()
root.update()
app.render(events)
text = app.listbox.get('1.0', 'end')
assert '...' in text and '第一行' in text
app.toggle_pin(event)
assert m.event_notes(app.pinned_event(app.pins[0])) == description
app.event_details(event)
root.update()
dialog = next(iter(app.modal_windows))
def descendants(widget):
    for child in widget.winfo_children():
        yield child
        yield from descendants(child)
notes = next(child for child in descendants(dialog) if isinstance(child, tk.Text))
assert notes.get('1.0', 'end-1c') == description
dialog.destroy()
app.calendars = [('https://caldav.icloud.com/example/', '个人')]
app.syncing = app.write_busy = False
app.config = {'username': 'test', 'password': 'test'}
app.event_form(event)
root.update()
dialog = next(iter(app.modal_windows))
editor = next(child for child in descendants(dialog) if isinstance(child, tk.Text))
assert editor.get('1.0', 'end-1c') == description
editor.delete('1.0', 'end')
editor.insert('1.0', '从编辑表单保存的备注\n第二行')
save = next(child for child in descendants(dialog) if isinstance(child, m.ttk.Button) and child.cget('text') == '保存到 iCloud')
with patch.object(m.CalDAV, 'put_event') as put, patch.object(m, 'unprotect', return_value='test'), \
     patch.object(m, 'get_logger', return_value=MagicMock()), \
     patch.object(m.threading, 'Thread', side_effect=lambda target, daemon: SimpleNamespace(start=target)):
    save.invoke()
    assert put.call_count == 1
    saved_raw = put.call_args.args[1]
    assert put.call_args.args[2] == 'v1'
    assert m.event_notes(m.parse_events(saved_raw, '个人', start - timedelta(days=1), start + timedelta(days=1))[0]) == '从编辑表单保存的备注\n第二行'
root.destroy()
print('Notes parsing, truncation, pins and details checks passed.')
