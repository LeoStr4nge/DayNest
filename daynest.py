import base64
import calendar as calendar_module
from collections import OrderedDict
from concurrent.futures import CancelledError
import ctypes
from ctypes import wintypes
from datetime import date, datetime, timedelta, timezone
import json
from itertools import count
import logging
from logging.handlers import RotatingFileHandler
import os
import re
import queue
import ssl
import tempfile
from http.client import IncompleteRead, RemoteDisconnected
from pathlib import Path
import threading
import time
import tkinter as tk
import tkinter.font as tkfont
from tkinter import colorchooser, messagebox, ttk
import uuid
import winreg
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError
from urllib.parse import urljoin, urlparse
import xml.etree.ElementTree as ET

from dateutil.rrule import rrulestr, rruleset
from dateutil.tz import gettz


APP_NAME = 'DayNest'
APP_VERSION = '1.0.0'
APP_DIR = Path(os.getenv('APPDATA', Path.home())) / APP_NAME
CONFIG_FILE = APP_DIR / 'config.json'
LOG_FILE = APP_DIR / 'sync.log'
CACHE_FILE = APP_DIR / 'cache.dat'
NS = {'d': 'DAV:', 'c': 'urn:ietf:params:xml:ns:caldav'}
LOCAL_TZ = datetime.now().astimezone().tzinfo
BG = '#101923'
CARD = '#1a2836'
HOVER = '#273c4e'
TEXT = '#e8eff7'
MUTED = '#93a6b9'
ACCENT = '#84d0ff'
FILE_WRITE_LOCK = threading.Lock()


THEMES = {
    'midnight': ('午夜蓝', '#101923', '#1a2836', '#273c4e', '#e8eff7', '#93a6b9', '#84d0ff'),
    'forest': ('松林绿', '#111e1b', '#1b302a', '#29473c', '#e7f2ec', '#99b8a9', '#8cdbb4'),
    'plum': ('暮光紫', '#1b1726', '#2b243b', '#413553', '#eee9f7', '#b0a0c3', '#c8adff'),
    'rose': ('暖玫瑰', '#23191e', '#35262e', '#503a46', '#f6e9ee', '#c3a0af', '#f2adc7'),
    'paper': ('云雾白', '#f3f5f8', '#ffffff', '#e1e7ef', '#263445', '#65768a', '#326ca8'),
    'sand': ('暖砂米', '#f5f0e7', '#fffcf5', '#e8ddcc', '#463c30', '#83735e', '#94612d'),
}
COLOR_ROLES = ('BG', 'CARD', 'HOVER', 'TEXT', 'MUTED', 'ACCENT',
               'PRESSED', 'DISABLED', 'ACCENT_HOVER', 'ACCENT_PRESSED', 'ACCENT_TEXT', 'SELECTED', 'SCROLL_THUMB', 'ACCENT_INK')


def mix_color(first, second, ratio):
    return '#' + ''.join(f'{round(int(first[i:i + 2], 16) * (1 - ratio) + int(second[i:i + 2], 16) * ratio):02x}'
                         for i in (1, 3, 5))


def color_luminance(color):
    channels = [int(color[i:i + 2], 16) / 255 for i in (1, 3, 5)]
    linear = [v / 12.92 if v <= 0.04045 else ((v + 0.055) / 1.055) ** 2.4 for v in channels]
    return sum(v * weight for v, weight in zip(linear, (0.2126, 0.7152, 0.0722)))


def contrast_color(color):
    return '#101923' if color_luminance(color) > 0.179 else '#ffffff'


def theme_palette(theme='midnight', accent=None):
    if not isinstance(theme, str):
        theme = 'midnight'
    values = THEMES.get(theme, THEMES['midnight'])[1:]
    palette = dict(zip(COLOR_ROLES[:6], values))
    if isinstance(accent, str) and re.fullmatch(r'#[0-9a-fA-F]{6}', accent):
        palette['ACCENT'] = accent.lower()
    bg, card, hover, text, muted, accent = (palette[key] for key in COLOR_ROLES[:6])
    # Keep accent text readable even when the user selects a very dark color.
    palette.update(PRESSED=mix_color(hover, text, 0.12), DISABLED=mix_color(bg, muted, 0.65),
                   ACCENT_HOVER=mix_color(accent, '#ffffff', 0.18),
                   ACCENT_PRESSED=mix_color(accent, '#000000', 0.16),
                   ACCENT_TEXT=contrast_color(accent), SELECTED=mix_color(card, accent, 0.28),
                   SCROLL_THUMB=mix_color(hover, muted, 0.45))
    ink = accent
    for step in range(21):
        ink = mix_color(accent, text, step / 20)
        light, dark = sorted((color_luminance(ink), color_luminance(bg)), reverse=True)
        if (light + 0.05) / (dark + 0.05) >= 4.5:
            break
    palette['ACCENT_INK'] = ink
    return palette


globals().update(theme_palette())



class SingleInstance:
    """Keep one running DayNest process in the Windows login session."""

    def __init__(self, name=r'Local\DayNest.SingleInstance'):
        self.name = name
        self.handle = None
        self.kernel32 = ctypes.WinDLL('kernel32', use_last_error=True)
        self.kernel32.CreateMutexW.argtypes = [ctypes.c_void_p, wintypes.BOOL, wintypes.LPCWSTR]
        self.kernel32.CreateMutexW.restype = wintypes.HANDLE
        self.kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
        self.kernel32.CloseHandle.restype = wintypes.BOOL

    def acquire(self):
        if self.handle is not None:
            raise RuntimeError('Single-instance guard already acquired')
        handle = self.kernel32.CreateMutexW(None, False, self.name)
        error = ctypes.get_last_error()
        if not handle:
            raise ctypes.WinError(error)
        if error == 183:  # ERROR_ALREADY_EXISTS
            self.kernel32.CloseHandle(handle)
            return False
        self.handle = handle
        return True

    def close(self):
        if self.handle is not None:
            self.kernel32.CloseHandle(self.handle)
            self.handle = None


def startup_message(text):
    # No Tk root or application state is needed for rejected launches.
    user32 = ctypes.WinDLL('user32', use_last_error=True)
    user32.MessageBoxW.argtypes = [wintypes.HWND, wintypes.LPCWSTR, wintypes.LPCWSTR, wintypes.UINT]
    user32.MessageBoxW.restype = ctypes.c_int
    user32.MessageBoxW(None, text, APP_NAME, 0x40)


def main(restore_window=False):
    guard = SingleInstance()
    try:
        try:
            acquired = guard.acquire()
        except OSError:
            startup_message('无法检查 DayNest 是否已运行，请稍后重试。')
            return 1
        if not acquired:
            startup_message('DayNest 已在运行。请使用现有窗口；如需恢复普通窗口，请先关闭 DayNest，再运行 RestoreWindow.pyw。')
            return 0
        if restore_window:
            config = load_config()
            config['desktop'] = False
            save_config(config)
        App().run()
        return 0
    finally:
        guard.close()


def apply_theme(root, theme='midnight', accent=None):
    globals().update(theme_palette(theme, accent))
    for name in ('TkDefaultFont', 'TkTextFont', 'TkMenuFont'):
        tkfont.nametofont(name, root=root).configure(family='Microsoft YaHei UI', size=10)
    root.option_add('*TCombobox*Listbox.background', CARD)
    root.option_add('*TCombobox*Listbox.foreground', TEXT)
    root.option_add('*TCombobox*Listbox.selectBackground', HOVER)
    style = ttk.Style(root)
    style.theme_use('clam')
    style.configure('.', background=BG, foreground=TEXT, font=('Microsoft YaHei UI', 10))
    style.configure('TFrame', background=BG)
    style.configure('TNotebook', background=BG, borderwidth=0,
                    bordercolor=HOVER, lightcolor=BG, darkcolor=BG)
    style.configure('TNotebook.Tab', background=CARD, foreground=MUTED, padding=(16, 9),
                    bordercolor=HOVER, lightcolor=CARD, darkcolor=CARD)
    style.map('TNotebook.Tab', background=[('selected', HOVER), ('active', CARD)],
              foreground=[('selected', ACCENT_INK), ('active', TEXT)])
    style.configure('TSeparator', background=HOVER)
    style.configure('Card.TFrame', background=CARD)
    style.configure('TLabel', background=BG, foreground=TEXT)
    style.configure('Muted.TLabel', foreground=MUTED)
    style.configure('Title.TLabel', font=('Microsoft YaHei UI', 20, 'bold'))
    style.configure('Card.TLabel', background=CARD)
    style.configure('CardMuted.TLabel', background=CARD, foreground=MUTED)
    style.configure('TButton', background=CARD, foreground=TEXT, borderwidth=0,
                    padding=(12, 8), focusthickness=0)
    style.map('TButton', background=[('active', HOVER), ('pressed', PRESSED)],
              foreground=[('disabled', DISABLED)])
    style.configure('Accent.TButton', background=ACCENT, foreground=ACCENT_TEXT)
    style.map('Accent.TButton', background=[('active', ACCENT_HOVER), ('pressed', ACCENT_PRESSED)],
              foreground=[('active', ACCENT_TEXT), ('pressed', ACCENT_TEXT)])
    style.configure('TEntry', fieldbackground=CARD, foreground=TEXT, bordercolor=HOVER,
                    insertcolor=TEXT, padding=8, lightcolor=CARD, darkcolor=CARD)
    style.configure('TCombobox', fieldbackground=CARD, background=CARD, foreground=TEXT,
                    arrowcolor=MUTED, bordercolor=HOVER, lightcolor=CARD, darkcolor=CARD, padding=6)
    style.map('TCombobox', fieldbackground=[('readonly', CARD), ('disabled', BG)],
              foreground=[('readonly', TEXT), ('disabled', MUTED)],
              selectbackground=[('readonly', CARD)], selectforeground=[('readonly', TEXT)])
    style.configure('TLabelframe', background=BG, bordercolor=HOVER, relief='flat')
    style.configure('TLabelframe.Label', background=BG, foreground=MUTED)
    style.configure('TCheckbutton', background=BG, foreground=TEXT, padding=4)
    style.map('TCheckbutton', background=[('active', BG)], indicatorbackground=[('selected', ACCENT)])
    style.configure('Vertical.TScrollbar', background=HOVER, troughcolor=BG,
                    bordercolor=BG, lightcolor=BG, darkcolor=BG, arrowcolor=MUTED, width=10)
    style.configure('OpacityValue.TLabel', background=CARD, foreground=ACCENT_INK,
                    font=('Microsoft YaHei UI', 10, 'bold'), padding=(8, 3))
    # Image elements keep ttk's native dragging and keyboard behavior while
    # replacing clam's raised rectangular handle with a soft circular thumb.
    def blend(foreground, coverage):
        channels = [round(int(BG[i:i + 2], 16) * (1 - coverage) +
                          int(foreground[i:i + 2], 16) * coverage) for i in (1, 3, 5)]
        return '#' + ''.join(f'{channel:02x}' for channel in channels)

    def thumb(color, highlighted=False, image=None):
        if image is None:
            image = tk.PhotoImage(master=root, width=24, height=24)
        for y in range(24):
            colors = []
            for x in range(24):
                distance = ((x - 11.5) ** 2 + (y - 11.5) ** 2) ** 0.5
                halo = max(0, min(1, 10 - distance)) if highlighted else 0
                coverage = max(0, min(1, 7 - distance))
                colors.append(blend(color, coverage) if coverage else blend(HOVER, halo))
            image.put('{' + ' '.join(colors) + '}', to=(0, y))
        return image

    previous_images = getattr(root, 'opacity_style_images', None)
    track = previous_images[0] if previous_images else tk.PhotoImage(master=root, width=12, height=6)
    for y in range(6):
        colors = []
        for x in range(12):
            dx = max(0, 2.5 - x, x - 8.5)
            distance = (dx ** 2 + (y - 2.5) ** 2) ** 0.5
            colors.append(blend(HOVER, max(0, min(1, 3 - distance))))
        track.put('{' + ' '.join(colors) + '}', to=(0, y))
    normal = thumb(ACCENT_INK, image=previous_images[1] if previous_images else None)
    hover = thumb(ACCENT_HOVER, True, previous_images[2] if previous_images else None)
    pressed = thumb(ACCENT_PRESSED, True, previous_images[3] if previous_images else None)
    focus = thumb(ACCENT_INK, True, previous_images[4] if previous_images else None)
    # PhotoImage objects must live as long as the theme elements.
    root.opacity_style_images = (track, normal, hover, pressed, focus)
    if 'DayNest.Opacity.slider' not in style.element_names():
        style.element_create('DayNest.Opacity.trough', 'image', track,
                             border=(4, 0, 4, 0), sticky='we')
        style.element_create('DayNest.Opacity.slider', 'image', normal,
                             ('pressed', pressed), ('active', hover), ('focus', focus))
    style.layout('Opacity.Horizontal.TScale', [
        ('DayNest.Opacity.trough', {'sticky': 'ew', 'children': [
            ('DayNest.Opacity.slider', {'side': 'left', 'sticky': ''})]})])
    style.configure('Opacity.Horizontal.TScale', background=BG)



def flat_button(parent, text, command, bg=None, fg=None, **kwargs):
    bg, fg = bg or CARD, fg or TEXT
    button = tk.Button(parent, text=text, command=command, bg=bg, fg=fg,
                       activebackground=HOVER, activeforeground=TEXT, relief='flat',
                       bd=0, highlightthickness=0, cursor='hand2', **kwargs)
    button.bind('<Enter>', lambda _event: button.configure(bg=HOVER) if button.cget('state') != 'disabled' else None)
    button.rest_bg = bg
    button.bind('<Leave>', lambda _event: button.configure(bg=button.rest_bg))
    return button


def dialog_header(win, title, subtitle):
    win.configure(bg=BG)
    header = ttk.Frame(win, padding=(24, 20, 24, 4))
    header.pack(fill='x')
    ttk.Label(header, text=title, style='Title.TLabel').pack(anchor='w')
    ttk.Label(header, text=subtitle, style='Muted.TLabel').pack(anchor='w', pady=(5, 0))


class SlimScrollbar(tk.Canvas):
    """A fixed gutter with a dark thumb; no native arrows or disabled track."""
    def __init__(self, parent, command, bg=None):
        bg = bg or BG
        super().__init__(parent, width=10, bg=bg, highlightthickness=0, bd=0)
        self.command = command
        self.first, self.last = 0.0, 1.0
        self.hover = False
        self.drag = None
        self.bind('<Configure>', lambda _event: self.redraw())
        self.bind('<Enter>', lambda _event: self.set_hover(True))
        self.bind('<Leave>', lambda _event: self.set_hover(False))
        self.bind('<Button-1>', self.press)
        self.bind('<B1-Motion>', self.move)
        self.bind('<ButtonRelease-1>', lambda _event: setattr(self, 'drag', None))

    def set(self, first, last):
        self.first, self.last = float(first), float(last)
        self.redraw()

    def geometry_values(self):
        height = max(1, self.winfo_height() - 8)
        size = min(height, max(24, height * (self.last - self.first)))
        travel = height - size
        top = 4 + travel * self.first / max(0.00001, 1 - (self.last - self.first))
        return top, size, travel

    def redraw(self):
        self.delete('thumb')
        if self.last - self.first >= 0.99999:
            self.configure(cursor='arrow')
            return
        self.configure(cursor='hand2')
        top, size, _ = self.geometry_values()
        self.create_line(5, top + 3, 5, top + size - 3, width=6 if self.hover else 4,
                         capstyle='round', fill=MUTED if self.hover else SCROLL_THUMB, tags='thumb')

    def set_hover(self, value):
        self.hover = value
        self.redraw()

    def press(self, event):
        if self.last - self.first >= 0.99999:
            return
        top, size, travel = self.geometry_values()
        if not top <= event.y <= top + size:
            fraction = max(0, min(1, (event.y - 4 - size / 2) / max(1, travel)))
            first = fraction * (1 - (self.last - self.first))
            self.command('moveto', first)
        else:
            first = self.first
        self.drag = (event.y, first)

    def move(self, event):
        if self.drag is None:
            return
        _, _, travel = self.geometry_values()
        delta = (event.y - self.drag[0]) / max(1, travel) * (1 - (self.last - self.first))
        self.command('moveto', max(0, min(1, self.drag[1] + delta)))


def enable_wheel(target, region):
    def wheel(event):
        if event.delta:
            steps = int(event.delta / 120) or (1 if event.delta > 0 else -1)
            target.yview_scroll(-steps * 3, 'units')
        return 'break'
    region.bind('<MouseWheel>', wheel)
    for child in region.winfo_children():
        enable_wheel(target, child)


def get_logger():
    APP_DIR.mkdir(parents=True, exist_ok=True)
    log = logging.getLogger(APP_NAME)
    if not log.handlers:
        log.setLevel(logging.INFO)
        handler = RotatingFileHandler(LOG_FILE, maxBytes=500000, backupCount=2, encoding='utf-8')
        handler.setFormatter(logging.Formatter('%(asctime)s %(levelname)s %(message)s'))
        log.addHandler(handler)
    return log


class DATA_BLOB(ctypes.Structure):
    _fields_ = [('cbData', wintypes.DWORD), ('pbData', ctypes.POINTER(ctypes.c_byte))]


def protect(text):
    raw = text.encode('utf-8')
    inp = DATA_BLOB(len(raw), (ctypes.c_byte * len(raw)).from_buffer_copy(raw))
    out = DATA_BLOB()
    if not ctypes.windll.crypt32.CryptProtectData(ctypes.byref(inp), None, None, None, None, 0, ctypes.byref(out)):
        raise ctypes.WinError()
    try:
        return base64.b64encode(ctypes.string_at(out.pbData, out.cbData)).decode('ascii')
    finally:
        ctypes.windll.kernel32.LocalFree(out.pbData)


def unprotect(encoded):
    raw = base64.b64decode(encoded)
    inp = DATA_BLOB(len(raw), (ctypes.c_byte * len(raw)).from_buffer_copy(raw))
    out = DATA_BLOB()
    if not ctypes.windll.crypt32.CryptUnprotectData(ctypes.byref(inp), None, None, None, None, 0, ctypes.byref(out)):
        raise ctypes.WinError()
    try:
        return ctypes.string_at(out.pbData, out.cbData).decode('utf-8')
    finally:
        ctypes.windll.kernel32.LocalFree(out.pbData)


def normalized_opacity(value):
    try:
        value = float(value)
    except (ValueError, TypeError, OverflowError):
        return 1.0
    return value if 0.4 <= value <= 1.0 else 1.0


def load_config():
    defaults = {'username': '', 'password': '', 'x': 60, 'y': 60, 'desktop': True, 'opacity': 1.0, 'theme': 'midnight', 'accent': None}
    try:
        stored = json.loads(CONFIG_FILE.read_text(encoding='utf-8'))
        if isinstance(stored, dict):
            defaults.update(stored)
    except (OSError, ValueError):
        pass
    if not isinstance(defaults['theme'], str) or defaults['theme'] not in THEMES:
        defaults['theme'] = 'midnight'
    if not isinstance(defaults['accent'], str) or not re.fullmatch(r'#[0-9a-fA-F]{6}', defaults['accent']):
        defaults['accent'] = None
    defaults['opacity'] = normalized_opacity(defaults['opacity'])
    return defaults


def atomic_write(path, content, encoding):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode='w', encoding=encoding, dir=path.parent,
                                         prefix=path.name + '.', suffix='.tmp', delete=False) as stream:
            temporary = Path(stream.name)
            stream.write(content)
        with FILE_WRITE_LOCK:
            for attempt in range(3):
                try:
                    temporary.replace(path)
                    break
                except PermissionError:
                    if attempt == 2:
                        raise
                    time.sleep(0.05 * (attempt + 1))
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def save_config(config):
    atomic_write(CONFIG_FILE, json.dumps(config, ensure_ascii=False, indent=2), 'utf-8')


def load_cache():
    try:
        cache = json.loads(unprotect(CACHE_FILE.read_text(encoding='ascii')))
        return cache if isinstance(cache, dict) else {}
    except (OSError, ValueError, json.JSONDecodeError):
        return {}


def save_cache(cache):
    encoded = protect(json.dumps(cache, ensure_ascii=False))
    atomic_write(CACHE_FILE, encoded, 'ascii')


def transient_read_error(error):
    reason = error.reason if isinstance(error, URLError) else error
    if isinstance(reason, ssl.SSLCertVerificationError):
        return False
    if isinstance(reason, (ssl.SSLEOFError, TimeoutError, ConnectionError, IncompleteRead, RemoteDisconnected)):
        return True
    return isinstance(reason, ssl.SSLError) and getattr(reason, 'reason', '') in {
        'UNEXPECTED_EOF_WHILE_READING', 'EOF_OCCURRED_IN_VIOLATION_OF_PROTOCOL',
    }


class ResourceCache:
    def __init__(self, cache=None, username=None):
        self.lock = threading.Lock()
        self.records = OrderedDict()
        self.download_locks = {}
        cache = cache or {}
        if username is not None and cache.get('username') != username:
            return
        for record in cache.get('resource_cache', []):
            if record.get('calendar_url') and record.get('href') and record.get('raw'):
                self.store(record['calendar_url'], [record], record.get('scope_start', ''), record.get('scope_end', ''))

    def download_lock(self, calendar_url):
        with self.lock:
            return self.download_locks.setdefault(calendar_url, threading.Lock())

    def get(self, calendar_url, href):
        with self.lock:
            key = (calendar_url, href)
            record = self.records.get(key)
            if record:
                self.records.move_to_end(key)
            return dict(record) if record else None

    def store(self, calendar_url, resources, start, end):
        def day(value):
            return value.date().isoformat() if isinstance(value, datetime) else str(value)[:10]
        with self.lock:
            for resource in resources:
                href = resource['href']
                self.records[(calendar_url, href)] = {
                    'calendar_url': calendar_url, 'href': href, 'etag': resource.get('etag'),
                    'raw': resource['raw'], 'scope_start': day(start), 'scope_end': day(end),
                }
                self.records.move_to_end((calendar_url, href))
            while len(self.records) > 4000:
                self.records.popitem(last=False)

    def invalidate(self, href):
        with self.lock:
            for key in list(self.records):
                if key[1] == href:
                    del self.records[key]

    def snapshot(self):
        first = shift_month(date.today(), -6).isoformat()
        last = shift_month(date.today(), 7).isoformat()
        with self.lock:
            return [dict(record) for record in self.records.values()
                    if record['scope_start'] < last and record['scope_end'] >= first]


class CalDAV:
    def __init__(self, username, password, resource_cache=None, cancel=None):
        self.auth = 'Basic ' + base64.b64encode(f'{username}:{password}'.encode()).decode()
        self.resource_cache = resource_cache if resource_cache is not None else ResourceCache()
        self.cancel = cancel

    def request(self, method, url, xml, depth='0'):
        parsed = urlparse(url)
        host = (parsed.hostname or '').lower().rstrip('.')
        allowed = host.endswith('.icloud.com') or host.endswith('.icloud.com.cn')
        if parsed.scheme != 'https' or not allowed:
            raise ValueError(f'当前连接配置仅允许 iCloud 的 HTTPS 地址；当前服务器：{host or "空"}')
        headers = {'Authorization': self.auth, 'Content-Type': 'application/xml; charset=utf-8', 'Depth': depth}
        req = Request(url, data=xml.encode('utf-8'), headers=headers, method=method)
        for attempt in range(3):
            if self.cancel is not None and self.cancel.is_set():
                raise CancelledError()
            try:
                with urlopen(req, timeout=25) as response:
                    return ET.fromstring(response.read())
            except HTTPError as e:
                if e.code == 401:
                    raise ValueError('认证失败：请检查日历账户和密码，部分服务需要使用应用专用密码') from e
                if e.code not in (429, 502, 503, 504) or attempt == 2:
                    raise ValueError(f'日历服务返回 HTTP {e.code}') from e
                retry_error = f'HTTP{e.code}'
            except (URLError, ssl.SSLError, TimeoutError, ConnectionError, IncompleteRead) as e:
                if not transient_read_error(e):
                    raise
                if attempt == 2:
                    raise ValueError('日历服务连接中断，自动重试后仍未恢复，请稍后刷新') from e
                retry_error = type(e.reason if isinstance(e, URLError) else e).__name__
            delay = attempt + 1
            get_logger().warning('read retry method=%s attempt=%d/3 error=%s delay=%ds',
                                 method, attempt + 2, retry_error, delay)
            if self.cancel is None:
                time.sleep(delay)
            elif self.cancel.wait(delay):
                raise CancelledError()

    def propfind(self, url, properties, depth='0'):
        body = '<d:propfind xmlns:d="DAV:" xmlns:c="urn:ietf:params:xml:ns:caldav"><d:prop>' + properties + '</d:prop></d:propfind>'
        return self.request('PROPFIND', url, body, depth)

    def discover(self):
        base = 'https://caldav.icloud.com/'
        root = self.propfind(base, '<d:current-user-principal/>')
        principal = root.find('.//d:current-user-principal/d:href', NS)
        if principal is None or not principal.text:
            raise ValueError('日历服务未返回用户日历地址')
        root = self.propfind(urljoin(base, principal.text), '<c:calendar-home-set/>')
        home = root.find('.//c:calendar-home-set/d:href', NS)
        if home is None or not home.text:
            raise ValueError('日历服务未返回日历目录')
        home_url = urljoin(base, home.text)
        root = self.propfind(home_url, '<d:resourcetype/><d:displayname/><c:supported-calendar-component-set/>', '1')
        result = []
        for response in root.findall('d:response', NS):
            href = response.find('d:href', NS)
            if href is None or not href.text:
                continue
            resource = response.find('.//d:resourcetype', NS)
            if resource is None or resource.find('c:calendar', NS) is None:
                continue
            components = response.findall('.//c:supported-calendar-component-set/c:comp', NS)
            if components and not any(c.attrib.get('name', '').upper() == 'VEVENT' for c in components):
                continue
            name = response.find('.//d:displayname', NS)
            result.append((urljoin(base, href.text), name.text if name is not None and name.text else '未命名日历'))
        return result

    def events(self, calendar_url, start, end):
        start_s = start.astimezone(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
        end_s = end.astimezone(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
        body = ('<c:calendar-query xmlns:d="DAV:" xmlns:c="urn:ietf:params:xml:ns:caldav">'
                '<d:prop><d:getetag/></d:prop><c:filter><c:comp-filter name="VCALENDAR">'
                f'<c:comp-filter name="VEVENT"><c:time-range start="{start_s}" end="{end_s}"/>'
                '</c:comp-filter></c:comp-filter></c:filter></c:calendar-query>')
        root = self.request('REPORT', calendar_url, body, '1')
        if root.tag != '{DAV:}multistatus':
            raise ValueError('日历服务的日程列表响应异常，保留原缓存')
        inventory = {}
        for response in root.findall('d:response', NS):
            href = response.find('d:href', NS)
            if href is None or not href.text:
                raise ValueError('日历服务的日程列表缺少资源地址，保留原缓存')
            status = response.findtext('d:status', default='', namespaces=NS)
            if ' 404 ' in status or ' 410 ' in status:
                continue
            if status and ' 200 ' not in status:
                raise ValueError('日历服务的日程列表返回不完整，保留原缓存')
            etag = None
            for propstat in response.findall('d:propstat', NS):
                status = propstat.findtext('d:status', default='', namespaces=NS)
                if ' 200 ' in status:
                    etag = propstat.findtext('d:prop/d:getetag', namespaces=NS)
                elif ' 404 ' not in status:
                    raise ValueError('日历服务的日程版本读取失败，保留原缓存')
            inventory[urljoin(calendar_url, href.text)] = etag
        result, downloaded, gone = {}, 0, 0
        # Separate download locks from the short-lived data lock so snapshots
        # on the UI thread never wait for a network request.
        with self.resource_cache.download_lock(calendar_url):
            changed = []
            for href, etag in inventory.items():
                cached = self.resource_cache.get(calendar_url, href)
                if cached and etag and cached.get('etag') == etag and cached.get('raw'):
                    result[href] = cached
                else:
                    changed.append(href)
            for offset in range(0, len(changed), 100):
                batch = changed[offset:offset + 100]
                query = ET.Element('{urn:ietf:params:xml:ns:caldav}calendar-multiget')
                prop = ET.SubElement(query, '{DAV:}prop')
                ET.SubElement(prop, '{DAV:}getetag')
                ET.SubElement(prop, '{urn:ietf:params:xml:ns:caldav}calendar-data')
                for href in batch:
                    parsed_href = urlparse(href)
                    ET.SubElement(query, '{DAV:}href').text = parsed_href.path + (
                        '?' + parsed_href.query if parsed_href.query else '')
                data = self.request('REPORT', calendar_url, ET.tostring(query, encoding='unicode'), '1')
                if data.tag != '{DAV:}multistatus':
                    raise ValueError('日历服务的日程内容响应异常，保留原缓存')
                seen = set()
                for response in data.findall('d:response', NS):
                    href_text = response.findtext('d:href', namespaces=NS)
                    href = urljoin(calendar_url, href_text) if href_text else None
                    if href not in batch:
                        raise ValueError('日历服务的日程内容响应与请求不匹配')
                    seen.add(href)
                    status = response.findtext('d:status', default='', namespaces=NS)
                    if ' 404 ' in status or ' 410 ' in status:
                        self.resource_cache.invalidate(href)
                        gone += 1
                        continue
                    if status and ' 200 ' not in status:
                        raise ValueError('日历服务的日程内容读取失败，保留原缓存')
                    raw, etag = None, None
                    for propstat in response.findall('d:propstat', NS):
                        status = propstat.findtext('d:status', default='', namespaces=NS)
                        if ' 200 ' in status:
                            raw = propstat.findtext('d:prop/c:calendar-data', default=raw, namespaces=NS)
                            etag = propstat.findtext('d:prop/d:getetag', default=etag, namespaces=NS)
                    if raw is None:
                        raise ValueError('日历服务未返回完整日程内容，保留原缓存')
                    result[href] = {'href': href, 'raw': raw, 'etag': etag}
                    downloaded += 1
                if seen != set(batch):
                    raise ValueError('日历服务的部分日程未返回，保留原缓存')
            self.resource_cache.store(calendar_url, list(result.values()), start, end)
        get_logger().info('resource sync listed=%d reused=%d downloaded=%d gone=%d',
                          len(inventory), len(result) - downloaded, downloaded, gone)
        return list(result.values())

    def pinned_resources(self, calendar_url, uid):
        """Query a UID without a time range, including moved occurrences."""
        query = ET.Element('{urn:ietf:params:xml:ns:caldav}calendar-query')
        prop = ET.SubElement(query, '{DAV:}prop')
        ET.SubElement(prop, '{DAV:}getetag')
        ET.SubElement(prop, '{urn:ietf:params:xml:ns:caldav}calendar-data')
        filter_node = ET.SubElement(query, '{urn:ietf:params:xml:ns:caldav}filter')
        calendar = ET.SubElement(filter_node, '{urn:ietf:params:xml:ns:caldav}comp-filter', name='VCALENDAR')
        event = ET.SubElement(calendar, '{urn:ietf:params:xml:ns:caldav}comp-filter', name='VEVENT')
        uid_filter = ET.SubElement(event, '{urn:ietf:params:xml:ns:caldav}prop-filter', name='UID')
        ET.SubElement(uid_filter, '{urn:ietf:params:xml:ns:caldav}text-match',
                      collation='i;octet').text = uid
        root = self.request('REPORT', calendar_url, ET.tostring(query, encoding='unicode'), '1')
        if root.tag != '{DAV:}multistatus':
            raise ValueError('固定项查询响应异常')
        resources = []
        for response in root.findall('d:response', NS):
            status = response.findtext('d:status', default='', namespaces=NS)
            if status and ' 200 ' not in status:
                raise ValueError('固定项查询响应不完整')
            href = response.findtext('d:href', namespaces=NS)
            raw = etag = None
            for propstat in response.findall('d:propstat', NS):
                if ' 200 ' not in propstat.findtext('d:status', default='', namespaces=NS):
                    raise ValueError('固定项内容读取失败')
                raw = propstat.findtext('d:prop/c:calendar-data', default=raw, namespaces=NS)
                etag = propstat.findtext('d:prop/d:getetag', default=etag, namespaces=NS)
            if not href or not raw:
                raise ValueError('固定项内容不完整')
            resources.append({'href': urljoin(calendar_url, href), 'etag': etag, 'raw': raw})
        return resources

    def put_event(self, href, raw, etag=None, create=False):
        parsed = urlparse(href)
        host = (parsed.hostname or '').lower().rstrip('.')
        if parsed.scheme != 'https' or not (host.endswith('.icloud.com') or host.endswith('.icloud.com.cn')):
            raise ValueError('当前连接配置不允许向非 iCloud 地址写入')
        headers = {'Authorization': self.auth, 'Content-Type': 'text/calendar; charset=utf-8'}
        if create:
            headers['If-None-Match'] = '*'
        elif etag:
            headers['If-Match'] = etag
        else:
            raise ValueError('缺少事件版本号，无法安全修改')
        req = Request(href, data=raw.encode('utf-8'), headers=headers, method='PUT')
        try:
            with urlopen(req, timeout=30) as response:
                response.read()
        except HTTPError as e:
            if e.code == 412:
                raise ValueError('这条日程已在其他设备上修改，请刷新后重试') from e
            if e.code in (401, 403):
                raise ValueError('日历服务拒绝写入：请确认该日历允许编辑') from e
            raise ValueError(f'日历服务写入失败：HTTP {e.code}') from e


def parallel_results(function, arguments, cancel, max_workers=4):
    """Bounded read workers that never hold the application process open."""
    arguments = list(arguments)
    tasks, results = queue.Queue(), queue.Queue()
    for args in arguments:
        tasks.put(args)

    def worker():
        while not cancel.is_set():
            try:
                args = tasks.get_nowait()
            except queue.Empty:
                return
            try:
                result = function(*args)
                results.put((True, result))
            except Exception as error:
                results.put((False, error))

    for _ in range(min(max_workers, len(arguments))):
        threading.Thread(target=worker, daemon=True, name='DayNest-read').start()
    for _ in arguments:
        while True:
            if cancel.is_set():
                raise CancelledError()
            try:
                success, value = results.get(timeout=0.1)
                break
            except queue.Empty:
                continue
        if not success:
            raise value
        yield value


def unfold_ics(raw):
    lines = raw.replace('\r\n', '\n').replace('\r', '\n').split('\n')
    out = []
    for line in lines:
        if line.startswith((' ', '\t')) and out:
            out[-1] += line[1:]
        else:
            out.append(line)
    return out


def parse_ics_datetime(value, parameters):
    if len(value) == 8:
        return datetime.strptime(value, '%Y%m%d').replace(tzinfo=LOCAL_TZ), True
    if value.endswith('Z'):
        return datetime.strptime(value, '%Y%m%dT%H%M%SZ').replace(tzinfo=timezone.utc), False
    naive = datetime.strptime(value, '%Y%m%dT%H%M%S')
    tzid = parameters.get('TZID', '').strip('"')
    return naive.replace(tzinfo=gettz(tzid) or LOCAL_TZ), False


def decode_text(value):
    return re.sub(r'\\([nN,;\\])', lambda match: '\n' if match[1] in 'nN' else match[1], value)


def parse_ics_duration(value):
    match = re.fullmatch(r'\+?P(?:(\d+)W)?(?:(\d+)D)?(?:T(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?)?', value)
    if not match or not any(part is not None for part in match.groups()):
        raise ValueError('无法解析日程时长')
    weeks, days, hours, minutes, seconds = (int(part or 0) for part in match.groups())
    return timedelta(weeks=weeks, days=days, hours=hours, minutes=minutes, seconds=seconds)


def event_properties(raw):
    items, current, depth = [], None, 0
    for line in unfold_ics(raw):
        if line == 'BEGIN:VEVENT':
            current = {}
            depth = 0
        elif line == 'END:VEVENT':
            if current is not None:
                items.append(current)
            current = None
        elif current is not None and line.startswith('BEGIN:'):
            depth += 1
        elif current is not None and line.startswith('END:'):
            depth -= 1
        elif current is not None and depth == 0 and ':' in line:
            head, value = line.split(':', 1)
            parts = head.split(';')
            params = dict(p.split('=', 1) for p in parts[1:] if '=' in p)
            key = parts[0].upper()
            current[key] = (value, params)
            if key in ('EXDATE', 'RDATE'):
                current.setdefault('_' + key, []).append((value, params))
    return items


def event_notes(event):
    meta = event[4] if len(event) > 4 else {}
    return meta.get('description', '')


def note_preview(notes, font, width):
    text = ' '.join(notes.split())
    if font.measure(text) <= width:
        return text
    low, high = 0, len(text)
    while low < high:
        middle = (low + high + 1) // 2
        if font.measure(text[:middle] + '...') <= width:
            low = middle
        else:
            high = middle - 1
    return text[:low].rstrip() + '...'


def parse_events(raw, calendar_name, range_start, range_end, resource=None, calendar_url=None):
    items = event_properties(raw)
    overrides = set()
    for event in items:
        if 'RECURRENCE-ID' in event:
            value, params = event['RECURRENCE-ID']
            if params.get('RANGE') == 'THISANDFUTURE':
                raise ValueError('暂不支持重复日程的“此后全部改期”规则')
            overrides.add((event.get('UID', ('',))[0], parse_ics_datetime(value, params)[0]))
    out = []
    for event in items:
        if 'DTSTART' not in event or event.get('STATUS', ('',))[0] == 'CANCELLED':
            continue
        begin, all_day = parse_ics_datetime(*event['DTSTART'])
        if 'DTEND' in event:
            end = parse_ics_datetime(*event['DTEND'])[0]
        elif 'DURATION' in event:
            end = begin + parse_ics_duration(event['DURATION'][0])
        else:
            end = begin + (timedelta(days=1) if all_day else timedelta())
        if end < begin:
            raise ValueError('日程结束时间早于开始时间')
        title = decode_text(event.get('SUMMARY', ('无标题',))[0])
        meta = {
            'uid': event.get('UID', ('',))[0],
            'description': decode_text(event.get('DESCRIPTION', ('',))[0]),
            'href': resource.get('href') if resource else None,
            'etag': resource.get('etag') if resource else None,
            'raw': raw,
            'calendar_url': calendar_url,
            'end': end.isoformat(),
            'duration_seconds': (end - begin).total_seconds(),
            'recurring': any(k in event for k in ('RRULE', 'RDATE', 'EXDATE', 'RECURRENCE-ID')),
        }
        starts = [begin]
        if any(key in event for key in ('RRULE', 'RDATE', 'EXDATE')) and 'RECURRENCE-ID' not in event:
            try:
                rule = rruleset()
                rule.rdate(begin)
                if 'RRULE' in event:
                    rule.rrule(rrulestr(event['RRULE'][0], dtstart=begin))
                for key, add in (('RDATE', rule.rdate), ('EXDATE', rule.exdate)):
                    for values, params in event.get('_' + key, []):
                        for value in values.split(','):
                            if '/' in value:
                                raise ValueError('暂不支持 RDATE 时间段规则')
                            add(parse_ics_datetime(value, params)[0])
                starts = rule.xafter(range_start - (end - begin), inc=True)
            except (ValueError, TypeError) as error:
                raise ValueError('无法解析重复日程规则：' + str(error)) from error
        count = 0
        for occurrence in starts:
            if occurrence >= range_end:
                break
            if 'RECURRENCE-ID' not in event and (meta['uid'], occurrence) in overrides:
                continue
            if occurrence < range_end and occurrence + max(end - begin, timedelta(microseconds=1)) > range_start:
                count += 1
                if count > 5000:
                    raise ValueError('重复日程在查询范围内超过 5000 条，请缩小查询范围')
                occurrence_meta = dict(meta, end=(occurrence + (end - begin)).isoformat())
                if meta['recurring']:
                    original = parse_ics_datetime(*event['RECURRENCE-ID'])[0] if 'RECURRENCE-ID' in event else occurrence
                    occurrence_meta['recurrence_id'] = original.isoformat()
                out.append((occurrence.astimezone(LOCAL_TZ), title, calendar_name, all_day, occurrence_meta))
    return out


def escape_ics_text(value):
    return value.replace('\\', '\\\\').replace('\n', '\\n').replace(',', '\\,').replace(';', '\\;')


def fold_ics_lines(lines):
    folded = []
    for line in lines:
        part = ''
        for char in line:
            if len((part + char).encode('utf-8')) > 75:
                folded.append(part)
                part = ' ' + char
            else:
                part += char
        folded.append(part)
    return '\r\n'.join(folded) + '\r\n'


def ics_time(value):
    return value.astimezone(timezone.utc).strftime('%Y%m%dT%H%M%SZ')


def new_event_ics(title, start, end, description=''):
    uid = str(uuid.uuid4())
    now = ics_time(datetime.now(timezone.utc))
    raw = fold_ics_lines([
        'BEGIN:VCALENDAR', 'VERSION:2.0', 'PRODID:-//DayNest//ZH',
        'BEGIN:VEVENT', f'UID:{uid}', f'DTSTAMP:{now}',
        f'DTSTART:{ics_time(start)}', f'DTEND:{ics_time(end)}',
        f'SUMMARY:{escape_ics_text(title)}', f'DESCRIPTION:{escape_ics_text(description)}',
        'END:VEVENT', 'END:VCALENDAR',
    ])
    return uid, raw


def edit_event_ics(raw, title, start, end, description=None):
    lines = unfold_ics(raw)
    if lines.count('BEGIN:VEVENT') != 1:
        raise ValueError('该日程包含多个事件，暂不支持修改')
    replacement = {
        'SUMMARY': f'SUMMARY:{escape_ics_text(title)}',
        'DTSTART': f'DTSTART:{ics_time(start)}',
        'DTEND': f'DTEND:{ics_time(end)}',
        'DTSTAMP': f'DTSTAMP:{ics_time(datetime.now(timezone.utc))}',
    }
    if description is not None:
        replacement['DESCRIPTION'] = f'DESCRIPTION:{escape_ics_text(description)}'
    out, in_event, depth, seen = [], False, 0, set()
    for line in lines:
        if line == 'BEGIN:VEVENT':
            in_event = True
            out.append(line)
            continue
        if line == 'END:VEVENT':
            for key, value in replacement.items():
                if key not in seen:
                    out.append(value)
            in_event = False
            out.append(line)
            continue
        if in_event and line.startswith('BEGIN:'):
            depth += 1
            out.append(line)
            continue
        if in_event and line.startswith('END:'):
            depth -= 1
            out.append(line)
            continue
        key = line.split(':', 1)[0].split(';', 1)[0].upper()
        if in_event and depth == 0 and key in replacement:
            if key not in seen:
                out.append(replacement[key])
                seen.add(key)
        elif in_event and depth == 0 and key == 'DURATION':
            continue
        else:
            out.append(line)
    return fold_ics_lines(x for x in out if x)


def serialize_events(events):
    return [(event[0].isoformat(), *event[1:]) for event in events]


def deserialize_events(rows):
    return [(datetime.fromisoformat(row[0]), *row[1:]) for row in rows]


def shift_month(month, offset):
    index = month.year * 12 + month.month - 1 + offset
    year, month_index = divmod(index, 12)
    return date(year, month_index + 1, 1)


def persistent_months(months, today=None):
    center = (today or date.today()).replace(day=1)
    allowed = {shift_month(center, offset).strftime('%Y-%m') for offset in range(-6, 7)}
    return {key: value for key, value in months.items() if key in allowed}


def event_key(event):
    meta = event[4] if len(event) > 4 else {}
    return f"{meta.get('href') or meta.get('uid') or event[1]}|{event[0].isoformat()}"


def tracked_pin_event(pin, resources):
    """Resolve exactly the pinned UID and recurrence instance from fresh data."""
    previous = deserialize_events([pin['event']])[0]
    meta = previous[4]
    uid = meta['uid']
    recurring = meta.get('recurring', False)
    original = datetime.fromisoformat(meta.get('recurrence_id', pin['start']))
    if recurring and not meta.get('recurrence_id') and meta.get('raw'):
        # Recover the original identity of pins saved before recurrence_id existed.
        old_events = parse_events(meta['raw'], previous[2], previous[0],
                                  previous[0] + timedelta(microseconds=1))
        old_match = next((event for event in old_events if event[0] == previous[0]
                          and event[4]['uid'] == uid), None)
        if old_match:
            original = datetime.fromisoformat(old_match[4]['recurrence_id'])
    matches = []
    for resource in resources:
        items = [item for item in event_properties(resource['raw']) if item.get('UID', ('',))[0] == uid]
        if not items:
            raise ValueError('固定项查询返回了其他 UID')
        target = original
        if not recurring:
            active = [item for item in items if 'RECURRENCE-ID' not in item and 'DTSTART' in item
                      and item.get('STATUS', ('',))[0] != 'CANCELLED']
            if not active:
                continue
            target = parse_ics_datetime(*active[0]['DTSTART'])[0]
        else:
            override = next((item for item in items if 'RECURRENCE-ID' in item and
                             parse_ics_datetime(*item['RECURRENCE-ID'])[0] == original), None)
            if override is not None:
                if override.get('STATUS', ('',))[0] == 'CANCELLED':
                    continue
                target = parse_ics_datetime(*override['DTSTART'])[0]
        events = parse_events(resource['raw'], pin.get('calendar', previous[2]), target,
                              target + timedelta(microseconds=1), resource, meta['calendar_url'])
        for event in events:
            if event[4]['uid'] != uid:
                continue
            if recurring and datetime.fromisoformat(event[4].get('recurrence_id', event[0].isoformat())) != original:
                continue
            matches.append(event)
    if len(matches) > 1:
        raise ValueError('固定项存在多个匹配事件')
    return matches[0] if matches else None


def events_on_day(events, day):
    day_start = datetime.combine(day, datetime.min.time(), LOCAL_TZ)
    day_end = day_start + timedelta(days=1)
    matches = []
    for event in events:
        start = event[0].astimezone(LOCAL_TZ)
        meta = event[4] if len(event) > 4 else {}
        duration = meta.get('duration_seconds')
        if duration is None:
            duration = 86400 if event[3] else 3600
        end = start + timedelta(seconds=max(1, duration))
        if start < day_end and end > day_start:
            matches.append(event)
    return sorted(matches, key=lambda item: item[0])


class App:
    def __init__(self):
        self.config = load_config()
        self.cache = load_cache()
        self.resource_cache = ResourceCache(self.cache, self.config.get('username'))
        self.cache_lock = threading.Lock()
        self.syncing = False
        self.write_busy = False
        self.close_requested = False
        self.callbacks = queue.Queue()
        self.closed = threading.Event()
        self.sync_token = None
        self.events = []
        self.calendars = self.cache.get('calendars', []) if self.cache.get('username') == self.config.get('username') else []
        self.pins = self.cache.get('pins', []) if self.cache.get('username') == self.config.get('username') else []
        self.month_cache = dict(self.cache.get('months', {})) if self.cache.get('username') == self.config.get('username') else {}
        retained_months = persistent_months(self.month_cache)
        if retained_months != self.month_cache:
            self.month_cache = retained_months
            self.cache['months'] = dict(retained_months)
            save_cache(self.cache)
        self.month_loading = set()
        self.month_generation = 0
        self.month_request_limit = threading.BoundedSemaphore(4)
        self.month_tasks = queue.PriorityQueue()
        self.month_sequence = count()
        for _ in range(2):
            threading.Thread(target=self.month_worker, daemon=True).start()
        self.desktop_error = ''
        self.desktop_mode = False
        self.desktop_polling = False
        self.desktop_raised = False
        self.modal_windows = set()
        self.root = tk.Tk()
        apply_theme(self.root, self.config.get('theme', 'midnight'), self.config.get('accent'))
        self.root.title(APP_NAME)
        self.root.overrideredirect(self.config.get('desktop', True))
        self.root.geometry(f"360x580+{self.config.get('x',60)}+{self.config.get('y',60)}")
        self.root.configure(bg=BG)
        self.root.attributes('-topmost', False)
        self.root.attributes('-alpha', normalized_opacity(self.config.get('opacity', 1.0)))
        self.root.bind('<Configure>', self.moved)
        self.root.bind('<Destroy>', lambda event: self.closed.set() if event.widget == self.root else None)
        self.root.protocol('WM_DELETE_WINDOW', self.close)
        self.build()
        self.show_cached_events()
        if self.config.get('desktop', True):
            self.root.after(500, self.attach_desktop)
        if self.config.get('username') and self.config.get('password'):
            self.root.after(800, self.refresh)
        else:
            self.root.after(500, self.settings)
        self.root.after(600000, self.periodic)
        self.root.after(60000, self.update_countdowns)
        self.root.after(60, self.drain_callbacks)

    def post(self, callback, *args):
        if not self.closed.is_set():
            self.callbacks.put((callback, args))

    def close(self):
        if self.closed.is_set():
            return
        if self.write_busy:
            self.close_requested = True
            self.status.configure(text='正在保存日程，完成后退出…')
            return
        self.closed.set()
        self.sync_token = None
        self.month_generation += 1
        self.root.destroy()

    def resources(self):
        if not hasattr(self, 'resource_cache'):
            self.resource_cache = ResourceCache(self.cache, self.config.get('username'))
        return self.resource_cache

    def month_worker(self):
        while not self.closed.is_set():
            try:
                _, _, run = self.month_tasks.get(timeout=0.25)
            except queue.Empty:
                continue
            try:
                run()
            finally:
                self.month_tasks.task_done()

    def drain_callbacks(self):
        if self.closed.is_set():
            return
        for _ in range(30):
            try:
                callback, args = self.callbacks.get_nowait()
            except queue.Empty:
                break
            try:
                callback(*args)
            except Exception:
                get_logger().exception('UI callback failed')
        self.root.after(60, self.drain_callbacks)

    def build(self):
        bar = tk.Frame(self.root, bg=BG)
        bar.pack(fill='x')
        title = tk.Label(bar, text=APP_NAME, bg=BG, fg=TEXT, font=('Microsoft YaHei UI', 16, 'bold'))
        title.pack(side='left', padx=18, pady=(18, 10))
        for item in (bar, title):
            item.bind('<ButtonPress-1>', self.drag_start)
            item.bind('<B1-Motion>', self.drag_move)
        flat_button(bar, '×', self.close, bg=BG, fg=MUTED, padx=9, pady=4).pack(side='right', padx=12)
        actions = ttk.Frame(self.root, padding=(16, 0, 16, 10))
        actions.pack(fill='x')
        ttk.Button(actions, text='+ 日程', width=7, style='Accent.TButton', command=self.event_form).pack(side='left')
        ttk.Button(actions, text='日历', width=5, command=self.open_calendar).pack(side='left', padx=6)
        ttk.Button(actions, text='设置', width=5, command=self.settings).pack(side='right')
        ttk.Button(actions, text='↻', width=2, command=self.refresh).pack(side='right', padx=6)
        self.pins_frame = tk.Frame(self.root, bg=BG)
        self.pins_frame.pack(fill='x', padx=16)
        self.render_pins()
        self.status = tk.Label(self.root, text='尚未同步', bg=BG, fg=MUTED, anchor='w', wraplength=325, font=('Microsoft YaHei UI', 9))
        self.status.pack(fill='x', padx=18, pady=10)
        self.listbox = tk.Text(self.root, bg=BG, fg=TEXT, font=('Microsoft YaHei UI', 11), relief='flat', wrap='word', state='disabled', padx=10, pady=10, highlightthickness=0, spacing1=3, spacing3=3)
        self.listbox.pack(fill='both', expand=True, padx=8, pady=4)
        self.render([])

    def render(self, events):
        self.events = events
        scroll = self.listbox.yview()
        self.listbox.configure(state='normal')
        self.listbox.delete('1.0', 'end')
        for tag, command in getattr(self, 'event_bindings', {}).items():
            self.listbox.tag_unbind(tag, '<Button-1>', command)
        self.event_bindings = {}
        for tag in self.listbox.tag_names():
            if tag.startswith('event_'):
                self.listbox.tag_delete(tag)
        today = date.today()
        for day_offset in range(8):
            day = today + timedelta(days=day_offset)
            self.listbox.insert('end', f"{day:%m月%d日}  {'今天' if day_offset == 0 else ''}\n", 'heading')
            daily = events_on_day(events, day)
            if daily:
                for event in sorted(daily, key=lambda e: e[0]):
                    start, title, cal, all_day = event[:4]
                    tag = f'event_{len(self.listbox.tag_names())}_{self.listbox.index("end")}'
                    self.listbox.insert('end', f"  {'全天' if all_day else start.strftime('%H:%M')}  {title}\n", tag)
                    notes = event_notes(event)
                    if notes.strip():
                        available = max(40, (self.listbox.winfo_width() if self.listbox.winfo_width() > 1 else 324) - 52)
                        preview = note_preview(notes, tkfont.Font(font=('Microsoft YaHei UI', 9)), available)
                        self.listbox.insert('end', f'      {preview}\n', (tag, 'notes'))
                    self.listbox.insert('end', f'      {cal}\n', (tag, 'notes'))
                    self.listbox.tag_config(tag, foreground=TEXT)
                    self.event_bindings[tag] = self.listbox.tag_bind(tag, '<Button-1>', lambda _e, item=event: self.event_details(item))
            else:
                self.listbox.insert('end', '  无日程\n')
            self.listbox.insert('end', '\n')
        self.listbox.tag_config('heading', foreground=ACCENT_INK, font=('Microsoft YaHei UI', 11, 'bold'))
        self.listbox.tag_config('notes', foreground=MUTED, font=('Microsoft YaHei UI', 9))
        self.listbox.tag_raise('notes')
        self.listbox.configure(state='disabled')
        if scroll:
            self.listbox.yview_moveto(scroll[0])

    def render_pins(self):
        signature = (date.today(), tuple((pin['key'], pin['title'], pin['start'], repr(self.pinned_event(pin)))
                                         for pin in self.pins))
        if signature == getattr(self, 'pins_signature', None):
            return
        self.pins_signature = signature
        for child in self.pins_frame.winfo_children():
            child.destroy()
        if not self.pins:
            self.pins_frame.pack_forget()
            return
        if not self.pins_frame.winfo_manager():
            options = {'fill': 'x', 'padx': 16}
            if hasattr(self, 'status'):
                options['before'] = self.status
            self.pins_frame.pack(**options)
        tk.Label(self.pins_frame, text='固定日程 · 倒计时', bg=BG, fg=MUTED,
                 anchor='w', font=('Microsoft YaHei UI', 10, 'bold')).pack(fill='x', pady=(7, 2))
        today = date.today()
        for pin in sorted(self.pins, key=lambda item: item['start']):
            event = self.pinned_event(pin)
            row = tk.Frame(self.pins_frame, bg=CARD, padx=12, pady=10)
            row.pack(fill='x', pady=4)
            days = (datetime.fromisoformat(pin['start']).astimezone(LOCAL_TZ).date() - today).days
            countdown = f'还有 {days} 天' if days > 0 else ('就是今天' if days == 0 else f'已过 {-days} 天')
            flat_button(row, '×', lambda key=pin['key']: self.remove_pin(key), fg=MUTED).pack(side='right')
            title_label = tk.Label(row, text=pin['title'], bg=CARD, fg=TEXT, anchor='w', wraplength=255,
                                   font=('Microsoft YaHei UI', 10))
            title_label.pack(fill='x')
            countdown_label = tk.Label(row, text=countdown, bg=CARD, fg=ACCENT_INK, anchor='w',
                                       font=('Microsoft YaHei UI', 16, 'bold'))
            countdown_label.pack(fill='x', pady=(3, 0))
            clickable = [row, title_label, countdown_label]
            if event_notes(event).strip():
                font = tkfont.Font(font=('Microsoft YaHei UI', 9))
                preview = note_preview(event_notes(event), font, 250)
                note_label = tk.Label(row, text=preview, bg=CARD, fg=MUTED, anchor='w', font=('Microsoft YaHei UI', 9))
                note_label.pack(fill='x', pady=(5, 0))
                clickable.append(note_label)
            for widget in clickable:
                widget.configure(cursor='hand2')
                widget.bind('<Button-1>', lambda _event, item=event: self.event_details(item))

    def pinned_event(self, pin):
        if pin.get('event'):
            return deserialize_events([pin['event']])[0]
        candidates = list(getattr(self, 'events', []))
        month = getattr(self, 'month_cache', {}).get(pin['start'][:7], {})
        candidates.extend(deserialize_events(month.get('events', [])))
        match = next((event for event in candidates if event_key(event) == pin['key']), None)
        if match:
            return match
        return (datetime.fromisoformat(pin['start']), pin['title'], pin.get('calendar', ''), False, {})

    def update_countdowns(self):
        self.render_pins()
        self.root.after(60000, self.update_countdowns)

    def save_pins(self):
        with self.cache_lock:
            self.cache['username'] = self.config.get('username')
            self.cache['pins'] = self.pins
            save_cache(self.cache)

    def toggle_pin(self, event):
        key = event_key(event)
        if any(pin['key'] == key for pin in self.pins):
            self.remove_pin(key)
            return
        self.pins.append({'key': key, 'title': event[1], 'start': event[0].isoformat(),
                          'calendar': event[2], 'href': event[4].get('href') if len(event) > 4 else None,
                          'event': serialize_events([event])[0]})
        self.save_pins()
        self.render_pins()

    def remove_pin(self, key):
        self.pins = [pin for pin in self.pins if pin['key'] != key]
        self.save_pins()
        self.render_pins()

    def show_cached_events(self):
        if self.cache.get('username') != self.config.get('username'):
            return
        try:
            events = deserialize_events(self.cache.get('events', []))
            if self.cache.get('synced_at'):
                self.render(events)
                when = datetime.fromisoformat(self.cache['synced_at']).astimezone().strftime('%m月%d日 %H:%M')
                self.status.config(text=f'显示上次同步的日程 · {when}')
        except (ValueError, TypeError, IndexError):
            pass

    def moved(self, _):
        if self.root.state() == 'normal':
            self.config['x'], self.config['y'] = self.root.winfo_x(), self.root.winfo_y()

    def drag_start(self, event):
        self.drag_offset = (event.x_root - self.root.winfo_x(), event.y_root - self.root.winfo_y())

    def drag_move(self, event):
        x = event.x_root - self.drag_offset[0]
        y = event.y_root - self.drag_offset[1]
        self.root.geometry(f'+{x}+{y}')

    def refresh(self):
        if self.syncing or self.write_busy or getattr(self, 'close_requested', False):
            return
        if not self.config.get('username') or not self.config.get('password'):
            self.settings()
            return
        self.syncing = True
        token = self.sync_token = object()
        username, password = self.config['username'], self.config['password']
        resource_cache = self.resources()
        cached_calendars = list(self.cache.get('calendars', [])) if self.cache.get('username') == username else []
        cached_discovered_at = self.cache.get('discovered_at', 0)
        pinned_snapshot = json.loads(json.dumps(getattr(self, 'pins', [])))
        self.status.config(text='正在同步日历…')
        def run():
            log = get_logger()
            sync_start = time.monotonic()
            log.info('sync started')
            try:
                client = CalDAV(username, unprotect(password), resource_cache, cancel=self.closed)
                discovered_at = cached_discovered_at
                if cached_calendars and time.time() - discovered_at < 86400:
                    calendars = cached_calendars
                    log.info('discovery cache hit calendars=%d', len(calendars))
                else:
                    discovery_start = time.monotonic()
                    calendars = client.discover()
                    log.info('discovery complete calendars=%d elapsed=%.2fs', len(calendars), time.monotonic() - discovery_start)
                    discovered_at = time.time()
                now = datetime.now(LOCAL_TZ)
                start = now.replace(hour=0, minute=0, second=0, microsecond=0)
                end = start + timedelta(days=8)
                events, errors = [], []
                def fetch_one(index, url, name):
                    t0 = time.monotonic()
                    try:
                        found = []
                        resources = client.events(url, start, end)
                        for resource in resources:
                            found.extend(parse_events(resource['raw'], name, start, end, resource, url))
                        log.info('calendar index=%d resources=%d events=%d elapsed=%.2fs', index, len(resources), len(found), time.monotonic() - t0)
                        return found, None
                    except Exception as e:
                        log.warning('calendar index=%d failed elapsed=%.2fs error=%s', index, time.monotonic() - t0, type(e).__name__)
                        return [], f'{name}: {e}'
                arguments = [(i, url, name) for i, (url, name) in enumerate(calendars, 1)]
                for found, error in parallel_results(fetch_one, arguments, self.closed):
                    events.extend(found)
                    if error:
                        errors.append(error)
                if errors:
                    raise ValueError('部分日历读取失败：' + '；'.join(errors))
                pin_updates, pin_resources = [], {}
                for pin in pinned_snapshot:
                    meta = pin.get('event', [None, None, None, None, {}])[4]
                    if not meta.get('uid') or not meta.get('calendar_url'):
                        continue
                    identity = (meta['calendar_url'], meta['uid'])
                    try:
                        if identity not in pin_resources:
                            try:
                                pin_resources[identity] = client.pinned_resources(*identity)
                            except Exception as error:
                                pin_resources[identity] = error
                        resources = pin_resources[identity]
                        if isinstance(resources, Exception):
                            raise resources
                        pin_updates.append((pin, tracked_pin_event(pin, resources)))
                    except CancelledError:
                        raise
                    except Exception as error:
                        log.warning('pin sync failed error=%s', type(error).__name__)
                elapsed = time.monotonic() - sync_start
                log.info('sync complete calendars=%d events=%d elapsed=%.2fs', len(calendars), len(events), elapsed)
                self.post(self.apply_sync, token, username, events, calendars, elapsed, discovered_at, pin_updates)
            except CancelledError:
                return
            except Exception as e:
                log.warning('sync failed elapsed=%.2fs error=%s', time.monotonic() - sync_start, type(e).__name__)
                self.post(self.apply_sync_error, token, username, str(e))
        threading.Thread(target=run, daemon=True).start()

    def apply_sync(self, token, username, events, calendars, elapsed, discovered_at, pin_updates=None):
        if token is not self.sync_token or username != self.config.get('username'):
            return
        for old_pin, event in pin_updates or []:
            # Ignore a result if the user removed or edited this pin meanwhile.
            if old_pin not in self.pins:
                continue
            index = self.pins.index(old_pin)
            if event is None:
                self.pins.pop(index)
            else:
                self.pins[index] = dict(old_pin, key=event_key(event), title=event[1],
                                       start=event[0].isoformat(), calendar=event[2],
                                       href=event[4].get('href'), event=serialize_events([event])[0])
        with self.cache_lock:
            if pin_updates is not None:
                self.cache['pins'] = self.pins
            self.cache.update(username=username, events=serialize_events(events), calendars=calendars,
                              synced_at=datetime.now(timezone.utc).isoformat(), discovered_at=discovered_at)
            self.cache['resource_cache'] = self.resources().snapshot()
            try:
                save_cache(self.cache)
            except OSError:
                get_logger().warning('cache save failed after sync')
        self.finish(events, calendars, elapsed)

    def apply_sync_error(self, token, username, message):
        if token is self.sync_token and username == self.config.get('username'):
            self.sync_failed(message)

    def finish(self, events, calendars, elapsed):
        self.syncing = False
        self.calendars = calendars
        self.render(events)
        self.render_pins()
        if getattr(self, 'calendar_window', None) and self.calendar_window.winfo_exists():
            self.update_pin_buttons()
        self.preload_months(date.today())
        if getattr(self, 'calendar_window', None) and self.calendar_window.winfo_exists():
            self.preload_months(self.calendar_month)
        suffix = ' · 桌面固定失败' if self.desktop_error else ''
        self.status.config(text=f'已同步 {len(calendars)} 个日历、{len(events)} 条日程 · 用时 {elapsed:.1f} 秒{suffix}')

    def sync_failed(self, message):
        self.syncing = False
        self.status.config(text='同步失败：' + message)

    def periodic(self):
        self.refresh()
        self.root.after(600000, self.periodic)

    def open_calendar(self):
        if getattr(self, 'calendar_window', None) and self.calendar_window.winfo_exists():
            self.calendar_window.lift()
            self.calendar_window.focus_force()
            return
        win = tk.Toplevel(self.root)
        self.calendar_window = win
        win.title('日历 · 浏览和固定日程')
        win.geometry('840x650')
        win.minsize(800, 620)
        dialog_header(win, '日历', '翻阅每一天，把重要的日子留在桌面。')
        win.bind('<Destroy>', lambda event: setattr(self, 'calendar_window', None) if event.widget == win else None)
        outer = ttk.Frame(win, padding=24)
        outer.pack(fill='both', expand=True)
        left = ttk.Frame(outer)
        left.pack(side='left', fill='y')
        right = ttk.Frame(outer, padding=(26, 0, 0, 0))
        right.pack(side='left', fill='both', expand=True)
        nav = ttk.Frame(left)
        nav.pack(fill='x', pady=(0, 8))
        ttk.Button(nav, text='‹', width=4, command=lambda: self.change_calendar_month(-1)).pack(side='left')
        self.calendar_month_label = ttk.Label(nav, anchor='center', width=19,
                                               font=('Microsoft YaHei UI', 15, 'bold'))
        self.calendar_month_label.pack(side='left', fill='x', expand=True)
        ttk.Button(nav, text='›', width=4, command=lambda: self.change_calendar_month(1)).pack(side='left')
        self.calendar_grid = ttk.Frame(left)
        self.calendar_grid.pack()
        self.calendar_cells = []
        self.calendar_day_cells = {}
        self.calendar_details_signature = None
        self.calendar_pin_buttons = {}
        for col, name in enumerate('一二三四五六日'):
            ttk.Label(self.calendar_grid, text=name, style='Muted.TLabel', anchor='center').grid(row=0, column=col, pady=(8, 12))
        for index in range(42):
            frame = tk.Frame(self.calendar_grid, width=50, height=52, bg=BG)
            frame.grid(row=index // 7 + 1, column=index % 7, padx=3, pady=3)
            frame.pack_propagate(False)
            button = flat_button(frame, '', lambda: None, font=('Microsoft YaHei UI', 12))
            button.pack(fill='both', expand=True)
            marker = tk.Frame(frame, height=3, bg=BG)
            marker.pack(fill='x')
            self.calendar_cells.append({'button': button, 'marker': marker, 'day': None,
                                        'weekend': index % 7 >= 5, 'has_events': False})
        self.calendar_status = ttk.Label(left, text='', style='Muted.TLabel', wraplength=370)
        self.calendar_status.pack(fill='x', pady=16)
        ttk.Button(left, text='刷新本月', command=lambda: self.load_month(self.calendar_month, force=True)).pack(anchor='w')
        ttk.Label(right, text='当天日程', style='Muted.TLabel').pack(anchor='w', pady=(0, 5))
        self.calendar_day_label = ttk.Label(right, font=('Microsoft YaHei UI', 15, 'bold'))
        self.calendar_day_label.pack(anchor='w', pady=(2, 16))
        details_canvas = tk.Canvas(right, highlightthickness=0, width=310, bg=BG, yscrollincrement=20)
        self.calendar_details_canvas = details_canvas
        details_canvas.pack(side='left', fill='both', expand=True)
        details_scroll = SlimScrollbar(right, command=details_canvas.yview)
        details_scroll.pack(side='right', fill='y')
        details_canvas.configure(yscrollcommand=details_scroll.set)
        self.calendar_details = ttk.Frame(details_canvas)
        details_window = details_canvas.create_window((0, 0), window=self.calendar_details, anchor='nw')
        self.calendar_details.bind('<Configure>', lambda _event: details_canvas.configure(scrollregion=details_canvas.bbox('all')))
        details_canvas.bind('<Configure>', lambda event: details_canvas.itemconfigure(details_window, width=event.width))
        enable_wheel(details_canvas, details_canvas)
        enable_wheel(details_canvas, details_scroll)
        self.calendar_month = date.today().replace(day=1)
        self.calendar_day = date.today()
        self.draw_calendar()
        self.show_dialog(win, self.calendar_month_label)
        self.preload_months(self.calendar_month)

    def change_calendar_month(self, offset):
        self.calendar_month = shift_month(self.calendar_month, offset)
        self.calendar_day = self.calendar_month
        self.draw_calendar()
        self.preload_months(self.calendar_month)

    def preload_months(self, center):
        # Load the visible month first, then warm both neighboring months.
        for offset in (0, -1, 1):
            self.load_month(shift_month(center, offset), priority=0 if offset == 0 else 1)

    def month_events(self, month):
        key = month.strftime('%Y-%m')
        item = self.month_cache.get(key)
        if not item:
            return None
        try:
            decoded = getattr(self, 'decoded_months', {})
            previous = decoded.get(key)
            if previous is not None and previous[0] is item:
                return previous[1]
            events = deserialize_events(item['events'])
            self.decoded_months = {k: value for k, value in decoded.items() if k in self.month_cache}
            self.decoded_months[key] = (item, events)
            return events
        except (ValueError, TypeError, KeyError, IndexError):
            return None

    def load_month(self, month, force=False, priority=0):
        key = month.strftime('%Y-%m')
        cached = self.month_cache.get(key)
        if not force and cached and time.time() - cached.get('synced_at', 0) < 600:
            return
        if key in self.month_loading:
            return
        if not self.config.get('username') or not self.config.get('password') or not self.calendars:
            if getattr(self, 'calendar_window', None) and self.calendar_window.winfo_exists():
                self.calendar_status.configure(text='请先完成日历同步。')
            return
        self.month_loading.add(key)
        self.refresh_month_view(key)
        calendars = list(self.calendars)
        username = self.config['username']
        password = self.config['password']
        resource_cache = self.resources()
        start = datetime.combine(month, datetime.min.time(), LOCAL_TZ)
        next_month = shift_month(month, 1)
        end = datetime.combine(next_month, datetime.min.time(), LOCAL_TZ)
        generation = self.month_generation

        def run():
            if generation != self.month_generation or self.closed.is_set():
                return
            t0 = time.monotonic()
            try:
                client = CalDAV(username, unprotect(password), resource_cache, cancel=self.closed)
                def fetch_one(url, name):
                    found = []
                    with self.month_request_limit:
                        if generation != self.month_generation or self.closed.is_set():
                            return found
                        resources = client.events(url, start, end)
                    for resource in resources:
                        found.extend(parse_events(resource['raw'], name, start, end, resource, url))
                    return found
                events = []
                for found in parallel_results(fetch_one, calendars, self.closed):
                    events.extend(found)
                get_logger().info('month sync complete month=%s calendars=%d events=%d elapsed=%.2fs',
                                  key, len(calendars), len(events), time.monotonic() - t0)
                self.post(self.month_loaded, key, events, username, generation)
            except CancelledError:
                return
            except Exception as error:
                get_logger().warning('month sync failed month=%s error=%s', key, type(error).__name__)
                self.post(self.month_failed, key, str(error), generation)
        self.month_tasks.put((priority, next(self.month_sequence), run))

    def month_loaded(self, key, events, username, generation):
        if generation != self.month_generation:
            return
        self.month_loading.discard(key)
        if self.config.get('username') != username:
            return
        self.month_cache[key] = {'events': serialize_events(events), 'synced_at': time.time()}
        # Retain the disk window plus the current three-month view in memory.
        retained = persistent_months(self.month_cache)
        if getattr(self, 'calendar_window', None) and self.calendar_window.winfo_exists():
            for offset in (-1, 0, 1):
                view_key = shift_month(self.calendar_month, offset).strftime('%Y-%m')
                if view_key in self.month_cache:
                    retained[view_key] = self.month_cache[view_key]
        self.month_cache = retained
        with self.cache_lock:
            self.cache['username'] = username
            self.cache['months'] = persistent_months(self.month_cache)
            self.cache['resource_cache'] = self.resources().snapshot()
            save_cache(self.cache)
        self.refresh_month_view(key)

    def refresh_month_view(self, key):
        if getattr(self, 'calendar_window', None) and self.calendar_window.winfo_exists():
            if self.calendar_month.strftime('%Y-%m') == key:
                self.draw_calendar()

    def month_failed(self, key, message, generation):
        if generation != self.month_generation:
            return
        self.month_loading.discard(key)
        if getattr(self, 'calendar_window', None) and self.calendar_window.winfo_exists():
            if self.calendar_month.strftime('%Y-%m') == key:
                self.calendar_status.configure(text='本月同步失败：' + message)

    def draw_calendar(self):
        if not getattr(self, 'calendar_window', None) or not self.calendar_window.winfo_exists():
            return
        month = self.calendar_month
        key = month.strftime('%Y-%m')
        self.calendar_month_label.configure(text=f'{month.year} 年 {month.month} 月')
        events = self.month_events(month)
        numbers = [number for week in calendar_module.monthcalendar(month.year, month.month) for number in week]
        numbers += [0] * (42 - len(numbers))
        self.calendar_day_cells = {}
        for cell, number in zip(self.calendar_cells, numbers):
            day = date(month.year, month.month, number) if number else None
            cell['day'] = day
            cell['has_events'] = day is not None and events is not None and bool(events_on_day(events, day))
            cell['button'].configure(text=str(number) if number else '', state='normal' if number else 'disabled',
                                     command=lambda chosen=day: self.select_calendar_day(chosen))
            cell['marker'].bind('<Button-1>', lambda _event, chosen=day: self.select_calendar_day(chosen))
            if day:
                self.calendar_day_cells[day] = cell
            self.style_calendar_cell(cell)
        if key in self.month_loading:
            self.calendar_status.configure(text='正在读取本月日程…' + ('当前显示缓存' if events is not None else ''))
        elif events is None:
            self.calendar_status.configure(text='此月份尚未读取。')
        else:
            self.calendar_status.configure(text=f'本月 {len(events)} 条日程 · 彩色横条表示有日程')
        self.draw_day_details()

    def style_calendar_cell(self, cell):
        day = cell['day']
        selected = day is not None and day == self.calendar_day
        bg = BG if day is None else (SELECTED if selected else CARD)
        fg = ACCENT_INK if day == date.today() else (MUTED if cell['weekend'] else TEXT)
        cell['button'].rest_bg = bg
        cell['button'].configure(bg=bg, fg=fg, activebackground=HOVER if day else BG,
                                 font=('Microsoft YaHei UI', 12, 'bold' if selected or day == date.today() else 'normal'))
        cell['marker'].configure(bg=ACCENT_INK if cell['has_events'] else bg)

    def select_calendar_day(self, day):
        if day is None or day == self.calendar_day:
            return
        previous = self.calendar_day
        self.calendar_day = day
        for changed in (previous, day):
            if changed in self.calendar_day_cells:
                self.style_calendar_cell(self.calendar_day_cells[changed])
        self.draw_day_details()

    def draw_day_details(self):
        day = self.calendar_day
        events = self.month_events(self.calendar_month)
        daily = events_on_day(events, day) if events is not None else None
        signature = (day, None if daily is None else tuple((event_key(e), e[1], e[2], e[3], event_notes(e)) for e in daily))
        if signature == self.calendar_details_signature:
            self.update_pin_buttons()
            return
        self.calendar_details_signature = signature
        self.calendar_pin_buttons = {}
        for child in self.calendar_details.winfo_children():
            child.destroy()
        self.calendar_details_canvas.yview_moveto(0)
        self.calendar_day_label.configure(text=f'{day.year}年{day.month}月{day.day}日')
        if events is None:
            ttk.Label(self.calendar_details, text='正在读取日程…', style='Muted.TLabel').pack(anchor='w', pady=18)
            return
        if not daily:
            ttk.Label(self.calendar_details, text='这天没有日程\n享受一段自由的时间。', style='Muted.TLabel', justify='left').pack(anchor='w', pady=18)
            return
        for event in daily:
            row = ttk.Frame(self.calendar_details, style='Card.TFrame', padding=16)
            row.pack(fill='x', pady=(0, 12))
            when = '全天' if event[3] else event[0].strftime('%H:%M')
            ttk.Label(row, text=when, background=CARD, foreground=ACCENT_INK,
                      font=('Microsoft YaHei UI', 12, 'bold')).pack(anchor='w')
            title_label = ttk.Label(row, text=event[1], style='Card.TLabel', wraplength=265,
                                    font=('Microsoft YaHei UI', 11, 'bold'), justify='left', cursor='hand2')
            title_label.pack(anchor='w', pady=(8, 6))
            title_label.bind('<Button-1>', lambda _event, item=event: self.event_details(item))
            if event_notes(event).strip():
                preview = note_preview(event_notes(event), tkfont.Font(font=('Microsoft YaHei UI', 9)), 265)
                note_label = ttk.Label(row, text=preview, style='CardMuted.TLabel', cursor='hand2', font=('Microsoft YaHei UI', 9))
                note_label.pack(anchor='w', pady=(0, 6))
                note_label.bind('<Button-1>', lambda _event, item=event: self.event_details(item))
            ttk.Label(row, text=event[2], style='CardMuted.TLabel').pack(anchor='w')
            pinned = any(pin['key'] == event_key(event) for pin in self.pins)
            button = ttk.Button(row, text='取消固定' if pinned else '+ 固定到桌面',
                       style='TButton' if pinned else 'Accent.TButton',
                       command=lambda item=event: self.pin_from_calendar(item))
            button.pack(anchor='e', pady=(14, 0))
            self.calendar_pin_buttons[event_key(event)] = button
        enable_wheel(self.calendar_details_canvas, self.calendar_details)

    def update_pin_buttons(self):
        pinned_keys = {pin['key'] for pin in self.pins}
        for key, button in self.calendar_pin_buttons.items():
            pinned = key in pinned_keys
            text = '取消固定' if pinned else '+ 固定到桌面'
            if button.cget('text') != text:
                button.configure(text=text, style='TButton' if pinned else 'Accent.TButton')

    def pin_from_calendar(self, event):
        self.toggle_pin(event)
        self.update_pin_buttons()

    def event_details(self, event):
        win = tk.Toplevel(self.root)
        win.title('日程详情')
        win.geometry('560x600')
        win.minsize(500, 460)
        win.configure(bg=BG)
        header = ttk.Frame(win, padding=24)
        header.pack(fill='x')
        ttk.Label(header, text=event[1], style='Title.TLabel', wraplength=450).pack(anchor='w')
        start = event[0].astimezone(LOCAL_TZ)
        meta = event[4] if len(event) > 4 else {}
        if event[3]:
            when = start.strftime('%Y年%m月%d日') + ' · 全天'
        else:
            duration = meta.get('duration_seconds')
            end = start + timedelta(seconds=duration) if duration is not None else (
                datetime.fromisoformat(meta['end']).astimezone(LOCAL_TZ) if meta.get('end') else None)
            when = start.strftime('%Y年%m月%d日 %H:%M')
            if end:
                when += ' — ' + end.strftime('%H:%M' if end.date() == start.date() else '%m月%d日 %H:%M')
        ttk.Label(header, text=when, foreground=ACCENT_INK).pack(anchor='w', pady=(14, 5))
        ttk.Label(header, text=event[2], style='Muted.TLabel').pack(anchor='w')
        actions = ttk.Frame(win, padding=(24, 14, 24, 20))
        actions.pack(side='bottom', fill='x')
        ttk.Button(actions, text='关闭', command=win.destroy).pack(side='right')
        def edit():
            win.destroy()
            self.event_form(event)
        editable = bool(meta.get('href') and meta.get('etag') and not event[3] and not meta.get('recurring'))
        ttk.Button(actions, text='编辑日程', style='Accent.TButton', command=edit,
                   state='normal' if editable else 'disabled').pack(side='right', padx=8)
        body = ttk.Frame(win, padding=(24, 0, 24, 0))
        body.pack(fill='both', expand=True)
        ttk.Label(body, text='备注', style='Muted.TLabel').pack(anchor='w', pady=(0, 8))
        content = ttk.Frame(body)
        content.pack(fill='both', expand=True)
        notes = tk.Text(content, wrap='word', bg=CARD, fg=TEXT, relief='flat', bd=0,
                        padx=14, pady=14, highlightthickness=0, font=('Microsoft YaHei UI', 10),
                        selectbackground=HOVER, selectforeground=TEXT)
        scroll = SlimScrollbar(content, command=notes.yview, bg=CARD)
        scroll.pack(side='right', fill='y')
        notes.pack(fill='both', expand=True)
        notes.configure(yscrollcommand=scroll.set)
        notes.insert('1.0', event_notes(event) or '暂无备注')
        notes.configure(state='disabled')
        enable_wheel(notes, content)
        self.show_dialog(win, notes)

    def event_form(self, selected=None):
        editing = selected is not None
        meta = selected[4] if editing and len(selected) > 4 else None
        if editing and (not meta or not meta.get('href') or not meta.get('etag')):
            messagebox.showinfo('请先刷新', '这条缓存日程缺少服务器版本信息，请先点 ↻ 同步。', parent=self.root)
            return
        if editing and (selected[3] or meta.get('recurring')):
            messagebox.showinfo('暂不支持', '当前仅支持修改单次、非全天日程。重复日程请在对应的日历服务中修改。', parent=self.root)
            return
        if not editing and not self.calendars:
            messagebox.showinfo('请先同步', '请先设置日历账户并同步日历。', parent=self.root)
            return
        win = tk.Toplevel(self.root)
        win.title('修改日程' if editing else '添加日程')
        win.geometry('880x680')
        win.resizable(False, False)
        dialog_header(win, '修改日程' if editing else '添加日程', '留出时间，安排你在意的事。')
        footer = ttk.Frame(win, padding=(24, 0, 24, 20))
        footer.pack(side='bottom', fill='x')
        frame = ttk.Frame(win, padding=24)
        frame.pack(fill='both', expand=True)
        frame.columnconfigure(1, weight=1)
        frame.rowconfigure(5, weight=1)
        ttk.Label(frame, text='标题').grid(row=0, column=0, sticky='w', pady=6)
        title = ttk.Entry(frame, width=32)
        title.grid(row=0, column=1, pady=6, sticky='ew')
        if editing:
            title.insert(0, selected[1])
        start = selected[0] if editing else datetime.now(LOCAL_TZ).replace(minute=0, second=0, microsecond=0) + timedelta(hours=1)
        end = datetime.fromisoformat(meta['end']) if editing else start + timedelta(hours=1)
        start = start.astimezone(LOCAL_TZ)
        end = end.astimezone(LOCAL_TZ)
        date_vars = {'start': tk.StringVar(value=start.date().isoformat()),
                     'end': tk.StringVar(value=end.date().isoformat())}
        active_date = tk.StringVar(value='start')
        time_vars = {}
        for row, key, label, value in ((1, 'start', '开始', start), (2, 'end', '结束', end)):
            ttk.Label(frame, text=label).grid(row=row, column=0, sticky='w', pady=6)
            controls = ttk.Frame(frame)
            controls.grid(row=row, column=1, sticky='w', pady=6)
            ttk.Button(controls, textvariable=date_vars[key], width=13,
                       command=lambda k=key: select_date_field(k)).pack(side='left')
            hour = tk.StringVar(value=value.strftime('%H'))
            minute = tk.StringVar(value=value.strftime('%M'))
            ttk.Combobox(controls, textvariable=hour, values=[f'{i:02d}' for i in range(24)],
                         state='readonly', width=3).pack(side='left', padx=(10, 0))
            ttk.Label(controls, text=':').pack(side='left')
            ttk.Combobox(controls, textvariable=minute, values=[f'{i:02d}' for i in range(60)],
                         state='readonly', width=3).pack(side='left')
            time_vars[key] = (hour, minute)
        ttk.Label(frame, text='日历').grid(row=3, column=0, sticky='w', pady=6)
        choices = [f'{i + 1}. {name}' for i, (_, name) in enumerate(self.calendars)]
        calendar_choice = ttk.Combobox(frame, values=choices, state='readonly', width=29)
        calendar_choice.grid(row=3, column=1, pady=6, sticky='ew')
        if choices:
            current = next((i for i, (url, _) in enumerate(self.calendars) if editing and url == meta.get('calendar_url')), 0)
            calendar_choice.current(current)
        if editing:
            calendar_choice.configure(state='disabled')

        ttk.Label(frame, text='备注', style='Muted.TLabel').grid(row=4, column=0, columnspan=2, sticky='w', pady=(14, 8))
        note_frame = ttk.Frame(frame)
        note_frame.grid(row=5, column=0, columnspan=2, sticky='nsew')
        notes_input = tk.Text(note_frame, width=32, height=8, wrap='word', bg=CARD, fg=TEXT,
                              insertbackground=TEXT, relief='flat', bd=0, highlightthickness=0,
                              padx=12, pady=12, font=('Microsoft YaHei UI', 10),
                              selectbackground=HOVER, selectforeground=TEXT, undo=True)
        note_scroll = SlimScrollbar(note_frame, command=notes_input.yview, bg=CARD)
        note_scroll.pack(side='right', fill='y')
        notes_input.pack(fill='both', expand=True)
        notes_input.configure(yscrollcommand=note_scroll.set)
        if editing:
            notes_input.insert('1.0', event_notes(selected))
        enable_wheel(notes_input, note_frame)

        picker = ttk.LabelFrame(frame, text='点击日期，再在月历中选一天', padding=8)
        picker.grid(row=0, column=2, rowspan=6, sticky='n', padx=(24, 0))
        picker.columnconfigure(0, weight=1)
        nav = ttk.Frame(picker)
        nav.grid(row=0, column=0, sticky='ew')
        nav.columnconfigure(1, weight=1)
        month_label = ttk.Label(nav, anchor='center')
        month_label.grid(row=0, column=1, sticky='ew')
        selection_label = ttk.Label(picker)
        selection_label.grid(row=1, column=0, pady=(4, 2))
        days = ttk.Frame(picker)
        days.grid(row=2, column=0)
        displayed_month = [date(start.year, start.month, 1)]

        def select_date_field(key):
            active_date.set(key)
            chosen = date.fromisoformat(date_vars[key].get())
            displayed_month[0] = chosen.replace(day=1)
            draw_month()

        def shift_month(offset):
            current = displayed_month[0]
            displayed_month[0] = (current.replace(day=28) + timedelta(days=4)).replace(day=1) if offset > 0 else (current - timedelta(days=1)).replace(day=1)
            draw_month()

        def choose_day(day):
            date_vars[active_date.get()].set(day.isoformat())
            draw_month()

        def draw_month():
            current = displayed_month[0]
            month_label.configure(text=f'{current.year} 年 {current.month} 月')
            selection_label.configure(text='正在选择：' + ('开始日期' if active_date.get() == 'start' else '结束日期'))
            for child in days.winfo_children():
                child.destroy()
            for col, weekday in enumerate('一二三四五六日'):
                ttk.Label(days, text=weekday, anchor='center', width=6).grid(row=0, column=col)
            selected_day = date.fromisoformat(date_vars[active_date.get()].get())
            for row, week in enumerate(calendar_module.monthcalendar(current.year, current.month), 1):
                for col, day_number in enumerate(week):
                    if day_number:
                        day = date(current.year, current.month, day_number)
                        button = flat_button(days, str(day_number), lambda d=day: choose_day(d), width=4, pady=4,
                                             bg=SELECTED if day == selected_day else CARD,
                                             fg=ACCENT_INK if day == selected_day else TEXT)
                        button.grid(row=row, column=col, padx=2, pady=2)

        ttk.Button(nav, text='‹', width=4, command=lambda: shift_month(-1)).grid(row=0, column=0)
        ttk.Button(nav, text='›', width=4, command=lambda: shift_month(1)).grid(row=0, column=2)
        draw_month()

        def save():
            if self.write_busy or self.syncing:
                if self.syncing:
                    messagebox.showinfo('正在同步', '请等待本次同步结束后再保存。', parent=win)
                return
            name = title.get().strip()
            if not name:
                messagebox.showerror('标题不能为空', '请输入日程标题。', parent=win)
                return
            try:
                start_at = datetime.combine(date.fromisoformat(date_vars['start'].get()),
                                            datetime.strptime(':'.join(v.get() for v in time_vars['start']), '%H:%M').time(), LOCAL_TZ)
                end_at = datetime.combine(date.fromisoformat(date_vars['end'].get()),
                                          datetime.strptime(':'.join(v.get() for v in time_vars['end']), '%H:%M').time(), LOCAL_TZ)
            except ValueError:
                messagebox.showerror('时间错误', '请选择有效的日期和时间。', parent=win)
                return
            if end_at <= start_at:
                messagebox.showerror('时间错误', '结束时间必须晚于开始时间。', parent=win)
                return
            description = notes_input.get('1.0', 'end-1c')
            if editing:
                href = meta['href']
                try:
                    raw = edit_event_ics(meta['raw'], name, start_at, end_at, description)
                except ValueError as error:
                    messagebox.showerror('暂时无法编辑', str(error), parent=win)
                    return
                etag = meta['etag']
            else:
                calendar_url = self.calendars[calendar_choice.current()][0]
                uid, raw = new_event_ics(name, start_at, end_at, description)
                href = calendar_url.rstrip('/') + '/' + uid + '.ics'
                etag = None
            self.write_busy = True
            username, password = self.config['username'], self.config['password']
            self.status.config(text='正在保存到日历…')
            def run_write():
                try:
                    client = CalDAV(username, unprotect(password))
                    client.put_event(href, raw, etag, create=not editing)
                    get_logger().info('event write complete action=%s', 'edit' if editing else 'create')
                    self.post(write_done)
                except Exception as e:
                    get_logger().warning('event write failed action=%s error=%s', 'edit' if editing else 'create', type(e).__name__)
                    self.post(write_failed, str(e))
            def write_done():
                self.write_busy = False
                if username != self.config.get('username'):
                    return
                win.destroy()
                self.month_generation += 1
                self.month_loading.clear()
                self.month_cache.clear()
                self.resources().invalidate(href)
                if editing:
                    old_key = event_key(selected)
                    for pin in self.pins:
                        if pin['key'] == old_key:
                            pin['title'] = name
                            pin['start'] = start_at.isoformat()
                            pin['key'] = f'{href}|{start_at.isoformat()}'
                            updated_meta = dict(meta, raw=raw, etag=None, description=description, end=end_at.isoformat(),
                                                duration_seconds=(end_at - start_at).total_seconds())
                            pin['event'] = serialize_events([(start_at, name, selected[2], False, updated_meta)])[0]
                    self.render_pins()
                with self.cache_lock:
                    self.cache['months'] = self.month_cache
                    self.cache['pins'] = self.pins
                    self.cache['resource_cache'] = self.resources().snapshot()
                    try:
                        save_cache(self.cache)
                    except OSError:
                        get_logger().warning('cache save failed after event write')
                if getattr(self, 'close_requested', False):
                    self.close()
                    return
                if getattr(self, 'calendar_window', None) and self.calendar_window.winfo_exists():
                    self.preload_months(self.calendar_month)
                self.refresh()
            def write_failed(message):
                self.write_busy = False
                self.status.config(text='保存失败')
                messagebox.showerror('保存失败', message, parent=win if win.winfo_exists() else self.root)
                if getattr(self, 'close_requested', False):
                    self.close()
            threading.Thread(target=run_write, daemon=True).start()

        ttk.Button(footer, text='取消', command=win.destroy).pack(side='right')
        ttk.Button(footer, text='保存到日历', style='Accent.TButton', command=save).pack(side='right', padx=8)
        self.show_dialog(win, title)

    def preview_theme(self, theme, accent=None):
        previous = {role: globals()[role] for role in COLOR_ROLES}
        apply_theme(self.root, theme, accent)
        replacements = {}
        for role, color in previous.items():
            replacements.setdefault(color.lower(), globals()[role])

        def recolor(widget):
            if not widget.winfo_exists():
                return
            options = widget.keys()
            for option in ('background', 'foreground', 'activebackground', 'activeforeground',
                           'insertbackground', 'selectbackground', 'selectforeground',
                           'highlightbackground', 'highlightcolor', 'disabledforeground'):
                if option in options:
                    color = str(widget.cget(option)).lower()
                    if color in replacements:
                        widget.configure(**{option: replacements[color]})
            if hasattr(widget, 'rest_bg'):
                widget.rest_bg = replacements.get(widget.rest_bg.lower(), widget.rest_bg)
            if isinstance(widget, tk.Text):
                for tag in widget.tag_names():
                    for option in ('background', 'foreground'):
                        color = str(widget.tag_cget(tag, option)).lower()
                        if color in replacements:
                            widget.tag_configure(tag, **{option: replacements[color]})
            if isinstance(widget, tk.Canvas):
                for item in widget.find_all():
                    for option in ('fill', 'outline'):
                        try:
                            color = str(widget.itemcget(item, option)).lower()
                        except tk.TclError:
                            continue
                        if color in replacements:
                            widget.itemconfigure(item, **{option: replacements[color]})
            if isinstance(widget, (tk.Tk, tk.Toplevel)):
                try:
                    outer = ctypes.windll.user32.GetParent(widget.winfo_id())
                    dark = ctypes.c_int(contrast_color(BG) == '#ffffff')
                    ctypes.windll.dwmapi.DwmSetWindowAttribute(wintypes.HWND(outer), 20, ctypes.byref(dark), ctypes.sizeof(dark))
                except (AttributeError, OSError):
                    pass
            for child in widget.winfo_children():
                recolor(child)
        recolor(self.root)

    def settings(self):
        win = tk.Toplevel(self.root)
        win.title('设置 · DayNest')
        win.geometry('550x600')
        win.resizable(False, False)
        dialog_header(win, '设置', '连接你的日历，让日程陪伴你的桌面。')
        body = ttk.Frame(win, padding=(24, 16, 24, 0))
        body.pack(fill='both', expand=True)
        tabs = ttk.Notebook(body)
        tabs.pack(fill='both', expand=True)
        account_frame = ttk.Frame(tabs, padding=12)
        appearance_frame = ttk.Frame(tabs, padding=12)
        appearance_frame.columnconfigure(1, weight=1)
        account_frame.columnconfigure(1, weight=1)
        tabs.add(appearance_frame, text='外观与个性化')
        tabs.add(account_frame, text='日历账户')
        frame = account_frame
        ttk.Label(frame, text='账户名或邮箱').grid(row=0, column=0, sticky='w', pady=7)
        user = ttk.Entry(frame, width=35)
        user.grid(row=0, column=1, pady=7, sticky='ew')
        user.insert(0, self.config.get('username', ''))
        ttk.Label(frame, text='日历密码').grid(row=1, column=0, sticky='w', pady=7)
        password = ttk.Entry(frame, width=35, show='•')
        password.grid(row=1, column=1, pady=7, sticky='ew')
        ttk.Label(frame, text='留空保留原密码；部分服务需要应用专用密码', style='Muted.TLabel').grid(row=2, column=1, sticky='w')
        frame = appearance_frame
        desktop = tk.BooleanVar(value=self.config.get('desktop', True))
        ttk.Checkbutton(frame, text='固定在桌面层（Win + D 时仍可见）', variable=desktop).grid(row=3, column=0, columnspan=2, sticky='w', pady=14)
        autostart = tk.BooleanVar(value=self.config.get('autostart', False))
        ttk.Checkbutton(frame, text='登录 Windows 时自动启动', variable=autostart).grid(row=4, column=0, columnspan=2, sticky='w')
        ttk.Label(frame, text='窗口透明度').grid(row=5, column=0, sticky='w', pady=(18, 5))
        transparency = tk.DoubleVar(value=round((1.0 - normalized_opacity(self.config.get('opacity', 1.0))) * 100))
        opacity_frame = ttk.Frame(frame)
        opacity_frame.grid(row=5, column=1, sticky='ew', pady=(18, 5))
        opacity_label = ttk.Label(opacity_frame, width=4, anchor='center', style='OpacityValue.TLabel')
        opacity_label.pack(side='right', padx=(12, 0))
        def preview_opacity(value):
            percent = round(float(value))
            opacity_label.configure(text=f'{percent}%')
            self.root.attributes('-alpha', normalized_opacity(1.0 - percent / 100))
        opacity_slider = ttk.Scale(opacity_frame, from_=0, to=60, variable=transparency,
                                   command=preview_opacity, style='Opacity.Horizontal.TScale',
                                   cursor='hand2', takefocus=True)
        opacity_slider.pack(side='left', fill='x', expand=True)
        opacity_label.configure(text=f'{round(transparency.get())}%')
        ttk.Label(frame, text='0% 为不透明；数值越大，壁纸越明显。', style='Muted.TLabel').grid(
            row=6, column=0, columnspan=2, sticky='w')
        ttk.Label(frame, text='文字也会一起变淡，仅影响主组件。', style='Muted.TLabel').grid(
            row=7, column=0, columnspan=2, sticky='w', pady=(3, 0))
        tk.Frame(frame, bg=HOVER, height=1).grid(row=8, column=0, columnspan=2, sticky='ew', pady=(18, 10))
        ttk.Label(frame, text='界面主题').grid(row=9, column=0, sticky='w', pady=5)
        theme_keys = list(THEMES)
        current_theme = self.config.get('theme', 'midnight')
        if current_theme not in THEMES:
            current_theme = 'midnight'
        theme_choice = ttk.Combobox(frame, state='readonly', width=28,
                                    values=[THEMES[key][0] for key in theme_keys])
        theme_choice.current(theme_keys.index(current_theme))
        theme_choice.grid(row=9, column=1, sticky='ew', pady=5)
        custom_accent = tk.StringVar(value=self.config.get('accent') or '')
        ttk.Label(frame, text='主题颜色').grid(row=10, column=0, sticky='w', pady=7)
        accent_row = ttk.Frame(frame)
        accent_row.grid(row=10, column=1, sticky='ew', pady=7)
        def selected_theme():
            return theme_keys[theme_choice.current()]
        def refresh_accent_button():
            color = theme_palette(selected_theme(), custom_accent.get())['ACCENT']
            accent_button.configure(bg=color, fg=contrast_color(color), activebackground=color,
                                    activeforeground=contrast_color(color), text=f'  {color.upper()}  ')
        def preview_colors():
            self.preview_theme(selected_theme(), custom_accent.get())
            refresh_accent_button()
        def choose_accent():
            color = theme_palette(selected_theme(), custom_accent.get())['ACCENT']
            chosen = colorchooser.askcolor(color=color, title='选择主题颜色', parent=win)[1]
            if chosen:
                custom_accent.set(chosen)
                preview_colors()
        accent_button = tk.Button(accent_row, command=choose_accent, relief='flat', bd=0,
                                  font=('Microsoft YaHei UI', 10, 'bold'), padx=8, pady=6, cursor='hand2')
        accent_button.pack(side='left')
        def reset_accent():
            custom_accent.set('')
            preview_colors()
        ttk.Button(accent_row, text='恢复默认色', command=reset_accent).pack(side='right')
        theme_choice.bind('<<ComboboxSelected>>', lambda _event: reset_accent())
        refresh_accent_button()
        ttk.Label(frame, text='即时预览，保存后下次启动沿用。', style='Muted.TLabel').grid(
            row=11, column=0, columnspan=2, sticky='w', pady=(2, 0))
        def restore_opacity(event):
            if event.widget is win and self.root.winfo_exists():
                self.root.attributes('-alpha', normalized_opacity(self.config.get('opacity', 1.0)))
                self.preview_theme(self.config.get('theme', 'midnight'), self.config.get('accent'))
        win.bind('<Destroy>', restore_opacity, add='+')
        def save_appearance():
            if self.write_busy:
                messagebox.showinfo('正在保存', '请等待日程保存完成后再修改设置。', parent=win)
                return
            self.config['desktop'] = desktop.get()
            self.config['autostart'] = autostart.get()
            self.config['opacity'] = normalized_opacity(1.0 - round(transparency.get()) / 100)
            self.config['theme'] = selected_theme()
            self.config['accent'] = custom_accent.get() or None
            self.set_autostart(autostart.get())
            save_config(self.config)
            win.destroy()
            if desktop.get():
                self.attach_desktop()
            else:
                self.detach_desktop()

        def commit():
            if self.write_busy:
                messagebox.showinfo('正在保存', '请等待日程保存完成后再修改设置。', parent=win)
                return
            if not user.get().strip():
                tabs.select(account_frame)
                messagebox.showerror('缺少账户', '请输入日历账户名或邮箱', parent=win)
                return
            account_changed = self.config.get('username') != user.get().strip()
            if account_changed and not password.get():
                tabs.select(account_frame)
                messagebox.showerror('缺少密码', '更换日历账户时，请输入新账户的日历密码。', parent=win)
                return
            if not password.get() and not self.config.get('password'):
                tabs.select(account_frame)
                messagebox.showerror('缺少密码', '请输入日历密码；如果服务要求，请使用应用专用密码', parent=win)
                return
            self.config['username'] = user.get().strip()
            self.sync_token = None
            self.syncing = False
            if account_changed:
                self.resource_cache = ResourceCache()
                self.month_generation += 1
                self.month_loading.clear()
                self.month_cache = {}
                self.pins = []
                self.calendars = []
                self.render_pins()
                with self.cache_lock:
                    self.cache = {'username': self.config['username'], 'months': {}, 'pins': []}
                    save_cache(self.cache)
            if password.get():
                self.config['password'] = protect(password.get())
            save_appearance()
            self.refresh()
        footer = ttk.Frame(win, padding=(24, 10, 24, 20))
        footer.pack(fill='x')
        ttk.Button(footer, text='保存外观', command=save_appearance).pack(side='left')
        ttk.Button(footer, text='保存并同步', style='Accent.TButton', command=commit).pack(side='right')
        self.show_dialog(win, theme_choice)

    def show_dialog(self, win, focus_widget):
        win.configure(bg=BG)
        win.update_idletasks()
        width, height = win.winfo_width(), win.winfo_height()
        x = max(0, (win.winfo_screenwidth() - width) // 2)
        y = max(0, (win.winfo_screenheight() - height) // 2 - 30)
        win.geometry(f'+{x}+{y}')
        try:
            outer = ctypes.windll.user32.GetParent(win.winfo_id())
            dark = ctypes.c_int(contrast_color(BG) == '#ffffff')
            ctypes.windll.dwmapi.DwmSetWindowAttribute(wintypes.HWND(outer), 20, ctypes.byref(dark), ctypes.sizeof(dark))
        except (AttributeError, OSError):
            pass
        self.modal_windows.add(win)
        win.bind('<Destroy>', lambda event: self.modal_windows.discard(win) if event.widget == win else None, add='+')
        if self.desktop_mode:
            self._set_desktop_z_order(True)
        win.attributes('-topmost', True)
        win.lift()
        win.grab_set()
        focus_widget.focus_set()

    def attach_desktop(self):
        try:
            user32 = ctypes.WinDLL('user32', use_last_error=True)
            user32.GetParent.argtypes = [wintypes.HWND]
            user32.GetParent.restype = wintypes.HWND
            user32.GetWindowLongW.argtypes = [wintypes.HWND, ctypes.c_int]
            user32.GetWindowLongW.restype = ctypes.c_long
            user32.SetWindowLongW.argtypes = [wintypes.HWND, ctypes.c_int, ctypes.c_long]
            user32.SetWindowLongW.restype = ctypes.c_long
            user32.SetWindowPos.argtypes = [wintypes.HWND, wintypes.HWND, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int, wintypes.UINT]
            user32.SetWindowPos.restype = wintypes.BOOL
            self.root.update_idletasks()
            outer = user32.GetParent(self.root.winfo_id())
            if not outer:
                raise RuntimeError('找不到小组件外层窗口')
            # Keep the widget top-level. Rainmeter uses desktop-state detection
            # and z-order changes; parenting to Progman/DefView hides Tk windows.
            ex_style = user32.GetWindowLongW(outer, -20)
            user32.SetWindowLongW(outer, -20, (ex_style | 0x00000080) & ~0x00040000)
            self.desktop_hwnd = outer
            self.desktop_user32 = user32
            self.desktop_mode = True
            self.desktop_raised = False
            self._set_desktop_z_order(True)
            if not self.desktop_polling:
                self.desktop_polling = True
                self.root.after(250, self._poll_desktop)
            self.desktop_error = ''
            get_logger().info('desktop-aware z-order enabled')
        except Exception as e:
            self.desktop_error = str(e)
            self.root.overrideredirect(False)
            try:
                get_logger().warning('desktop layer attach failed: %s', e)
            except OSError:
                pass
            self.status.config(text=str(e))

    def _set_desktop_z_order(self, raised):
        if self.desktop_raised == raised:
            return
        # HWND_TOPMOST while Show Desktop is active; otherwise HWND_BOTTOM.
        target = -1 if raised else 1
        flags = 0x0001 | 0x0002 | 0x0010 | (0x0040 if raised else 0)
        self.desktop_user32.SetWindowPos(self.desktop_hwnd, target, 0, 0, 0, 0, flags)
        self.desktop_raised = raised

    def _poll_desktop(self):
        if not self.desktop_mode:
            self.desktop_polling = False
            return
        try:
            if self.modal_windows:
                self._set_desktop_z_order(True)
                self.root.after(250, self._poll_desktop)
                return
            user32 = self.desktop_user32
            user32.GetForegroundWindow.restype = wintypes.HWND
            user32.GetClassNameW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
            foreground = user32.GetForegroundWindow()
            class_name = ctypes.create_unicode_buffer(128)
            user32.GetClassNameW(foreground, class_name, 128)
            show_desktop = foreground == self.desktop_hwnd or class_name.value in {
                'Progman', 'WorkerW', 'SHELLDLL_DefView', 'Shell_TrayWnd',
            }
            if show_desktop:
                user32.IsIconic.argtypes = [wintypes.HWND]
                user32.IsIconic.restype = wintypes.BOOL
                if user32.IsIconic(self.desktop_hwnd):
                    user32.ShowWindow(self.desktop_hwnd, 9)  # SW_RESTORE
                self._set_desktop_z_order(True)
            else:
                self._set_desktop_z_order(False)
        except Exception as e:
            self.desktop_error = str(e)
        self.root.after(250, self._poll_desktop)

    def detach_desktop(self):
        self.desktop_mode = False
        if hasattr(self, 'desktop_hwnd'):
            self.desktop_user32.SetWindowPos(self.desktop_hwnd, -2, 0, 0, 0, 0, 0x0001 | 0x0002 | 0x0010)
        self.root.overrideredirect(False)

    def set_autostart(self, enabled):
        with winreg.CreateKey(winreg.HKEY_CURRENT_USER, r'Software\Microsoft\Windows\CurrentVersion\Run') as key:
            if enabled:
                launcher = Path(__file__).resolve()
                pythonw = Path(os.sys.executable).with_name('pythonw.exe')
                winreg.SetValueEx(key, APP_NAME, 0, winreg.REG_SZ, f'"{pythonw}" "{launcher}"')
            else:
                try:
                    winreg.DeleteValue(key, APP_NAME)
                except FileNotFoundError:
                    pass

    def run(self):
        self.root.mainloop()
        save_config(self.config)


if __name__ == '__main__':
    raise SystemExit(main())
