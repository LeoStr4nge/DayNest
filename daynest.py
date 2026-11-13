"""CalDAV, encrypted storage and iCalendar backend for the WinUI application.

This module has no GUI entry point. Existing account/cache formats are retained.
"""
import base64
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
import ssl
import tempfile
from http.client import IncompleteRead, RemoteDisconnected
from pathlib import Path
import threading
import time
import uuid
from urllib.request import Request, build_opener, HTTPRedirectHandler
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urljoin, urlparse
import xml.etree.ElementTree as ET

from dateutil.rrule import rrulestr, rruleset
from dateutil.tz import gettz


APP_NAME = 'DayNest'
APP_DIR = Path(os.getenv('APPDATA', Path.home())) / APP_NAME
CONFIG_FILE = APP_DIR / 'config.json'
LOG_FILE = APP_DIR / 'sync.log'
CACHE_FILE = APP_DIR / 'cache.dat'
NS = {'d': 'DAV:', 'c': 'urn:ietf:params:xml:ns:caldav'}
LOCAL_TZ = datetime.now().astimezone().tzinfo
FILE_WRITE_LOCK = threading.Lock()


class SingleInstance:
    """Serialize backend access within a Windows login session; retain the legacy mutex name for compatibility."""

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


ICLOUD_DISCOVERY = 'https://caldav.icloud.com/'


def server_url(value):
    if not isinstance(value, str) or not value.strip():
        raise ValueError('请填写 HTTPS 发现地址')
    value = value.strip()
    try:
        parsed = urlparse(value)
        port = parsed.port
        host = parsed.hostname
    except ValueError as error:
        raise ValueError('服务器地址或端口无效') from error
    if parsed.scheme != 'https' or not host or parsed.username is not None or parsed.password is not None:
        raise ValueError('服务器地址必须是 HTTPS URL，账户和密码请填写在独立字段中')
    if parsed.fragment or any(char.isspace() or ord(char) < 32 for char in value) or '\\' in value:
        raise ValueError('服务器地址不能包含空白、反斜线或片段标记')
    if port == 0:
        raise ValueError('服务器端口必须大于零')
    host = host.lower().rstrip('.').encode('idna').decode('ascii')
    if not host:
        raise ValueError('服务器域名无效')
    if ':' in host:
        host = '[' + host + ']'
    origin = 'https://' + host + (f':{port}' if port and port != 443 else '')
    path = quote(parsed.path or '/', safe="/%:@!$&'()*+,;=-._~")
    query = quote(parsed.query, safe="/%?:@!$&'()*+,;=+-._~")
    return origin + path + ('?' + query if query else '')


def url_origin(value):
    parsed = urlparse(server_url(value))
    return f'{parsed.scheme}://{parsed.netloc}'


def connection_config(config):
    provider = config.get('provider', 'icloud')
    if provider == 'icloud':
        return {'provider': 'icloud', 'discovery_url': ICLOUD_DISCOVERY,
                'calendar_home_url': '', 'trusted_origins': []}
    if provider != 'custom':
        raise ValueError('请选择支持的日历服务类型')
    discovery = server_url(config.get('discovery_url', ''))
    home = config.get('calendar_home_url', '')
    home = server_url(home) if home else ''
    extra = config.get('trusted_origins', [])
    if isinstance(extra, str):
        extra = [part for part in re.split(r'[,;，；\s]+', extra.strip()) if part]
    if not isinstance(extra, list):
        raise ValueError('额外可信地址格式无效')
    origins = []
    for value in extra:
        normalized = server_url(value)
        parsed = urlparse(normalized)
        if parsed.path != '/' or parsed.query:
            raise ValueError('额外可信地址只填写 HTTPS 域名及端口，不包含路径')
        origins.append(url_origin(normalized))
    return {'provider': provider, 'discovery_url': discovery,
            'calendar_home_url': home, 'trusted_origins': sorted(set(origins))}


def cache_matches(cache, config):
    try:
        return (cache.get('username') == config.get('username') and
                connection_config(cache.get('connection', {})) == connection_config(config))
    except (ValueError, TypeError, AttributeError):
        return False


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def urlopen(request, timeout):
    # Validate redirects in CalDAV before forwarding credentials or DAV methods.
    return build_opener(NoRedirect()).open(request, timeout=timeout)


def load_config():
    defaults = {'username': '', 'password': '', 'provider': 'icloud',
                'discovery_url': '', 'calendar_home_url': '', 'trusted_origins': []}
    try:
        stored = json.loads(CONFIG_FILE.read_text(encoding='utf-8'))
        if isinstance(stored, dict):
            defaults.update(stored)
    except (OSError, ValueError):
        pass
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
    def __init__(self, username, password, resource_cache=None, cancel=None, connection=None):
        self.auth = 'Basic ' + base64.b64encode(f'{username}:{password}'.encode()).decode()
        self.resource_cache = resource_cache if resource_cache is not None else ResourceCache()
        self.cancel = cancel
        self.connection = connection_config(connection or {})
        self.allowed_origins = {url_origin(self.connection['discovery_url'])}
        if self.connection['calendar_home_url']:
            self.allowed_origins.add(url_origin(self.connection['calendar_home_url']))
        self.allowed_origins.update(self.connection['trusted_origins'])

    def validate_url(self, url):
        normalized = server_url(url)
        parsed = urlparse(normalized)
        if self.connection['provider'] == 'icloud':
            host = parsed.hostname
            allowed = (host.endswith('.icloud.com') or host.endswith('.icloud.com.cn')) and parsed.port in (None, 443)
        else:
            allowed = url_origin(normalized) in self.allowed_origins
        if not allowed:
            raise ValueError('日历服务返回未授权的服务器地址：' + url_origin(normalized) + '；请检查服务配置和额外可信地址')
        return normalized

    def open(self, request, timeout, allow_redirects=False):
        for attempt in range(6):
            if self.cancel is not None and self.cancel.is_set():
                raise CancelledError()
            self.validate_url(request.full_url)
            try:
                return urlopen(request, timeout=timeout), request.full_url
            except HTTPError as error:
                if error.code not in (301, 302, 303, 307, 308):
                    raise
                location = error.headers.get('Location') if error.headers else None
                if not allow_redirects or not location:
                    if error.fp is not None:
                        error.close()
                    raise ValueError('日历地址发生重定向，请检查地址或刷新后重试') from error
                try:
                    target = self.validate_url(urljoin(request.full_url, location))
                finally:
                    if error.fp is not None:
                        error.close()
                if attempt == 5:
                    raise ValueError('日历服务重定向次数过多')
                request = Request(target, data=request.data, headers=dict(request.header_items()), method=request.get_method())

    def request(self, method, url, xml, depth='0'):
        url = self.validate_url(url)
        headers = {'Authorization': self.auth, 'Content-Type': 'application/xml; charset=utf-8', 'Depth': depth}
        req = Request(url, data=xml.encode('utf-8'), headers=headers, method=method)
        for attempt in range(3):
            if self.cancel is not None and self.cancel.is_set():
                raise CancelledError()
            try:
                response, effective_url = self.open(req, 25, allow_redirects=True)
                with response as stream:
                    root = ET.fromstring(stream.read())
                    root.set('_request_url', effective_url)
                    return root
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
        properties = ('<d:current-user-principal/><c:calendar-home-set/>'
                      '<d:resourcetype/><d:displayname/><c:supported-calendar-component-set/>')

        def props(root):
            if root.tag not in ('{DAV:}multistatus', '{DAV:}response'):
                raise ValueError('日历发现响应异常')
            return [part.find('d:prop', NS) for part in root.findall('.//d:propstat', NS)
                    if ' 200 ' in part.findtext('d:status', default='', namespaces=NS) and part.find('d:prop', NS) is not None]

        def href_property(root, name):
            for prop in props(root):
                href = prop.find(name + '/d:href', NS)
                if href is not None and href.text:
                    return self.validate_url(urljoin(root.get('_request_url', base), href.text))
            return None

        base = self.connection['discovery_url']
        home = self.connection['calendar_home_url']
        if not home:
            root = self.propfind(base, properties)
            base = root.get('_request_url', base)
            home = href_property(root, 'c:calendar-home-set')
            if not home:
                principal = href_property(root, 'd:current-user-principal')
                if principal:
                    root = self.propfind(principal, properties)
                    base = root.get('_request_url', principal)
                    home = href_property(root, 'c:calendar-home-set')
            # Some services expose a calendar or its home directly at the URL.
            if not home:
                home = base
        root = self.propfind(home, '<d:resourcetype/><d:displayname/><c:supported-calendar-component-set/>', '1')
        home_url = root.get('_request_url', home)
        result = []
        for response in root.findall('d:response', NS):
            href = response.findtext('d:href', namespaces=NS)
            if not href:
                continue
            for prop in props(response):
                resource = prop.find('d:resourcetype', NS)
                if resource is None or resource.find('c:calendar', NS) is None:
                    continue
                components = prop.findall('c:supported-calendar-component-set/c:comp', NS)
                if components and not any(c.attrib.get('name', '').upper() == 'VEVENT' for c in components):
                    continue
                url = self.validate_url(urljoin(home_url, href))
                name = prop.findtext('d:displayname', namespaces=NS) or '未命名日历'
                if not any(item[0] == url for item in result):
                    result.append((url, name))
        if not result:
            raise ValueError('未发现可用日历，请检查发现地址，或填写日历目录地址')
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
        href = self.validate_url(href)
        headers = {'Authorization': self.auth, 'Content-Type': 'text/calendar; charset=utf-8'}
        if create:
            headers['If-None-Match'] = '*'
        elif etag:
            headers['If-Match'] = etag
        else:
            raise ValueError('缺少事件版本号，无法安全修改')
        req = Request(href, data=raw.encode('utf-8'), headers=headers, method='PUT')
        try:
            response, _ = self.open(req, 30)
            with response as stream:
                stream.read()
        except HTTPError as e:
            if e.code == 412:
                raise ValueError('这条日程已在其他设备上修改，请刷新后重试') from e
            if e.code in (401, 403):
                raise ValueError('日历服务拒绝写入：请确认该日历允许编辑') from e
            raise ValueError(f'日历服务写入失败：HTTP {e.code}') from e


    def delete_event(self, href, etag):
        href = self.validate_url(href)
        if not etag:
            raise ValueError('缺少事件版本号，无法安全删除，请刷新后重试')
        request = Request(href, headers={'Authorization': self.auth, 'If-Match': etag}, method='DELETE')
        try:
            response, _ = self.open(request, 30)
            with response as stream:
                stream.read()
        except HTTPError as error:
            if error.code in (404, 410, 412):
                raise ValueError('日程已在其他设备上修改或删除，请刷新后重试') from error
            if error.code in (401, 403):
                raise ValueError('日历服务拒绝删除，请确认日历允许编辑') from error
            raise ValueError(f'日历服务删除失败：HTTP {error.code}') from error


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


def new_event_ics(title, start, end, description='', *, uid=None):
    uid = str(uuid.UUID(uid)) if uid is not None else str(uuid.uuid4())
    now = ics_time(datetime.now(timezone.utc))
    if isinstance(start, datetime):
        dates = [f'DTSTART:{ics_time(start)}', f'DTEND:{ics_time(end)}']
    else:
        dates = [f'DTSTART;VALUE=DATE:{start:%Y%m%d}', f'DTEND;VALUE=DATE:{end:%Y%m%d}']
    raw = fold_ics_lines([
        'BEGIN:VCALENDAR', 'VERSION:2.0', 'PRODID:-//DayNest//ZH',
        'BEGIN:VEVENT', f'UID:{uid}', f'DTSTAMP:{now}',
        *dates,
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
