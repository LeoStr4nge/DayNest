"""Month arithmetic and persisted cache retention shared by the WinUI bridge."""
from pathlib import Path
from datetime import date
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import daynest as backend

assert backend.shift_month(date(2026, 12, 1), 1) == date(2027, 1, 1)
assert backend.shift_month(date(2026, 1, 1), -1) == date(2025, 12, 1)
center = date(2026, 1, 1)
months = {backend.shift_month(center, i).strftime('%Y-%m'): {'events': [], 'synced_at': 1}
          for i in range(-8, 9)}
kept = backend.persistent_months(months, today=center)
expected = {backend.shift_month(center, i).strftime('%Y-%m') for i in range(-6, 7)}
assert set(kept) == expected
assert len(months) == 17, 'Filtering must not mutate the in-memory cache'
print('Year boundaries and persisted month retention checks passed.')
