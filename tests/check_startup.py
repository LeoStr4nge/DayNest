import importlib.util
from pathlib import Path
from unittest.mock import patch, MagicMock
import time

spec = importlib.util.spec_from_file_location('calendar_app', Path(__file__).resolve().parents[1] / 'daynest.py')
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)
calendars = [('https://caldav.icloud.com/test/', '个人')]
client = MagicMock()
client.discover.return_value = calendars
client.events.return_value = []
saved = []
with patch.object(m, 'load_config', return_value={'username': 'test', 'password': 'fake', 'desktop': False}), \
     patch.object(m, 'load_cache', return_value={}), \
     patch.object(m, 'save_cache', side_effect=lambda cache: saved.append(dict(cache))), \
     patch.object(m, 'unprotect', return_value='fake'), \
     patch.object(m, 'get_logger', return_value=MagicMock()), \
     patch.object(m, 'CalDAV', return_value=client):
    app = m.App()
    app.root.after(10, app.refresh)
    app.root.after(1500, app.root.quit)
    app.root.mainloop()
    assert not app.syncing
    assert app.calendars == calendars
    assert len(app.month_cache) == 3
    assert saved[-1]['username'] == 'test'
    assert '已同步' in app.status.cget('text')
    resource = []
    def put(href, raw, etag, create):
        assert create
        resource[:] = [{'href': href, 'raw': raw, 'etag': 'new-version'}]
    client.put_event.side_effect = put
    client.events.side_effect = lambda *args: list(resource)
    app.event_form()
    dialog = next(iter(app.modal_windows))
    def descendants(widget):
        for child in widget.winfo_children():
            yield child
            yield from descendants(child)
    widgets = list(descendants(dialog))
    title = next(w for w in widgets if isinstance(w, m.ttk.Entry))
    title.insert(0, '队列写入测试')
    notes = next(w for w in widgets if isinstance(w, m.tk.Text))
    notes.insert('1.0', '验证写入后刷新与缓存更新')
    button = next(w for w in widgets if isinstance(w, m.ttk.Button) and w.cget('text') == '保存到日历')
    button.invoke()
    app.root.after(700, app.root.quit)
    app.root.mainloop()
    assert not app.write_busy and not app.syncing
    assert client.put_event.call_count == 1
    assert app.events[0][1] == '队列写入测试'
    assert m.event_notes(app.events[0]) == '验证写入后刷新与缓存更新'
    app.root.destroy()
    assert app.closed.is_set()
    time.sleep(0.3)
print('Startup, queued callbacks, background preload and window-close checks passed.')
