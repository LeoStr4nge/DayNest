"""Offline checks for pinned event tracking and authoritative query handling."""
from pathlib import Path
import sys
import threading
from unittest.mock import Mock, patch
import xml.etree.ElementTree as ET

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import daynest as m

URL = 'https://caldav.icloud.com/cal/'
START = m.datetime(2026, 1, 1, 10, tzinfo=m.timezone.utc)


def resource(start='20260101T100000Z', title='Before', extra='', override='', href='old.ics'):
    return {'href': URL + href, 'etag': 'v2', 'raw': (
        'BEGIN:VCALENDAR\r\nVERSION:2.0\r\nBEGIN:VEVENT\r\nUID:pin-test\r\n'
        f'DTSTART:{start}\r\nDURATION:PT1H\r\nSUMMARY:{title}\r\nDESCRIPTION:Notes\r\n'
        f'{extra}END:VEVENT\r\n{override}END:VCALENDAR\r\n')}


def make_pin(res, start=START):
    event = m.parse_events(res['raw'], 'Calendar', start, start + m.timedelta(seconds=1), res, URL)[0]
    return {'key': m.event_key(event), 'title': event[1], 'start': event[0].isoformat(),
            'calendar': event[2], 'href': res['href'], 'event': m.serialize_events([event])[0]}


pin = make_pin(resource())
moved = resource('20270901T120000Z', 'After', href='new.ics')
updated = m.tracked_pin_event(pin, [moved])
assert updated[0].year == 2027 and updated[1] == 'After'
assert updated[4]['href'].endswith('new.ics') and updated[4]['description'] == 'Notes'
assert m.tracked_pin_event(pin, []) is None
assert m.tracked_pin_event(pin, [resource(extra='STATUS:CANCELLED\r\n')]) is None
all_day = resource('20270901', 'All day')
assert m.tracked_pin_event(pin, [all_day])[3]

series = resource(extra='RRULE:FREQ=DAILY;COUNT=3\r\n')
second = START + m.timedelta(days=1)
repeat_pin = make_pin(series, second)
override = ('BEGIN:VEVENT\r\nUID:pin-test\r\nRECURRENCE-ID:20260102T100000Z\r\n'
            'DTSTART:20270901T120000Z\r\nDURATION:PT1H\r\nSUMMARY:Moved instance\r\nEND:VEVENT\r\n')
changed_series = resource(extra='RRULE:FREQ=DAILY;COUNT=3\r\n', override=override)
result = m.tracked_pin_event(repeat_pin, [changed_series])
assert result[1] == 'Moved instance' and result[0].year == 2027
assert m.datetime.fromisoformat(result[4]['recurrence_id']) == second
assert m.tracked_pin_event(repeat_pin, [resource(extra='RRULE:FREQ=DAILY;COUNT=3\r\nEXDATE:20260102T100000Z\r\n')]) is None
cancelled = override.replace('SUMMARY:Moved instance', 'STATUS:CANCELLED\r\nSUMMARY:Moved instance')
assert m.tracked_pin_event(repeat_pin, [resource(extra='RRULE:FREQ=DAILY;COUNT=3\r\n', override=cancelled)]) is None
legacy = make_pin(changed_series, m.datetime(2027, 9, 1, 12, tzinfo=m.timezone.utc))
legacy['event'][4].pop('recurrence_id')
assert m.tracked_pin_event(legacy, [changed_series])[1] == 'Moved instance'

client = m.CalDAV('fake', 'fake')
root = ET.Element('{DAV:}multistatus')
response = ET.SubElement(root, '{DAV:}response')
ET.SubElement(response, '{DAV:}href').text = '/cal/new.ics'
propstat = ET.SubElement(response, '{DAV:}propstat')
ET.SubElement(propstat, '{DAV:}status').text = 'HTTP/1.1 200 OK'
prop = ET.SubElement(propstat, '{DAV:}prop')
ET.SubElement(prop, '{urn:ietf:params:xml:ns:caldav}calendar-data').text = moved['raw']
ET.SubElement(prop, '{DAV:}getetag').text = 'v2'
client.request = Mock(return_value=root)
assert client.pinned_resources(URL, 'pin-test')[0]['raw'] == moved['raw']
query = ET.fromstring(client.request.call_args.args[2])
assert query.find('.//c:text-match', m.NS).text == 'pin-test'
assert query.find('.//c:time-range', m.NS) is None
prop.remove(prop.find('c:calendar-data', m.NS))
try:
    client.pinned_resources(URL, 'pin-test')
except ValueError:
    pass
else:
    raise AssertionError('Incomplete responses must preserve existing pins')

app = m.App.__new__(m.App)
app.config = {'username': 'test'}
app.sync_token = object()
app.pins = [pin]
app.cache = {}
app.cache_lock = threading.Lock()
app.resources = Mock(return_value=Mock(snapshot=Mock(return_value=[])))
app.finish = Mock()
with patch.object(m, 'save_cache'):
    app.apply_sync(object(), 'test', [], [], 0, 0, [(pin, None)])
    assert app.pins == [pin]
    app.apply_sync(app.sync_token, 'other', [], [], 0, 0, [(pin, None)])
    assert app.pins == [pin]
    app.apply_sync(app.sync_token, 'test', [], [], 0, 0, [(pin, updated)])
    assert app.pins[0]['title'] == 'After'
    assert app.cache['pins'] == app.pins
    assert app.pinned_event(app.pins[0])[1] == 'After'
    app.apply_sync(app.sync_token, 'test', [], [], 0, 0, [(pin, None)])
    assert len(app.pins) == 1  # Old snapshot cannot remove a newer pin.
    current = app.pins[0]
    app.apply_sync(app.sync_token, 'test', [], [], 0, 0, [])
    assert app.pins == [current]  # Failed lookups produce no updates.
    app.apply_sync(app.sync_token, 'test', [], [], 0, 0, [(current, None)])
    assert not app.pins and not app.cache['pins']
    app.apply_sync(app.sync_token, 'test', [], [], 0, 0, [(current, updated)])
    assert not app.pins  # Unpinning during a read cannot be undone.
print('Pinned move, deletion, recurrence, legacy identity, protocol and stale-result checks passed.')

# Exercise the real background refresh path: query failure must not fail the
# recent-events sync or remove pins, and multiple instances share one lookup.
import queue
import time
for fail in (False, True):
    worker_app = m.App.__new__(m.App)
    worker_app.config = {'username': 'test', 'password': 'fake'}
    worker_app.cache = {'username': 'test', 'calendars': [(URL, 'Calendar')],
                        'discovered_at': time.time()}
    worker_app.pins = [pin, dict(pin, key='another-pin')]
    worker_app.syncing = worker_app.write_busy = False
    worker_app.closed = threading.Event()
    worker_app.status = Mock()
    worker_app.resources = Mock(return_value=m.ResourceCache())
    posted = queue.Queue()
    worker_app.post = lambda *args: posted.put(args)
    fake = Mock()
    fake.events.return_value = []
    fake.pinned_resources.return_value = [moved]
    if fail:
        fake.pinned_resources.side_effect = OSError('offline')
    with patch.object(m, 'CalDAV', return_value=fake), \
         patch.object(m, 'unprotect', return_value='fake'), \
         patch.object(m, 'get_logger', return_value=Mock()):
        worker_app.refresh()
        result = posted.get(timeout=5)
    assert result[0] == worker_app.apply_sync
    updates = result[-1]
    assert len(updates) == (0 if fail else 2)
    fake.pinned_resources.assert_called_once_with(URL, 'pin-test')
print('Background refresh deduplication and failure preservation checks passed.')
