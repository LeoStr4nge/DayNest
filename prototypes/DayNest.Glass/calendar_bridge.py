import json, sys
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


def pin_views(cache, config):
    return [dict(title=p['title'], start=p['start'], key=pin_key(p), actionHandle=c.protect(json.dumps(dict(
        purpose='pin-remove', username=config['username'], connection=c.connection_config(config), key=pin_key(p)))))
        for p in cache.get('pins', []) if isinstance(p, dict) and p.get('title') and p.get('start')]


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

def read_month(month, refresh=False):
    config=c.load_config(); cache=c.load_cache()
    if not c.cache_matches(cache,config): cache={}
    start=datetime.strptime(month,'%Y-%m').replace(tzinfo=c.LOCAL_TZ)
    end=datetime.combine(c.shift_month(start.date(),1),datetime.min.time(),c.LOCAL_TZ)
    events=c.deserialize_events(cache.get('months',{}).get(month,{}).get('events',cache.get('events',[])))
    status='本地缓存 · 刷新可获取本月日程'
    if refresh:
        if not config.get('username') or not config.get('password'): return dict(events=[],pins=[],status='请打开设置，填写日历账户后同步')
        client=c.CalDAV(config['username'],c.unprotect(config['password']),c.ResourceCache(cache,config['username']),connection=c.connection_config(config))
        events=[]
        for url,name in client.discover():
            for resource in client.events(url,start,end): events.extend(c.parse_events(resource['raw'],name,start,end,resource,url))
        status='本月日程已同步'
    pins=pin_views(cache, config)
    return dict(status=status,pins=pins,events=[event_view(e, config) for e in sorted(events,key=lambda e:e[0])])

if __name__ == '__main__':
    try:
        if sys.argv[1] == 'get-account': result = account_settings()
        elif sys.argv[1] == 'save-account': result = save_account(json.load(sys.stdin))
        elif sys.argv[1] == 'edit-event': result = mutate_event(json.load(sys.stdin))
        elif sys.argv[1] == 'delete-event': result = mutate_event(json.load(sys.stdin), delete=True)
        elif sys.argv[1] == 'add-pin': result = set_pin(json.load(sys.stdin))
        elif sys.argv[1] == 'remove-pin': result = set_pin(json.load(sys.stdin), remove=True)
        else: result=read_month(sys.argv[1], '--refresh' in sys.argv)
    except ValueError as error:
        result = dict(error=str(error)) if sys.argv[1] in ('save-account', 'edit-event', 'delete-event', 'add-pin', 'remove-pin') else dict(error='读取失败，请检查日历设置和网络。')
    except Exception: result=dict(error='读取失败，请检查账户、网络及 Python 依赖。')
    print(json.dumps(result,ensure_ascii=True))
