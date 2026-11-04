"""No real account or server writes: all crypto, persistence and network are mocked."""
import copy
import json
from datetime import datetime, timedelta
from unittest.mock import Mock, patch
import calendar_bridge as bridge
c = bridge.c
begin = datetime(2026, 11, 4, 9, tzinfo=c.LOCAL_TZ)
uid, raw = c.new_event_ics('Original', begin, begin + timedelta(hours=1), 'line one\nline two')
config = dict(username='test', password='encrypted-password', provider='icloud')
connection = c.connection_config(config)
meta = dict(raw=raw, href='https://caldav.icloud.com/test.ics', etag='"v1"', end=(begin+timedelta(hours=1)).isoformat(), description='line one\nline two')
event = (begin, 'Original', 'Calendar', False, meta)
row = c.serialize_events([event])[0]
token = json.dumps(dict(username='test', connection=connection, event=row))
cache = dict(username='test', events=[row], months={'2026-11': {'events': [row]}},
             pins=[dict(title='Original', start=begin.isoformat(), href=meta['href'], event=row)],
             resource_cache=[dict(href=meta['href'])])
guard = Mock(); guard.acquire.return_value = True
client = Mock()
with patch.object(c, 'SingleInstance', return_value=guard), patch.object(c, 'load_config', return_value=config), \
     patch.object(c, 'load_cache', side_effect=lambda: copy.deepcopy(cache)), patch.object(c, 'save_cache') as saved, \
     patch.object(c, 'CalDAV', return_value=client), patch.object(c, 'unprotect', side_effect=lambda value: token if value == 'token' else 'password'), \
     patch.object(c, 'protect', side_effect=lambda value: value):
    view = bridge.event_view(event, config)
    assert view['editable'] and view['deletable'] and view['notes'] == 'line one\nline two'
    payload = dict(handle='token', title='Edited', notes='new\nnotes', start=begin.isoformat(), end=(begin+timedelta(hours=2)).isoformat())
    assert bridge.mutate_event(payload)['ok']
    args = client.put_event.call_args.args
    assert args[0] == meta['href'] and args[2] == '"v1"' and 'SUMMARY:Edited' in args[1]
    updated = saved.call_args.args[0]
    assert updated['months'] == {} and updated['resource_cache'] == []
    assert updated['pins'][0]['title'] == 'Edited'
    client.reset_mock(); saved.reset_mock()
    for bad in [dict(payload, title=' '), dict(payload, end=begin.isoformat()),
                dict(payload, start='invalid')]:
        try: bridge.mutate_event(bad); raise AssertionError('Invalid edit accepted')
        except ValueError: pass
    client.put_event.assert_not_called()
    try: bridge.mutate_event(dict(handle='token'), delete=True); raise AssertionError('Unconfirmed deletion accepted')
    except ValueError: pass
    client.delete_event.assert_not_called()
    assert bridge.mutate_event(dict(handle='token', confirmed=True), delete=True)['ok']
    client.delete_event.assert_called_once_with(meta['href'], '"v1"')
    assert saved.call_args.args[0]['pins'] == [] and saved.call_args.args[0]['events'] == []
    saved.reset_mock();client.reset_mock()
    with patch.object(c, 'load_config', return_value=dict(config, username='another')):
        try: bridge.mutate_event(payload); raise AssertionError('Stale account token accepted')
        except ValueError: pass
    client.put_event.assert_not_called()
    with patch.object(client, 'delete_event', side_effect=ValueError('conflict')):
        try: bridge.mutate_event(dict(handle='token', confirmed=True), delete=True); raise AssertionError('Conflict ignored')
        except ValueError: pass
        saved.assert_not_called()
    recurring = (begin, 'Recurring', 'Calendar', False, dict(meta, recurring=True))
    assert not bridge.event_view(recurring, config)['deletable']
    all_day = (begin, 'All-day', 'Calendar', True, meta)
    assert not bridge.event_view(all_day, config)['editable'] and bridge.event_view(all_day, config)['deletable']
    with patch.object(c, 'unprotect', side_effect=lambda value: json.dumps(dict(username='test', connection=connection, event=c.serialize_events([recurring])[0])) if value == 'token' else 'password'):
        try: bridge.mutate_event(dict(handle='token', confirmed=True), delete=True); raise AssertionError('Series deletion accepted')
        except ValueError: pass
print('Event edit/delete validation, account binding, confirmation, conflict preservation, cache/pins and recurrence guards passed.')
