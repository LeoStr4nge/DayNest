"""Offline month persistence/create checks. Never reads personal files or servers."""
import copy
import json
import tempfile
import uuid
from datetime import date, datetime, timedelta
from pathlib import Path
from unittest.mock import Mock, patch
import calendar_bridge as bridge

c = bridge.c
config = dict(username='test', password='encrypted', provider='icloud')
connection = c.connection_config(config)
month = date.today().replace(day=1)
key = month.strftime('%Y-%m')
neighbor = c.shift_month(month, 1).strftime('%Y-%m')
begin = datetime.combine(month, datetime.min.time(), c.LOCAL_TZ) + timedelta(days=3, hours=9)
uid, raw = c.new_event_ics('Server event', begin, begin + timedelta(hours=1), 'line one\nline two')
url = 'https://caldav.icloud.com/test/'
resource = dict(href=url + uid + '.ics', etag='"v1"', raw=raw)
guard = Mock(); guard.acquire.return_value = True
puts = {}
calls = []
fail = False


class FakeClient:
    def __init__(self, username, password, resources=None, **kwargs):
        self.resources = resources

    def discover(self):
        calls.append('discover')
        return [(url, 'Calendar')]

    def events(self, calendar_url, start, end):
        calls.append(start.strftime('%Y-%m'))
        if fail: raise ValueError('offline')
        found = [resource] if start <= begin < end else []
        self.resources.store(calendar_url, found, start, end)
        return found

    def put_event(self, href, content, etag=None, create=False):
        assert create is True and etag is None
        if href in puts: raise ValueError('already exists')
        puts[href] = content


with tempfile.TemporaryDirectory(prefix='daynest-sync-check-') as folder, \
     patch.object(c, 'CACHE_FILE', Path(folder) / 'cache.dat'), \
     patch.object(c, 'load_config', side_effect=lambda: dict(config)), \
     patch.object(c, 'protect', side_effect=lambda value: value), \
     patch.object(c, 'unprotect', side_effect=lambda value: value), \
     patch.object(c, 'CalDAV', FakeClient), patch.object(c, 'SingleInstance', return_value=guard):
    # Real cache serialization and atomic file IO in an isolated temporary folder.
    original = dict(username='test', connection=connection, months={neighbor: dict(events=[], synced_at=1)},
                    pins=[dict(title='Pinned', start=begin.isoformat())])
    c.save_cache(original)
    empty = bridge.read_month(key)
    assert not empty['hasCache'] and empty['configured'] and not calls
    loaded = bridge.read_month(key, refresh=True)
    assert loaded['hasCache'] and loaded['syncedAt'] > 0 and loaded['events'][0]['notes'] == 'line one\nline two'
    disk = c.load_cache()
    assert disk['months'][key]['events'] and neighbor in disk['months'] and disk['pins'] == original['pins']
    assert disk['resource_cache'][0]['etag'] == '"v1"' and disk['calendars'] == [[url, 'Calendar']]
    calls.clear()
    restarted = bridge.read_month(key)
    assert restarted['events'] == loaded['events'] and restarted['syncedAt'] == loaded['syncedAt'] and not calls
    # Empty server result is complete data, distinct from a month never loaded.
    bridge.read_month(neighbor, refresh=True)
    assert bridge.read_month(neighbor)['hasCache'] and bridge.read_month(neighbor)['events'] == []
    assert 'discover' not in calls, 'Reuse discovery cache on adjacent months'
    snapshot = (Path(folder) / 'cache.dat').read_bytes()
    fail = True
    try: bridge.read_month(key, refresh=True); raise AssertionError('Offline refresh reported success')
    except ValueError: pass
    assert (Path(folder) / 'cache.dat').read_bytes() == snapshot, 'Failure must preserve disk cache'
    assert bridge.read_month(key)['events'] == loaded['events']
    fail = False
    # Partial success across calendars must never commit a partial replacement.
    disk = c.load_cache(); disk['calendars'].append([url + 'other/', 'Other']); c.save_cache(disk)
    snapshot = (Path(folder) / 'cache.dat').read_bytes()
    original_events = FakeClient.events
    def partial(self, calendar_url, start, end):
        if calendar_url.endswith('other/'): raise ValueError('one calendar failed')
        return original_events(self, calendar_url, start, end)
    with patch.object(FakeClient, 'events', partial):
        try: bridge.read_month(key, refresh=True); raise AssertionError('Partial refresh accepted')
        except ValueError: pass
    assert (Path(folder) / 'cache.dat').read_bytes() == snapshot
    with patch.object(c, 'save_cache', side_effect=OSError('disk full')):
        fresh = bridge.read_month(key, refresh=True)
        assert fresh['hasCache'] and fresh['warning']
    # Far-away data is returned, but does not grow the persistent month window.
    far = c.shift_month(month, 20).strftime('%Y-%m')
    assert bridge.read_month(far, refresh=True)['hasCache']
    assert far not in c.load_cache()['months']
    # Account and service isolation also applies to automatic reads.
    for changed in [dict(config, username='other'), dict(config, provider='custom', discovery_url='https://example.com/')]:
        with patch.object(c, 'load_config', return_value=changed):
            isolated = bridge.read_month(key)
            assert not isolated['hasCache'] and isolated['events'] == [] and isolated['pins'] == []
    choices = bridge.calendar_choices()['calendars']
    assert choices[0]['name'] == 'Calendar' and json.loads(choices[0]['handle'])['purpose'] == 'create-calendar'
    payload = dict(handle=choices[0]['handle'], requestId=str(uuid.uuid4()), title='New event', notes='new\nnotes',
                   start=begin.isoformat(), end=(begin + timedelta(hours=2)).isoformat())
    assert bridge.create_event(payload)['ok'] and len(puts) == 1
    created_raw = next(iter(puts.values()))
    assert 'UID:' + payload['requestId'] in created_raw and 'SUMMARY:New event' in created_raw
    created = c.load_cache()
    assert created['months'] == {} and created['pins'] == original['pins']
    assert any(row[1] == 'New event' for row in created['events'])
    try: bridge.create_event(payload); raise AssertionError('Retry duplicated event')
    except ValueError: pass
    assert len(puts) == 1
    for bad in [dict(payload, title=' '), dict(payload, end=begin.isoformat()),
                dict(payload, start='invalid'), dict(payload, requestId='../bad')]:
        try: bridge.create_event(bad); raise AssertionError('Invalid creation accepted')
        except ValueError: pass
    with patch.object(c, 'load_config', return_value=dict(config, username='changed')):
        try: bridge.create_event(payload); raise AssertionError('Cross-account calendar token accepted')
        except ValueError: pass
    guard.acquire.return_value = False
    for operation in [lambda: bridge.read_month(key, refresh=True), lambda: bridge.create_event(payload)]:
        try: operation(); raise AssertionError('Write conflict accepted')
        except ValueError: pass
    assert len(puts) == 1
    guard.acquire.return_value = True
    with patch.object(c, 'save_cache', side_effect=OSError('disk full')):
        outcome = bridge.create_event(dict(payload, requestId=str(uuid.uuid4())))
        assert outcome['ok'] and outcome['warning'], 'A committed server write must not look like failed creation'

print('PASS: month restart/offline/partial-error persistence, resource/discovery reuse, account isolation, retention, creation, retry deduplication and write guards.')
