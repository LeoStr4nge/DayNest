"""Theme preview must preserve live data, edit contents and widget state."""
from pathlib import Path
import sys
import tempfile
from unittest.mock import Mock, patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import daynest as m


def descendants(widget):
    for child in widget.winfo_children():
        yield child
        yield from descendants(child)


def close(app):
    for callback in app.root.tk.call('after', 'info'):
        app.root.after_cancel(callback)
    app.close()


for theme in m.THEMES:
    for color in ('#000000', '#ffffff', '#ff0000'):
        palette = m.theme_palette(theme, color)
        light, dark = sorted((m.color_luminance(palette['ACCENT_INK']),
                              m.color_luminance(palette['BG'])), reverse=True)
        assert (light + 0.05) / (dark + 0.05) >= 4.5
        assert palette['ACCENT'] == color


with tempfile.TemporaryDirectory(dir=Path(__file__).parent) as directory, \
     patch.object(m, 'CONFIG_FILE', Path(directory) / 'config.json'), \
     patch.object(m, 'load_cache', return_value={}), patch.object(m, 'save_cache'), \
     patch.object(m.App, 'refresh'), patch.object(m.App, 'set_autostart'), \
     patch.object(m.App, 'load_month'), patch.object(m, 'get_logger', return_value=Mock()):
    m.CONFIG_FILE.write_text('{"theme": [], "accent": "invalid"}', encoding='utf-8')
    assert m.load_config()['theme'] == 'midnight' and m.load_config()['accent'] is None
    m.save_config({'username': 'test', 'password': 'fake', 'desktop': False})
    app = m.App()
    try:
        app.root.update()
        app.calendars = [('https://caldav.icloud.com/test/', 'Test')]
        app.open_calendar()
        app.event_form()
        edit = next(w for w in app.modal_windows if w is not app.calendar_window)
        notes = next(w for w in descendants(edit) if isinstance(w, m.tk.Text))
        notes.insert('1.0', 'Keep unsaved notes')
        app.settings()
        app.root.update()
        settings = next(w for w in app.modal_windows if w not in (edit, app.calendar_window))
        chooser = next(w for w in descendants(settings) if isinstance(w, m.ttk.Combobox))
        initial_images = tuple(map(str, app.root.opacity_style_images))
        initial_image_count = len(app.root.tk.call('image', 'names'))
        listbox = app.listbox
        for theme in m.THEMES:
            chooser.current(list(m.THEMES).index(theme))
            chooser.event_generate('<<ComboboxSelected>>')
            app.root.update()
            palette = m.theme_palette(theme)
            assert app.root.cget('background') == palette['BG']
            assert app.listbox.cget('foreground') == palette['TEXT']
            assert notes.cget('background') == palette['CARD']
            assert notes.get('1.0', 'end-1c') == 'Keep unsaved notes'
            assert listbox is app.listbox
            assert tuple(map(str, app.root.opacity_style_images)) == initial_images
        assert len(app.root.tk.call('image', 'names')) == initial_image_count
        # The custom color picker returns a value without opening a native dialog.
        custom = next(w for w in descendants(settings) if isinstance(w, m.tk.Button)
                      and str(w.cget('text')).strip().startswith('#'))
        with patch.object(m.colorchooser, 'askcolor', return_value=((18, 52, 86), '#123456')):
            custom.invoke()
        app.root.update()
        assert m.ACCENT == '#123456'
        assert m.ttk.Style(app.root).lookup('Accent.TButton', 'foreground') == '#ffffff'
        assert app.config.get('theme', 'midnight') == 'midnight'
        settings.destroy()
        app.root.update()
        assert app.root.cget('background') == m.THEMES['midnight'][1]
        assert notes.get('1.0', 'end-1c') == 'Keep unsaved notes'
        edit.destroy()
        app.calendar_window.destroy()
        app.root.update()
        app.config.update(username='', password='')
        app.settings()
        app.root.update()
        settings = next(iter(app.modal_windows))
        chooser = next(w for w in descendants(settings) if isinstance(w, m.ttk.Combobox))
        chooser.current(list(m.THEMES).index('paper'))
        chooser.event_generate('<<ComboboxSelected>>')
        with patch.object(m.colorchooser, 'askcolor', return_value=(None, '#7c3aed')):
            next(w for w in descendants(settings) if isinstance(w, m.tk.Button)
                 and str(w.cget('text')).strip().startswith('#')).invoke()
        save = next(w for w in descendants(settings) if isinstance(w, m.ttk.Button)
                    and w.cget('text') == '保存外观')
        app.root.update()
        assert save.winfo_rooty() + save.winfo_height() <= settings.winfo_rooty() + settings.winfo_height()
        save.invoke()
        app.root.update()
        assert not app.modal_windows
        assert m.load_config()['theme'] == 'paper'
        assert m.load_config()['accent'] == '#7c3aed'
    finally:
        close(app)
    restarted = m.App()
    try:
        restarted.root.update()
        assert restarted.root.cget('background') == m.THEMES['paper'][1]
        assert m.ACCENT == '#7c3aed'
        # Controls created later must use the active palette, not old defaults.
        button = m.flat_button(restarted.root, 'test', lambda: None)
        assert button.rest_bg == m.CARD
        scrollbar = m.SlimScrollbar(restarted.root, lambda *_: None)
        assert scrollbar.cget('background') == m.BG
    finally:
        close(restarted)
print('Theme presets, live dialogs, unsaved notes, custom colors, image reuse, cancel and persistence checks passed.')
