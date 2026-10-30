import importlib.util
from pathlib import Path
from datetime import datetime
import ssl
import tkinter as tk
from urllib.error import URLError, HTTPError
from unittest.mock import patch, MagicMock

spec = importlib.util.spec_from_file_location('calendar_app', Path(__file__).resolve().parents[1] / 'daynest.py')
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)
client = m.CalDAV('test', 'test')
response = MagicMock()
response.__enter__.return_value.read.return_value = b'<ok/>'
eof = URLError(ssl.SSLEOFError(8, 'UNEXPECTED_EOF_WHILE_READING'))
with patch.object(m, 'get_logger', return_value=MagicMock()), patch.object(m.time, 'sleep') as sleep:
    with patch.object(m, 'urlopen', side_effect=[eof, response]) as read:
        assert client.request('REPORT', 'https://caldav.icloud.com/', '<query/>').tag == 'ok'
        assert read.call_count == 2
        sleep.assert_called_once_with(1)
    with patch.object(m, 'urlopen', side_effect=eof) as read:
        try:
            client.request('REPORT', 'https://caldav.icloud.com/', '<query/>')
            raise AssertionError('Expected failure after retries')
        except ValueError as error:
            assert '自动重试' in str(error)
        assert read.call_count == 3
    for error in [URLError(ssl.SSLCertVerificationError(1, 'certificate failed')),
                  HTTPError('https://caldav.icloud.com/', 401, 'Unauthorized', {}, None)]:
        with patch.object(m, 'urlopen', side_effect=error) as read:
            try:
                client.request('PROPFIND', 'https://caldav.icloud.com/', '<query/>')
            except (URLError, ValueError):
                pass
            assert read.call_count == 1

root = tk.Tk()
m.apply_theme(root)
root.geometry('360x580')
a = m.App.__new__(m.App)
a.root = root
a.pins_frame = tk.Frame(root)
a.pins_frame.pack(fill='x')
a.status = tk.Label(root, text='同步状态')
a.status.pack(fill='x')
a.save_pins = lambda: None
start = datetime.now(m.LOCAL_TZ)
event = (start, '测试固定日程', '个人', False, {'href': 'https://caldav.icloud.com/test.ics'})
a.pins = []
a.toggle_pin(event)
root.update()
pinned_y = a.status.winfo_y()
a.remove_pin(m.event_key(event))
root.update()
assert a.pins_frame.winfo_manager() == ''
assert a.status.winfo_y() < pinned_y
a.toggle_pin(event)
root.update()
assert a.pins_frame.winfo_manager() == 'pack'
assert a.status.winfo_y() == pinned_y
root.destroy()
print('Pin layout and transient read retry checks passed.')
