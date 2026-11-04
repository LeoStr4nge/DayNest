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
