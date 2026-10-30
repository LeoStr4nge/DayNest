import importlib.util
from pathlib import Path
import tkinter as tk
from types import SimpleNamespace

spec = importlib.util.spec_from_file_location('calendar_app', Path(__file__).resolve().parents[1] / 'daynest.py')
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)
root = tk.Tk()
root.geometry('360x240')
text = tk.Text(root, height=5, wrap='word')
bar = m.SlimScrollbar(root, text.yview)
bar.pack(side='right', fill='y')
text.pack(fill='both', expand=True)
text.configure(yscrollcommand=bar.set)
m.enable_wheel(text, root)
text.insert('1.0', '短备注')
root.update()
assert not bar.find_withtag('thumb')
text.insert('end', '\n' + '\n'.join(str(i) for i in range(100)))
root.update()
assert len(bar.find_withtag('thumb')) == 1
assert bar.winfo_width() == 10
text.event_generate('<MouseWheel>', delta=-120)
root.update()
assert text.yview()[0] > 0
bar.press(SimpleNamespace(y=bar.winfo_height() // 2))
root.update()
assert 0.2 < text.yview()[0] < 0.8
text.delete('1.0', 'end')
root.update()
assert not bar.find_withtag('thumb')
root.destroy()
print('Scrollbar fit, overflow, wheel and track-click checks passed.')
