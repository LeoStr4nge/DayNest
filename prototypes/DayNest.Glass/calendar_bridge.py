import json, sys
from pathlib import Path
from datetime import datetime
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
import daynest as c

def read_month(month, refresh=False):
    config=c.load_config(); cache=c.load_cache()
    if not c.cache_matches(cache,config): cache={}
    start=datetime.strptime(month,'%Y-%m').replace(tzinfo=c.LOCAL_TZ)
    end=datetime.combine(c.shift_month(start.date(),1),datetime.min.time(),c.LOCAL_TZ)
    events=c.deserialize_events(cache.get('months',{}).get(month,{}).get('events',cache.get('events',[])))
    status='本地缓存 · 刷新可获取本月日程'
    if refresh:
        if not config.get('username') or not config.get('password'): return dict(events=[],pins=[],status='请先在原版 DayNest 设置日历账户')
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
    try: result=read_month(sys.argv[1], '--refresh' in sys.argv)
    except Exception: result=dict(error='读取失败，请检查账户、网络及 Python 依赖。')
    print(json.dumps(result,ensure_ascii=True))
