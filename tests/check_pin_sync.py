"""Offline checks for pinned event tracking and authoritative query handling."""
from pathlib import Path
import sys
from unittest.mock import Mock
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

print('Pinned move, deletion, recurrence, legacy identity and protocol checks passed.')
