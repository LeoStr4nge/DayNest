"""Offline adapter checks; never load the user's config or calendar cache."""
from datetime import datetime
from unittest.mock import patch
import calendar_bridge as bridge

c = bridge.c
config = {'username': 'test', 'provider': 'icloud'}
event = (datetime(2026, 11, 4, 9, tzinfo=c.LOCAL_TZ), '测试日程', '测试日历', False,
         {'end': '2026-11-04T10:00:00+08:00', 'description': '多行\n备注'})
cache = {'username': 'test', 'events': c.serialize_events([event]),
         'pins': [{'title': '重要日期', 'start': '2026-12-01T09:00:00+08:00'}]}

with patch.object(c, 'load_config', return_value=config), patch.object(c, 'load_cache', return_value=cache), \
     patch.object(c, 'CalDAV') as network, patch.object(c, 'save_cache') as save:
    result = bridge.read_month('2026-11')
    assert result['events'][0]['notes'] == '多行\n备注'
    assert result['pins'][0]['title'] == '重要日期'
    network.assert_not_called()
    save.assert_not_called()
    with patch.object(c, 'load_config', return_value=dict(config, username='another-user')):
        result = bridge.read_month('2026-11')
        assert result['events'] == [] and result['pins'] == []
    with patch.object(c, 'load_config', return_value=dict(config, provider='custom', discovery_url='https://example.com/')):
        result = bridge.read_month('2026-11')
        assert result['events'] == [] and result['pins'] == []

print('Bridge cache/pin isolation, notes and read-only behavior passed.')

# Account operations use fake encryption and fake persistence. No personal
# credentials, registry or real config files are read/written by these checks.
from unittest.mock import Mock
guard = Mock()
guard.acquire.return_value = True
saved_config = dict(config, password='encrypted-old', opacity=.8, theme='forest')
with patch.object(c, 'load_config', return_value=saved_config), \
     patch.object(c, 'SingleInstance', return_value=guard), \
     patch.object(c, 'protect', return_value='encrypted-new') as protect, \
     patch.object(c, 'save_config') as save_config, patch.object(c, 'save_cache') as save_cache:
    exposed = bridge.account_settings()
    assert exposed['hasPassword'] is True and 'password' not in exposed
    result = bridge.save_account(dict(provider='icloud', username='test', password=''))
    assert not result['accountChanged']
    assert save_config.call_args.args[0]['password'] == 'encrypted-old'
    assert save_config.call_args.args[0]['theme'] == 'forest'
    protect.assert_not_called()
    save_cache.assert_not_called()
    save_config.reset_mock()
    for payload in [dict(provider='icloud', username='', password=''),
                    dict(provider='icloud', username='different', password=''),
                    dict(provider='custom', username='test', discovery_url='http://example.com', password='secret')]:
        try:
            bridge.save_account(payload)
            raise AssertionError('Invalid account must be rejected')
        except ValueError:
            pass
        save_config.assert_not_called()
    result = bridge.save_account(dict(provider='custom', username='test', password='new-secret', discovery_url='https://example.com/'))
    assert result['accountChanged']
    assert save_config.call_args.args[0]['password'] == 'encrypted-new'
    assert save_config.call_args.args[0]['opacity'] == .8
    assert save_cache.call_args.args[0]['pins'] == []
    guard.close.assert_called()
    with patch.object(c, 'save_cache', side_effect=OSError('simulated disk failure')):
        committed = bridge.save_account(dict(provider='icloud', username='new-user', password='new-secret'))
        assert committed['ok'] and committed['accountChanged'] and not committed['cacheReset']
    save_config.reset_mock()
    guard.acquire.return_value = False
    try:
        bridge.save_account(dict(provider='icloud', username='test', password='new-secret'))
        raise AssertionError('Running original app must prevent config writes')
    except ValueError:
        pass
    save_config.assert_not_called()
print('Account validation, encrypted password handling, cache reset, settings isolation and write guard passed.')
