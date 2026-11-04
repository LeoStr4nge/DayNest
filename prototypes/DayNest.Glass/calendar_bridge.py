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
    # Pins are a read-only snapshot; the original app remains responsible for
    # following moved/deleted events and persisting pin changes.
    pins=[dict(title=p['title'],start=p['start']) for p in cache.get('pins',[])
          if isinstance(p,dict) and p.get('title') and p.get('start')]
    return dict(status=status,pins=pins,events=[dict(start=e[0].isoformat(),end=e[4].get('end',e[0].isoformat()),title=e[1],calendar=e[2],allDay=e[3],notes=c.event_notes(e)) for e in sorted(events,key=lambda e:e[0])])

if __name__ == '__main__':
    try:
        if sys.argv[1] == 'get-account': result = account_settings()
        elif sys.argv[1] == 'save-account': result = save_account(json.load(sys.stdin))
        else: result=read_month(sys.argv[1], '--refresh' in sys.argv)
    except ValueError as error:
        result = dict(error=str(error)) if sys.argv[1] == 'save-account' else dict(error='读取失败，请检查日历设置和网络。')
    except Exception: result=dict(error='读取失败，请检查账户、网络及 Python 依赖。')
    print(json.dumps(result,ensure_ascii=True))
