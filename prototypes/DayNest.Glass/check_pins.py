"""Fixed countdown persistence checks; no personal files or network are used."""
import copy
from datetime import datetime, timedelta
from unittest.mock import Mock, patch
import calendar_bridge as bridge
c = bridge.c
config = dict(username='test', provider='icloud')
begin = datetime(2026, 11, 6, 9, tzinfo=c.LOCAL_TZ)
_, raw = c.new_event_ics('Deadline', begin, begin + timedelta(hours=1), 'Notes')
event = (begin, 'Deadline', 'Test', False, dict(raw=raw, href='https://caldav.icloud.com/event.ics', etag='v1'))
state = dict(username='test', events=c.serialize_events([event]), pins=[])
guard = Mock(); guard.acquire.return_value = True
def save(value):
    state.clear(); state.update(copy.deepcopy(value))

with patch.object(c, 'load_config', return_value=config), \
     patch.object(c, 'load_cache', side_effect=lambda: copy.deepcopy(state)), \
     patch.object(c, 'save_cache', side_effect=save) as saved, \
     patch.object(c, 'SingleInstance', return_value=guard), \
     patch.object(c, 'protect', side_effect=lambda value: value), \
     patch.object(c, 'unprotect', side_effect=lambda value: value), patch.object(c, 'CalDAV') as network:
    entry = bridge.event_view(event, config)
    payload = dict(handle=entry['pinHandle'])
    added = bridge.set_pin(payload)
    assert len(added['pins']) == 1 and len(state['pins']) == 1
    assert state['pins'][0]['event'] == list(c.serialize_events([event])[0])
    assert state['events'] == c.serialize_events([event])
    bridge.set_pin(payload)
    assert len(state['pins']) == 1, 'Repeated pinning must be idempotent'
    assert bridge.read_month('2026-11')['pins'][0]['key'] == added['pins'][0]['key']
    state['pins'].append(dict(title='Other', start=begin.isoformat(), key='other'))
    bridge.set_pin(dict(handle=added['pins'][0]['actionHandle']), remove=True)
    assert [p['key'] for p in state['pins']] == ['other']
    assert state['events'] == c.serialize_events([event]), 'Unpin must not delete the event'
    state['pins'] = [dict(title='Legacy', start=begin.isoformat())]
    legacy = bridge.pin_views(state, config)[0]
    bridge.set_pin(dict(handle=legacy['actionHandle']), remove=True)
    assert state['pins'] == []
    recurring = (*event[:4], dict(event[4], recurring=True))
    recurring_view = bridge.event_view(recurring, config)
    assert not recurring_view['deletable'] and recurring_view['pinHandle']
    saved.reset_mock()
    with patch.object(c, 'load_config', return_value=dict(config, username='other-account')):
        try: bridge.set_pin(payload); raise AssertionError('Cross-account pin accepted')
        except ValueError: pass
    try: bridge.set_pin(dict(handle=legacy['actionHandle'])); raise AssertionError('Wrong token purpose accepted')
    except ValueError: pass
    guard.acquire.return_value = False
    try: bridge.set_pin(payload); raise AssertionError('Original-app write conflict accepted')
    except ValueError: pass
    saved.assert_not_called()
    network.assert_not_called()
print('Pin add/reload, deduplication, selected/legacy removal, recurrence, account isolation and no-server-write checks passed.')
