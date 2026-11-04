import json, sys
from pathlib import Path
from datetime import datetime
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
import daynest as c

def read():
    config=c.load_config(); cache=c.load_cache()
    if not c.cache_matches(cache,config): cache={}
    month=sys.argv[1]; start=datetime.strptime(month,'%Y-%m').replace(tzinfo=c.LOCAL_TZ)
    end=datetime.combine(c.shift_month(start.date(),1),datetime.min.time(),c.LOCAL_TZ)
    events=c.deserialize_events(cache.get('months',{}).get(month,{}).get('events',cache.get('events',[])))
    status='本地缓存 · 刷新可获取本月日程'
    if '--refresh' in sys.argv:
        if not config.get('username') or not config.get('password'): return dict(events=[],status='请先在原版 DayNest 设置日历账户')
        client=c.CalDAV(config['username'],c.unprotect(config['password']),c.ResourceCache(cache,config['username']),connection=c.connection_config(config))
        events=[]
        for url,name in client.discover():
            for resource in client.events(url,start,end): events.extend(c.parse_events(resource['raw'],name,start,end,resource,url))
        status='本月日程已同步'
    return dict(status=status,events=[dict(start=e[0].isoformat(),end=e[4].get('end',e[0].isoformat()),title=e[1],calendar=e[2],allDay=e[3],notes=c.event_notes(e)) for e in sorted(events,key=lambda e:e[0])])
try: result=read()
except Exception: result=dict(error='读取失败，请检查账户、网络及 Python 依赖。')
print(json.dumps(result,ensure_ascii=True))
