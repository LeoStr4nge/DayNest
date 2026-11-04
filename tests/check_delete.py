"""Conditional CalDAV deletion must not redirect, retry or erase a stale event."""
from pathlib import Path
import sys
from io import BytesIO
from unittest.mock import Mock, patch
from urllib.error import HTTPError
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import daynest as c

url = 'https://calendar.example/events/test.ics'
client = c.CalDAV('test', 'test', connection=c.connection_config({
    'provider': 'custom', 'discovery_url': 'https://calendar.example/'}))
response = Mock()
response.__enter__ = Mock(return_value=response)
response.__exit__ = Mock(return_value=False)
with patch.object(c, 'urlopen', return_value=response) as opened:
    client.delete_event(url, '"v1"')
    request = opened.call_args.args[0]
    assert request.method == 'DELETE' and request.get_header('If-match') == '"v1"'
    assert opened.call_count == 1
for code in (401, 403, 404, 410, 412, 500, 307):
    error = HTTPError(url, code, 'test', {'Location': '/other.ics'}, BytesIO())
    with patch.object(c, 'urlopen', side_effect=error) as opened:
        try:
            client.delete_event(url, '"v1"')
            raise AssertionError('Deletion failure must be reported')
        except ValueError:
            pass
        assert opened.call_count == 1
with patch.object(c, 'urlopen') as opened:
    for href, etag in ((url, ''), ('https://foreign.example/test.ics', '"v1"')):
        try:
            client.delete_event(href, etag)
            raise AssertionError('Unsafe delete must be refused')
        except ValueError:
            pass
    opened.assert_not_called()
print('Conditional delete, conflict/auth handling, redirect rejection and no-retry checks passed.')
