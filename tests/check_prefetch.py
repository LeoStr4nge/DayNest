import importlib.util
from pathlib import Path
from datetime import date
import threading

spec = importlib.util.spec_from_file_location('calendar_app', Path(__file__).resolve().parents[1] / 'daynest.py')
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
assert module.shift_month(date(2026, 12, 1), 1) == date(2027, 1, 1)
assert module.shift_month(date(2026, 1, 1), -1) == date(2025, 12, 1)

app = module.App.__new__(module.App)
requested = []
app.load_month = lambda month, **options: requested.append(month)
app.preload_months(date(2026, 10, 30))
assert requested == [date(2026, 10, 1), date(2026, 9, 1), date(2026, 11, 1)]
requested.clear()
app.preload_months(date(2026, 11, 1))
assert date(2026, 12, 1) in requested

center = date.today().replace(day=1)
app.month_cache = {module.shift_month(center, i).strftime('%Y-%m'): {'events': [], 'synced_at': 1}
                   for i in range(-8, 9)}
app.month_generation = 1
app.month_loading = set()
app.calendar_window = None
app.cache_lock = threading.Lock()
app.cache = {}
app.config = {'username': 'test'}
saved = []
module.save_cache = lambda cache: saved.append(dict(cache['months']))
app.month_loaded(center.strftime('%Y-%m'), [], 'test', 1)
expected = {module.shift_month(center, i).strftime('%Y-%m') for i in range(-6, 7)}
assert set(saved[-1]) == expected
assert set(app.month_cache) == expected
app.month_loaded(center.strftime('%Y-%m'), [], 'test', 0)
assert len(saved) == 1
print('Prefetch, year boundaries, retention and stale callback checks passed.')
