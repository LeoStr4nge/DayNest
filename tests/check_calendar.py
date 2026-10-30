import importlib.util
import pathlib
import threading
import time
import tkinter as tk
from datetime import date, datetime, timedelta

source = pathlib.Path(__file__).resolve().parents[1] / 'daynest.py'
spec = importlib.util.spec_from_file_location('daynest', source)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)

today = date.today()
start = datetime.combine(today, datetime.min.time(), module.LOCAL_TZ) + timedelta(hours=17)
event = (start, '测试日程', '日历', False,
         {'href': 'https://caldav.icloud.com/test.ics', 'duration_seconds': 3600})
assert module.events_on_day([event], today) == [event]
assert module.events_on_day([event], today + timedelta(days=1)) == []
assert module.deserialize_events(module.serialize_events([event])) == [event]

root = tk.Tk()
module.apply_theme(root)
root.withdraw()
app = module.App.__new__(module.App)
app.root = root
app.desktop_mode = False
app.modal_windows = set()
app.config = {}
app.calendars = []
app.pins = []
app.month_loading = set()
app.month_generation = 0
app.cache_lock = threading.Lock()
app.cache = {}
app.month_cache = {today.strftime('%Y-%m'): {'events': module.serialize_events([event]),
                                                'synced_at': time.time()}}
app.pins_frame = tk.Frame(root)
app.pins_frame.pack()
app.save_pins = lambda: None
app.open_calendar()
root.update()
assert len(app.modal_windows) == 1
assert app.calendar_window.winfo_exists()
original_buttons = [cell['button'].winfo_id() for cell in app.calendar_cells]
original_details = [child.winfo_id() for child in app.calendar_details.winfo_children()]
app.select_calendar_day(today)
root.update()
assert original_details == [child.winfo_id() for child in app.calendar_details.winfo_children()]
other_day = today.replace(day=1 if today.day != 1 else 2)
app.select_calendar_day(other_day)
root.update()
assert original_buttons == [cell['button'].winfo_id() for cell in app.calendar_cells]
assert app.calendar_day_cells[other_day]['button'].rest_bg == module.SELECTED
assert app.calendar_day_cells[today]['button'].rest_bg == module.CARD
app.select_calendar_day(today)
root.update()
original_details = [child.winfo_id() for child in app.calendar_details.winfo_children()]
pin_button = app.calendar_pin_buttons[module.event_key(event)]
app.pin_from_calendar(event)
root.update()
assert len(app.pins) == 1
assert app.pins[0]['title'] == '测试日程'
assert app.pins_frame.winfo_children()
assert app.calendar_pin_buttons[module.event_key(event)] is pin_button
assert pin_button.cget('text') == '取消固定'
app.draw_calendar()  # A background refresh with identical data keeps the cards.
root.update()
assert original_details == [child.winfo_id() for child in app.calendar_details.winfo_children()]
assert original_buttons == [cell['button'].winfo_id() for cell in app.calendar_cells]
app.change_calendar_month(1)
root.update()
assert original_buttons == [cell['button'].winfo_id() for cell in app.calendar_cells]
app.remove_pin(module.event_key(event))
assert not app.pins
app.calendar_window.destroy()
root.update()
assert not app.modal_windows
assert app.calendar_window is None
root.destroy()
