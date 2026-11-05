import importlib.util
from pathlib import Path
import ssl
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

print('Transient read retry checks passed.')
