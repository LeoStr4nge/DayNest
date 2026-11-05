import importlib.util
from pathlib import Path
from datetime import datetime, timedelta

spec = importlib.util.spec_from_file_location('calendar_app', Path(__file__).resolve().parents[1] / 'daynest.py')
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)
start = datetime.now(m.LOCAL_TZ).replace(hour=17, minute=0, second=0, microsecond=0)
description = '第一行：准备资料；带上纸笔。\n' + '这是一条需要完整展示的很长的中文备注，' * 15 + '\n字面量 \\n 不应变成换行'
raw = m.fold_ics_lines(['BEGIN:VCALENDAR', 'VERSION:2.0', 'BEGIN:VEVENT', 'UID:test-notes',
                       'DTSTART:' + m.ics_time(start), 'DTEND:' + m.ics_time(start + timedelta(hours=1)),
                       'SUMMARY:测试备注', 'DESCRIPTION:' + m.escape_ics_text(description),
                       'BEGIN:VALARM', 'DESCRIPTION:提醒文字，不是日程备注', 'END:VALARM',
                       'END:VEVENT', 'END:VCALENDAR'])
events = m.parse_events(raw, '个人', start - timedelta(days=1), start + timedelta(days=1),
                        {'href': 'https://caldav.icloud.com/test.ics', 'etag': 'v1'})
event = events[0]
assert m.event_notes(event) == description
edited = m.edit_event_ics(raw, '修改标题', start, start + timedelta(hours=2))
assert m.parse_events(edited, '个人', start - timedelta(days=1), start + timedelta(days=1))[0][4]['description'] == description
for value in ('修改后的备注\n第二行，包含分号；和反斜杠\\', ''):
    edited = m.edit_event_ics(raw, '修改标题', start, start + timedelta(hours=2), value)
    parsed = m.parse_events(edited, '个人', start - timedelta(days=1), start + timedelta(days=1))[0]
    assert m.event_notes(parsed) == value
    assert 'DESCRIPTION:提醒文字，不是日程备注' in edited
    _, created = m.new_event_ics('新日程', start, start + timedelta(hours=1), value)
    assert m.event_notes(m.parse_events(created, '个人', start - timedelta(days=1), start + timedelta(days=1))[0]) == value

print('Notes parsing, escaping, editing and creation checks passed.')
