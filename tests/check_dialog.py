import importlib.util
import pathlib
import tkinter as tk

source = pathlib.Path(__file__).resolve().parents[1] / 'daynest.py'
spec = importlib.util.spec_from_file_location('daynest', source)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)

root = tk.Tk()
module.apply_theme(root)
root.withdraw()
app = module.App.__new__(module.App)
app.root = root
app.calendars = [('https://caldav.icloud.com/example/', '日历')]
app.desktop_mode = False
app.modal_windows = set()
app.event_form()
root.update()
assert len(app.modal_windows) == 1
dialog = next(iter(app.modal_windows))
assert dialog.winfo_exists()
assert len(dialog.winfo_children()) > 0
def descendants(widget):
    for child in widget.winfo_children():
        yield child
        yield from descendants(child)

next_button = next(child for child in descendants(dialog)
                   if isinstance(child, module.ttk.Button) and child.cget('text') == '›')
next_button.invoke()  # November 2026 requires six calendar rows.
root.update()
save_button = next(child for child in descendants(dialog)
                   if isinstance(child, module.ttk.Button) and child.cget('text') == '保存到日历')
assert save_button.winfo_rooty() + save_button.winfo_height() <= dialog.winfo_rooty() + dialog.winfo_height()
dialog.destroy()
root.update()
assert not app.modal_windows
root.destroy()
