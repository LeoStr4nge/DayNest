"""Check opacity preview, cancel, save, restart and settings layout in Tk."""
from pathlib import Path
import sys
import tempfile
from unittest.mock import patch, Mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import daynest as m

for invalid in (None, 'invalid', float('nan'), float('inf'), 0, -1, 2, {}):
    assert m.normalized_opacity(invalid) == 1.0
assert m.normalized_opacity('0.6') == 0.6


def descendants(widget):
    for child in widget.winfo_children():
        yield child
        yield from descendants(child)


with tempfile.TemporaryDirectory(dir=Path(__file__).parent) as directory, \
     patch.object(m, 'CONFIG_FILE', Path(directory) / 'config.json'), \
     patch.object(m, 'load_cache', return_value={}), \
     patch.object(m, 'save_cache'), \
     patch.object(m.App, 'refresh'), \
     patch.object(m.App, 'set_autostart'), \
     patch.object(m, 'get_logger', return_value=Mock()):
    assert m.load_config()['opacity'] == 1.0
    m.CONFIG_FILE.write_text('{"opacity": "invalid"}', encoding='utf-8')
    assert m.load_config()['opacity'] == 1.0
    m.save_config({'username': 'test', 'password': 'fake', 'desktop': False, 'opacity': 0.8})
    app = m.App()
    try:
        app.root.update()
        assert abs(app.root.attributes('-alpha') - 0.8) < 0.01
        app.settings()
        app.root.update()
        dialog = next(iter(app.modal_windows))
        assert dialog.attributes('-alpha') == 1.0
        slider = next(w for w in descendants(dialog) if isinstance(w, m.ttk.Scale))
        slider.set(60)
        app.root.update()
        assert abs(app.root.attributes('-alpha') - 0.4) < 0.01
        assert app.config['opacity'] == 0.8  # Preview must not mutate config.
        button = next(w for w in descendants(dialog)
                      if isinstance(w, m.ttk.Button) and w.cget('text') == '保存并同步')
        assert button.winfo_rooty() + button.winfo_height() <= dialog.winfo_rooty() + dialog.winfo_height()
        dialog.destroy()
        app.root.update()
        assert abs(app.root.attributes('-alpha') - 0.8) < 0.01
        assert m.load_config()['opacity'] == 0.8
        app.settings()
        app.root.update()
        dialog = next(iter(app.modal_windows))
        slider = next(w for w in descendants(dialog) if isinstance(w, m.ttk.Scale))
        slider.set(35)
        next(w for w in descendants(dialog)
             if isinstance(w, m.ttk.Button) and w.cget('text') == '保存并同步').invoke()
        app.root.update()
        assert not app.modal_windows
        assert abs(app.root.attributes('-alpha') - 0.65) < 0.01
        assert m.load_config()['opacity'] == 0.65
    finally:
        for callback in app.root.tk.call('after', 'info'):
            app.root.after_cancel(callback)
        app.close()
    restarted = m.App()
    try:
        restarted.root.update()
        assert abs(restarted.root.attributes('-alpha') - 0.65) < 0.01
    finally:
        for callback in restarted.root.tk.call('after', 'info'):
            restarted.root.after_cancel(callback)
        restarted.close()
print('Opacity startup, preview, cancel, persistence, dialog isolation and layout checks passed.')
