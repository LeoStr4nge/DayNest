"""Full pin tracking through the bridge, using fake crypto, disk and CalDAV."""
import copy
from datetime import datetime, timedelta, timezone
from unittest.mock import Mock, patch
import calendar_bridge as b
c = b.c
url = 'https://caldav.icloud.com/cal/'
start = datetime(2026, 1, 1, 10, tzinfo=timezone.utc)


def resource(when='20260101T100000Z', title='Before', extra='', override='', href='old.ics'):
    return dict(href=url + href, etag='v2', raw=(
        'BEGIN:VCALENDAR\r\nVERSION:2.0\r\nBEGIN:VEVENT\r\nUID:pin-test\r\n'
        f'DTSTART:{when}\r\nDURATION:PT1H\r\nSUMMARY:{title}\r\nDESCRIPTION:Full notes\\nsecond line\r\n'
        f'{extra}END:VEVENT\r\n{override}END:VCALENDAR\r\n'))


def pin_from(res, at=start):
    event = c.parse_events(res['raw'], 'Calendar', at, at + timedelta(seconds=1), res, url)[0]
    return dict(key=c.event_key(event), title=event[1], start=event[0].isoformat(),
                calendar=event[2], href=res['href'], event=c.serialize_events([event])[0])


pin = pin_from(resource())
config = dict(username='test', password='fake', provider='icloud')
cache = dict(username='test', pins=[pin])
client = Mock()
moved = resource('20270901T120000Z', 'After', href='new.ics')
client.pinned_resources.return_value = [moved]
changed, failures = b.track_pins(cache, client)
assert not failures and changed[0]['title'] == 'After' and changed[0]['start'].startswith('2027-09')
assert changed[0]['href'].endswith('new.ics') and changed[0]['event'][4]['description'] == 'Full notes\nsecond line'
with patch.object(c, 'protect', side_effect=lambda value: value):
    view = b.pin_views(dict(cache, pins=changed), config)[0]
    assert view['event']['editable'] and view['notes'] == 'Full notes\nsecond line'
    assert view['event']['key'] == view['key']
for resources in [[], [resource(extra='STATUS:CANCELLED\r\n')]]:
    client.pinned_resources.return_value = resources
    assert b.track_pins(cache, client) == ([], 0)
client.pinned_resources.side_effect = OSError('offline')
preserved, errors = b.track_pins(cache, client)
assert preserved == [pin] and errors == 1
client.pinned_resources.side_effect = None
client.pinned_resources.return_value = [moved]
client.reset_mock()
b.track_pins(dict(cache, pins=[pin, dict(pin, key='same-resource-other-pin')]), client)
client.pinned_resources.assert_called_once_with(url, 'pin-test')
series = resource(extra='RRULE:FREQ=DAILY;COUNT=3\r\n')
second = start + timedelta(days=1)
repeat = pin_from(series, second)
override = ('BEGIN:VEVENT\r\nUID:pin-test\r\nRECURRENCE-ID:20260102T100000Z\r\n'
            'DTSTART:20270901T120000Z\r\nDURATION:PT1H\r\nSUMMARY:Moved instance\r\nEND:VEVENT\r\n')
client.pinned_resources.return_value = [resource(extra='RRULE:FREQ=DAILY;COUNT=3\r\n', override=override)]
result, errors = b.track_pins(dict(cache, pins=[repeat]), client)
assert not errors and result[0]['title'] == 'Moved instance' and result[0]['event'][4]['recurrence_id'] == second.isoformat()
client.pinned_resources.return_value = [resource(extra='RRULE:FREQ=DAILY;COUNT=3\r\nEXDATE:20260102T100000Z\r\n')]
assert b.track_pins(dict(cache, pins=[repeat]), client) == ([], 0)
legacy = {k: v for k, v in pin.items() if k != 'event'}
client.pinned_resources.return_value = [moved]
assert b.track_pins(dict(cache, pins=[legacy], events=[pin['event']]), client)[0][0]['title'] == 'After'
with patch.object(c, 'protect', side_effect=lambda value: value):
    fallback = b.pin_views(dict(cache, pins=[dict(title='Legacy', start=start.isoformat())]), config)[0]
    assert fallback['event']['title'] == 'Legacy' and not fallback['event']['editable']
# Exercise the real month refresh/commit, and the no-tracking prefetch path.
guard = Mock(); guard.acquire.return_value = True
client.events.return_value = []
client.discover.return_value = [(url, 'Calendar')]
state = copy.deepcopy(cache)
with patch.object(c, 'load_config', return_value=config), patch.object(c, 'load_cache', side_effect=lambda: copy.deepcopy(state)), \
     patch.object(c, 'save_cache') as save, patch.object(c, 'SingleInstance', return_value=guard), \
     patch.object(c, 'CalDAV', return_value=client), patch.object(c, 'unprotect', side_effect=lambda value: value), \
     patch.object(c, 'protect', side_effect=lambda value: value):
    result = b.read_month('2026-11', refresh=True)
    assert result['pins'][0]['title'] == 'After' and save.call_args.args[0]['pins'][0]['title'] == 'After'
    client.reset_mock()
    b.read_month('2026-11', refresh=True, sync_pins=False)
    client.pinned_resources.assert_not_called()
    client.pinned_resources.side_effect = OSError('offline')
    result = b.read_month('2026-11', refresh=True)
    assert result['warning'] and result['pins'][0]['title'] == 'Before'
    assert save.call_args.args[0]['pins'] == [pin]
print('PASS: pin moves across months, notes/details, authoritative deletion/cancellation, recurrence identity, legacy pins, query deduplication, failure retention and prefetch exclusion.')
