import importlib.util
from pathlib import Path
from datetime import datetime, timezone
from concurrent.futures import ThreadPoolExecutor
from tempfile import TemporaryDirectory
import json
from unittest.mock import patch

spec = importlib.util.spec_from_file_location('calendar_app', Path(__file__).resolve().parents[1] / 'daynest.py')
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)

with TemporaryDirectory(dir=Path(__file__).parent) as directory:
    target = Path(directory) / 'config.json'
    m.atomic_write(target, '{"original": true}', 'utf-8')
    with patch.object(Path, 'replace', side_effect=OSError('simulated interruption')):
        try:
            m.atomic_write(target, '{"new": true}', 'utf-8')
        except OSError:
            pass
    assert json.loads(target.read_text()) == {'original': True}
    assert not list(Path(directory).glob('*.tmp'))
    with ThreadPoolExecutor(max_workers=4) as pool:
        list(pool.map(lambda n: m.atomic_write(target, json.dumps({'value': n}), 'utf-8'), range(20)))
    assert isinstance(json.loads(target.read_text())['value'], int)
    assert not list(Path(directory).glob('*.tmp'))
    target.write_text('incomplete {', encoding='utf-8')
    with patch.object(m, 'CONFIG_FILE', target):
        assert m.load_config()['username'] == ''
    stored = {'username': 'test', 'password': 'encrypted-placeholder',
              'theme': 'old-theme', 'opacity': 0.8, 'unknown-option': {'keep': True}}
    target.write_text(json.dumps(stored), encoding='utf-8')
    with patch.object(m, 'CONFIG_FILE', target):
        loaded = m.load_config()
        assert all(loaded[key] == value for key, value in stored.items())
        m.save_config(dict(loaded, username='updated'))
        assert json.loads(target.read_text())['unknown-option'] == {'keep': True}
raw = '\r\n'.join(['BEGIN:VCALENDAR', 'BEGIN:VEVENT', 'UID:repeat', 'DTSTART:20261001T090000Z',
                    'DTEND:20261001T100000Z', 'SUMMARY:例会', 'RRULE:FREQ=DAILY;COUNT=5',
                    'EXDATE:20261002T090000Z', 'EXDATE:20261003T090000Z',
                    'RDATE:20261001T090000Z,20261007T090000Z', 'END:VEVENT',
                    'BEGIN:VEVENT', 'UID:repeat', 'RECURRENCE-ID:20261004T090000Z',
                    'DTSTART:20261004T140000Z', 'DTEND:20261004T150000Z', 'SUMMARY:改期例会', 'END:VEVENT',
                    'BEGIN:VEVENT', 'UID:repeat', 'RECURRENCE-ID:20261005T090000Z',
                    'STATUS:CANCELLED', 'END:VEVENT', 'END:VCALENDAR'])
found = m.parse_events(raw, '个人', datetime(2026, 10, 1, tzinfo=timezone.utc),
                        datetime(2026, 10, 8, tzinfo=timezone.utc))
assert sorted(e[0].astimezone(timezone.utc).strftime('%d %H') for e in found) == ['01 09', '04 14', '07 09']
assert all(datetime.fromisoformat(e[4]['end']) > e[0] for e in found)
timed = '\r\n'.join(['BEGIN:VCALENDAR', 'BEGIN:VEVENT', 'UID:duration',
                      'DTSTART:20261001T230000Z', 'DURATION:PT3H', 'END:VEVENT', 'END:VCALENDAR'])
found = m.parse_events(timed, '个人', datetime(2026, 10, 1, tzinfo=timezone.utc), datetime(2026, 10, 3, tzinfo=timezone.utc))
assert found[0][4]['duration_seconds'] == 3 * 3600

assert m.deserialize_events(m.serialize_events(found)) == found
print('Atomic writes, concurrent persistence, recurrence exceptions and serialization checks passed.')
