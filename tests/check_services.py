"""Offline multi-service discovery, origin policy, transport and settings checks."""
from pathlib import Path
from io import BytesIO
import sys
from unittest.mock import Mock, patch
from urllib.error import HTTPError
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import daynest as m

CUSTOM = {'provider': 'custom', 'discovery_url': 'https://dav.example/.well-known/caldav'}


def multistatus(properties, href='/'):
    return ('<d:multistatus xmlns:d="DAV:" xmlns:c="urn:ietf:params:xml:ns:caldav">'
            f'<d:response><d:href>{href}</d:href><d:propstat><d:prop>{properties}</d:prop>'
            '<d:status>HTTP/1.1 200 OK</d:status></d:propstat></d:response></d:multistatus>')


CALENDAR = '<d:resourcetype><d:collection/><c:calendar/></d:resourcetype><d:displayname>Work</d:displayname>'
PRINCIPAL = multistatus('<d:current-user-principal><d:href>/principals/alice/</d:href></d:current-user-principal>')
HOME = multistatus('<c:calendar-home-set><d:href>../../calendars/alice/</d:href></c:calendar-home-set>')
LIST = multistatus(CALENDAR, 'work/')


def response(text):
    return BytesIO(text.encode())


def expect_invalid(action):
    try:
        action()
    except ValueError:
        return
    raise AssertionError('Expected invalid configuration or origin')


assert m.connection_config({})['discovery_url'] == m.ICLOUD_DISCOVERY
assert m.server_url('https://DAV.example:443/日历/') == 'https://dav.example/%E6%97%A5%E5%8E%86/'
for bad in ('http://dav.example/', 'https://u:p@dav.example/', 'file:///tmp/a',
            'https://dav.example/#fragment', 'https://dav.example:0/', 'https://bad host/'):
    expect_invalid(lambda: m.connection_config(dict(CUSTOM, discovery_url=bad)))
expect_invalid(lambda: m.connection_config(dict(CUSTOM, trusted_origins='https://other.example/path')))
config = m.connection_config(dict(CUSTOM, trusted_origins='https://OTHER.example:443, https://other.example/'))
assert config['trusted_origins'] == ['https://other.example']
client = m.CalDAV('same-user', 'fake', connection=CUSTOM)
client.validate_url('https://dav.example/path')
expect_invalid(lambda: client.validate_url('https://dav.example:8443/path'))
expect_invalid(lambda: client.validate_url('https://foreign.example/path'))
expect_invalid(lambda: m.CalDAV('test', 'fake').validate_url('https://evilicloud.com/'))
m.CalDAV('test', 'fake').validate_url('https://p01-caldav.icloud.com/user/')

# Well-known redirects preserve DAV method, body, depth and authentication.
seen = []
replies = [HTTPError(CUSTOM['discovery_url'], 302, 'redirect', {'Location': '/dav/'}, BytesIO()),
           PRINCIPAL, HOME, LIST]
def transport(req, timeout):
    seen.append(req)
    item = replies.pop(0)
    if isinstance(item, Exception):
        raise item
    return response(item)
with patch.object(m, 'urlopen', side_effect=transport):
    assert client.discover() == [('https://dav.example/calendars/alice/work/', 'Work')]
assert [req.full_url for req in seen] == [CUSTOM['discovery_url'], 'https://dav.example/dav/',
                                       'https://dav.example/principals/alice/', 'https://dav.example/calendars/alice/']
assert all(req.get_method() == 'PROPFIND' and req.get_header('Authorization') for req in seen)
assert seen[1].data == seen[0].data and seen[1].get_header('Depth') == '0'
assert seen[-1].get_header('Depth') == '1'

# A supplied home bypasses principal discovery; a direct home works too.
with patch.object(m, 'urlopen', return_value=response(LIST)) as opened:
    home_client = m.CalDAV('test', 'fake', connection=dict(CUSTOM, calendar_home_url='https://dav.example/calendars/alice/'))
    assert home_client.discover()[0][0].endswith('/work/')
    assert opened.call_count == 1
with patch.object(m, 'urlopen', side_effect=[response(multistatus('<d:resourcetype><d:collection/></d:resourcetype>')),
                                           response(LIST)]):
    assert client.discover()[0][0] == 'https://dav.example/.well-known/work/'

# Never forward credentials to an unapproved redirect or discovered host.
redirect = HTTPError(CUSTOM['discovery_url'], 302, 'redirect', {'Location': 'https://foreign.example/'}, BytesIO())
with patch.object(m, 'urlopen', side_effect=redirect) as opened:
    expect_invalid(client.discover)
    assert opened.call_count == 1
with patch.object(m, 'urlopen', return_value=response(multistatus(
        '<d:current-user-principal><d:href>https://foreign.example/p/</d:href></d:current-user-principal>'))) as opened:
    expect_invalid(client.discover)
    assert opened.call_count == 1
trusted_client = m.CalDAV('test', 'fake', connection=dict(CUSTOM, trusted_origins=['https://foreign.example']))
with patch.object(m, 'urlopen', side_effect=[redirect, response(PRINCIPAL), response(HOME), response(LIST)]):
    assert trusted_client.discover()[0][0] == 'https://foreign.example/calendars/alice/work/'
with patch.object(m, 'urlopen', side_effect=HTTPError(CUSTOM['discovery_url'], 307, 'redirect', {'Location': '/loop'}, BytesIO())) as opened:
    expect_invalid(client.discover)
    assert opened.call_count == 6

# Non-iCloud reads and conditional writes use the selected origin policy.
url = 'https://dav.example/calendars/alice/work/'
start = m.datetime(2026, 1, 1, tzinfo=m.timezone.utc)
_, raw = m.new_event_ics('Test', start, start + m.timedelta(hours=1))
inventory = multistatus('<d:getetag>v1</d:getetag>', '/calendars/alice/work/test.ics')
data = multistatus('<d:getetag>v1</d:getetag><c:calendar-data>' + raw + '</c:calendar-data>', '/calendars/alice/work/test.ics')
with patch.object(m, 'urlopen', side_effect=[response(inventory), response(data)]) as opened, \
     patch.object(m, 'get_logger', return_value=Mock()):
    resources = client.events(url, start, start + m.timedelta(days=1))
    assert resources[0]['raw'] == raw.replace('\r\n', '\n')
    assert all(call.args[0].get_method() == 'REPORT' for call in opened.call_args_list)
with patch.object(m, 'urlopen', return_value=response('')) as opened:
    client.put_event(url + 'test.ics', raw, etag='v1')
    assert opened.call_args.args[0].get_header('If-match') == 'v1'
with patch.object(m, 'urlopen', side_effect=HTTPError(url, 307, 'redirect', {'Location': '/other.ics'}, BytesIO())) as opened:
    expect_invalid(lambda: client.put_event(url + 'test.ics', raw, etag='v1'))
    assert opened.call_count == 1
with patch.object(m, 'urlopen') as opened:
    expect_invalid(lambda: client.put_event('https://foreign.example/test.ics', raw, etag='v1'))
    opened.assert_not_called()

# Legacy iCloud cache remains usable, but the same username on another service
# cannot reuse calendar URLs, pins or resource bodies.
legacy = {'username': 'same-user'}
assert m.cache_matches(legacy, {'username': 'same-user'})
assert not m.cache_matches(legacy, dict(CUSTOM, username='same-user'))
assert not m.cache_matches({'username': 'same-user', 'connection': CUSTOM},
                           dict(CUSTOM, username='same-user', discovery_url='https://another.example/'))

print('Service discovery, origin policy, redirects, reads/writes and cache isolation checks passed.')
