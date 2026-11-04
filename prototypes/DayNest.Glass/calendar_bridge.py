import json, sys, time, uuid
from pathlib import Path
from datetime import datetime
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
import daynest as c


def account_settings():
    config = c.load_config()
    return {key: config.get(key, default) for key, default in
            [('username', ''), ('provider', 'icloud'), ('discovery_url', ''),
             ('calendar_home_url', ''), ('trusted_origins', [])]} | {'hasPassword': bool(config.get('password'))}


def save_account(payload):
    guard = c.SingleInstance()
    try:
        if not guard.acquire():
            raise ValueError('请先退出原版 DayNest，再修改日历账户。')
        config = c.load_config()
        username = str(payload.get('username', '')).strip()
        password = payload.get('password', '')
        if not username:
            raise ValueError('请输入日历账户名或邮箱。')
        if not isinstance(password, str):
            raise ValueError('日历密码格式无效。')
        connection = c.connection_config(payload)
        try:
            old_connection = c.connection_config(config)
        except ValueError:
            old_connection = None
        changed = username != config.get('username') or connection != old_connection
        if changed and not password:
            raise ValueError('更换账户或日历服务时，请重新输入日历密码。')
        if not password and not config.get('password'):
            raise ValueError('请输入日历密码，iCloud 请使用 App 专用密码。')
        updated = dict(config, **connection, username=username)
        if password:
            updated['password'] = c.protect(password)
        c.save_config(updated)
        # The connection/username check prevents old data from being reused even
        # if the process stops between the two atomic writes.
        if changed:
            try:
                c.save_cache({'username': username, 'connection': connection, 'months': {}, 'pins': []})
            except (OSError, ValueError):
                # Credentials have already committed. Report success so the UI
                # drops its old data; cache_matches rejects the old cache.
                return {'ok': True, 'accountChanged': True, 'cacheReset': False}
        return {'ok': True, 'accountChanged': changed}
    finally:
        guard.close()


def event_view(event, config):
    meta = event[4]
    raw = meta.get('raw', '')
    items = c.event_properties(raw)
    single = len(items) == 1 and not meta.get('recurring') and not any(
        key in items[0] for key in ('RRULE', 'RDATE', 'EXDATE', 'RECURRENCE-ID'))
    mutable = bool(single and meta.get('href') and meta.get('etag'))
    handle = None
    if mutable:
        handle = c.protect(json.dumps(dict(username=config['username'], connection=c.connection_config(config),
                                         event=c.serialize_events([event])[0])))
    pin_handle = c.protect(json.dumps(dict(purpose='pin-event', username=config['username'], connection=c.connection_config(config),
                                         event=c.serialize_events([event])[0])))
    return dict(start=event[0].isoformat(), end=meta.get('end', event[0].isoformat()), title=event[1],
                calendar=event[2], allDay=event[3], notes=c.event_notes(event),
                handle=handle, pinHandle=pin_handle, key=c.event_key(event), editable=mutable and not event[3], deletable=mutable)


def pin_key(pin):
    return pin.get('key') or f"{pin.get('href') or pin['title']}|{pin['start']}"


def pinned_event(pin, cache):
    if pin.get('event'):
        return c.deserialize_events([pin['event']])[0]
    rows = list(cache.get('events', []))
    for month in cache.get('months', {}).values(): rows.extend(month.get('events', []))
    for event in c.deserialize_events(rows):
        if c.event_key(event) == pin_key(pin) or (pin.get('href') and event[4].get('href') == pin['href']
                and event[0] == datetime.fromisoformat(pin['start'])): return event
    return (datetime.fromisoformat(pin['start']), pin['title'], pin.get('calendar', ''), False, {})


def pin_views(cache, config):
    views = []
    for pin in sorted((p for p in cache.get('pins', []) if isinstance(p, dict) and p.get('title') and p.get('start')), key=lambda p: p['start']):
        event = pinned_event(pin, cache)
        view = event_view(event, config)
        view['key'] = pin_key(pin)
        views.append(dict(title=pin['title'], start=pin['start'], key=pin_key(pin), notes=c.event_notes(event), event=view,
            actionHandle=c.protect(json.dumps(dict(purpose='pin-remove', username=config['username'],
                connection=c.connection_config(config), key=pin_key(pin))))))
    return views


def track_pins(cache, client):
    """Authoritative UID queries, shared per resource, using original recurrence logic."""
    updated, lookups, failures = [], {}, 0
    for pin in cache.get('pins', []):
        try:
            previous = pinned_event(pin, cache)
            meta = previous[4]
            if not meta.get('uid') or not meta.get('calendar_url'):
                updated.append(pin); continue
            identity = (meta['calendar_url'], meta['uid'])
            if identity not in lookups:
                try: lookups[identity] = client.pinned_resources(*identity)
                except Exception as error: lookups[identity] = error
            resources = lookups[identity]
            if isinstance(resources, Exception): raise resources
            event = c.tracked_pin_event(dict(pin, event=c.serialize_events([previous])[0]), resources)
            if event is not None:
                updated.append(dict(pin, key=c.event_key(event), title=event[1], start=event[0].isoformat(),
                    calendar=event[2], href=event[4].get('href'), event=c.serialize_events([event])[0]))
        except Exception:
            updated.append(pin); failures += 1
    return updated, failures


def set_pin(payload, remove=False):
    guard = c.SingleInstance()
    try:
        if not guard.acquire():
            raise ValueError('请先退出原版 DayNest，再修改固定倒计时。')
        config = c.load_config()
        try:
            token = json.loads(c.unprotect(payload['handle']))
        except (ValueError, KeyError, TypeError):
            raise ValueError('固定项信息无效，请重新打开日程后再试。')
        if token.get('username') != config.get('username') or token.get('connection') != c.connection_config(config):
            raise ValueError('日历账户已改变，请刷新后重试。')
        if token.get('purpose') != ('pin-remove' if remove else 'pin-event'):
            raise ValueError('固定项操作信息无效，请刷新后重试。')
        cache = c.load_cache()
        if not c.cache_matches(cache, config):
            cache = dict(username=config['username'], connection=c.connection_config(config), months={}, pins=[])
        pins = cache.setdefault('pins', [])
        if remove:
            cache['pins'] = [p for p in pins if pin_key(p) != token['key']]
        else:
            event = c.deserialize_events([token['event']])[0]
            key = c.event_key(event)
            if not any(pin_key(p) == key for p in pins):
                pins.append(dict(key=key, title=event[1], start=event[0].isoformat(), calendar=event[2],
                                 href=event[4].get('href'), event=token['event']))
        c.save_cache(cache)
        return dict(ok=True, pins=pin_views(cache, config))
    finally:
        guard.close()


def mutate_event(payload, delete=False):
    guard = c.SingleInstance()
    try:
        if not guard.acquire():
            raise ValueError('请先退出原版 DayNest，再修改日程。')
        config = c.load_config()
        try:
            token = json.loads(c.unprotect(payload['handle']))
        except (ValueError, KeyError, TypeError):
            raise ValueError('日程信息无效，请刷新后重试。')
        if token.get('username') != config.get('username') or token.get('connection') != c.connection_config(config):
            raise ValueError('日历账户已改变，请刷新后重试。')
        event = c.deserialize_events([token['event']])[0]
        meta = event[4]
        items = c.event_properties(meta.get('raw', ''))
        if len(items) != 1 or meta.get('recurring') or any(k in items[0] for k in ('RRULE', 'RDATE', 'EXDATE', 'RECURRENCE-ID')):
            raise ValueError('重复日程请在原日历服务中修改或删除，避免误操作整个系列。')
        if not meta.get('etag') or not meta.get('href'):
            raise ValueError('缺少日程版本信息，请先刷新。')
        client = c.CalDAV(config['username'], c.unprotect(config['password']), connection=c.connection_config(config))
        href = meta['href']
        replacement = None
        if delete:
            if payload.get('confirmed') is not True:
                raise ValueError('请确认删除后再操作。')
            client.delete_event(href, meta['etag'])
        else:
            if event[3]:
                raise ValueError('全天日程请在原日历服务中编辑。')
            title = str(payload.get('title', '')).strip()
            if not title:
                raise ValueError('日程标题不能为空。')
            try:
                start, end = (datetime.fromisoformat(payload[key]) for key in ('start', 'end'))
                if start.tzinfo is None or end.tzinfo is None or end <= start:
                    raise ValueError()
            except (ValueError, KeyError, TypeError):
                raise ValueError('日期时间无效，结束时间必须晚于开始时间。')
            notes = str(payload.get('notes', ''))
            raw = c.edit_event_ics(meta['raw'], title, start, end, notes)
            client.put_event(href, raw, meta['etag'])
            updated = dict(meta, raw=raw, etag=None, end=end.isoformat(), description=notes,
                           duration_seconds=(end-start).total_seconds())
            replacement = c.serialize_events([(start, title, event[2], False, updated)])[0]
        warning = None
        try:
            cache = c.load_cache()
            if c.cache_matches(cache, config):
                cache['months'] = {}
                cache['events'] = [row for row in cache.get('events', []) if row[4].get('href') != href]
                if replacement is not None:
                    cache['events'].append(replacement)
                cache['resource_cache'] = [r for r in cache.get('resource_cache', []) if r.get('href') != href]
                if delete:
                    cache['pins'] = [p for p in cache.get('pins', []) if p.get('href') != href]
                else:
                    for pin in cache.get('pins', []):
                        if pin.get('href') == href:
                            pin.update(title=replacement[1], start=replacement[0], event=replacement,
                                       key=f'{href}|{replacement[0]}')
                c.save_cache(cache)
        except Exception:
            warning = '服务器已更新，但本地缓存未能更新；请刷新后再操作。'
        return {'ok': True, 'warning': warning}
    finally:
        guard.close()

def calendar_choices(payload=None):
    config = c.load_config()
    if not config.get('username') or not config.get('password'):
        raise ValueError('请先在设置中填写日历账户并同步。')
    cache = c.load_cache()
    calendars = cache.get('calendars', []) if c.cache_matches(cache, config) else []
    if not calendars and not (payload or {}).get('cachedOnly'):
        client = c.CalDAV(config['username'], c.unprotect(config['password']), connection=c.connection_config(config))
        calendars = client.discover()
    return dict(calendars=[dict(name=name, handle=c.protect(json.dumps(dict(
        purpose='create-calendar', username=config['username'], connection=c.connection_config(config),
        url=url, name=name)))) for url, name in calendars])


def create_event(payload):
    guard = c.SingleInstance()
    try:
        if not guard.acquire():
            raise ValueError('请先退出原版 DayNest，再添加日程。')
        config = c.load_config()
        try:
            token = json.loads(c.unprotect(payload['handle']))
        except (ValueError, KeyError, TypeError):
            raise ValueError('日历信息无效，请重新打开添加日程。')
        if token.get('purpose') != 'create-calendar' or token.get('username') != config.get('username') or token.get('connection') != c.connection_config(config):
            raise ValueError('日历账户已改变，请重新打开添加日程。')
        title = str(payload.get('title', '')).strip()
        if not title:
            raise ValueError('日程标题不能为空。')
        try:
            start, end = (datetime.fromisoformat(payload[key]) for key in ('start', 'end'))
            if start.tzinfo is None or end.tzinfo is None or end <= start:
                raise ValueError()
            request_id = str(uuid.UUID(payload['requestId']))
        except (ValueError, KeyError, TypeError, AttributeError):
            raise ValueError('日期时间无效，结束时间必须晚于开始时间。')
        notes = str(payload.get('notes', ''))
        uid, raw = c.new_event_ics(title, start, end, notes, uid=request_id)
        client = c.CalDAV(config['username'], c.unprotect(config['password']), connection=c.connection_config(config))
        href = token['url'].rstrip('/') + '/' + uid + '.ics'
        # A stable UID per form plus If-None-Match prevents duplicate creation
        # when the first response is lost and the user retries the same form.
        client.put_event(href, raw, create=True)
        warning = None
        try:
            cache = c.load_cache()
            if not c.cache_matches(cache, config):
                cache = dict(username=config['username'], connection=c.connection_config(config), pins=[])
            cache['months'] = {}
            meta = dict(raw=raw, uid=uid, href=href, etag=None, calendar_url=token['url'],
                        end=end.isoformat(), description=notes, duration_seconds=(end-start).total_seconds())
            row = c.serialize_events([(start, title, token['name'], False, meta)])[0]
            cache['events'] = [e for e in cache.get('events', []) if e[4].get('href') != href] + [row]
            cache['resource_cache'] = [r for r in cache.get('resource_cache', []) if r.get('href') != href]
            c.save_cache(cache)
        except Exception:
            warning = '日程已添加到服务器，但本地缓存未能更新；请刷新确认，不要重复添加。'
        return dict(ok=True, warning=warning)
    finally:
        guard.close()


def read_month(month, refresh=False, sync_pins=True):
    # Serialize a whole refresh against account changes, edits, pins and the Tk
    # app. The UI cancels/awaits reads before writing, so no stale snapshot can
    # overwrite a successful write. Terminating a read releases the OS mutex.
    guard = c.SingleInstance() if refresh else None
    try:
        if guard and not guard.acquire():
            raise ValueError('请先退出原版 DayNest 或其他正在同步的实例，再同步日历。')
        config = c.load_config(); cache = c.load_cache()
        if not c.cache_matches(cache, config): cache = {}
        configured = bool(config.get('username') and config.get('password'))
        start = datetime.strptime(month, '%Y-%m').replace(tzinfo=c.LOCAL_TZ)
        end = datetime.combine(c.shift_month(start.date(), 1), datetime.min.time(), c.LOCAL_TZ)
        entry = cache.get('months', {}).get(month)
        events = c.deserialize_events(entry.get('events', []) if entry is not None else cache.get('events', []))
        synced_at = entry.get('synced_at', 0) if entry is not None else 0
        status = '显示本地缓存' if entry is not None else '本月尚未完整同步'
        warning = None
        if refresh and configured:
            resources = c.ResourceCache(cache, config['username'])
            client = c.CalDAV(config['username'], c.unprotect(config['password']), resources, connection=c.connection_config(config))
            calendars = cache.get('calendars', [])
            discovered_at = cache.get('discovered_at', 0)
            if not calendars or time.time() - discovered_at >= 86400:
                calendars = client.discover(); discovered_at = time.time()
            events = []
            for url, name in calendars:
                for resource in client.events(url, start, end):
                    events.extend(c.parse_events(resource['raw'], name, start, end, resource, url))
            if sync_pins and cache.get('pins'):
                pins, failures = track_pins(cache, client)
                cache = dict(cache, pins=pins)
                if failures: warning = '部分固定项暂未能更新，已保留上次数据。'
            # Commit only after every calendar succeeds. Preserve pins and the
            # other months; reuse the original encrypted/atomic cache format.
            synced_at = time.time()
            entry = dict(events=c.serialize_events(events), synced_at=synced_at)
            cache = dict(cache, username=config['username'], connection=c.connection_config(config),
                         calendars=calendars, discovered_at=discovered_at, resource_cache=resources.snapshot(),
                         months=c.persistent_months(dict(cache.get('months', {}), **{month: entry})))
            try: c.save_cache(cache)
            except (OSError, ValueError): warning = (warning + ' ' if warning else '') + '日程已同步，但缓存保存失败；重启后需要重新同步。'
            status = '已同步 · ' + datetime.now().strftime('%H:%M')
        if not configured: status = '请打开设置，填写日历账户后同步'
        return dict(status=status, pins=pin_views(cache, config), configured=configured,
                    hasCache=entry is not None, syncedAt=synced_at, warning=warning,
                    events=[event_view(e, config) for e in sorted(events, key=lambda e: e[0])])
    finally:
        if guard: guard.close()

if __name__ == '__main__':
    try:
        if sys.argv[1] == 'get-account': result = account_settings()
        elif sys.argv[1] == 'save-account': result = save_account(json.load(sys.stdin))
        elif sys.argv[1] == 'edit-event': result = mutate_event(json.load(sys.stdin))
        elif sys.argv[1] == 'delete-event': result = mutate_event(json.load(sys.stdin), delete=True)
        elif sys.argv[1] == 'add-pin': result = set_pin(json.load(sys.stdin))
        elif sys.argv[1] == 'remove-pin': result = set_pin(json.load(sys.stdin), remove=True)
        elif sys.argv[1] == 'get-calendars': result = calendar_choices(json.load(sys.stdin))
        elif sys.argv[1] == 'create-event': result = create_event(json.load(sys.stdin))
        else: result=read_month(sys.argv[1], '--refresh' in sys.argv, '--no-pin-sync' not in sys.argv)
    except ValueError as error:
        result = dict(error=str(error))
    except Exception: result=dict(error='读取失败，请检查账户、网络及 Python 依赖。')
    print(json.dumps(result,ensure_ascii=True))
