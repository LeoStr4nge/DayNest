import importlib.util
from pathlib import Path
from datetime import datetime, timedelta
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch, MagicMock
import threading
import xml.etree.ElementTree as ET

spec = importlib.util.spec_from_file_location('calendar_app', Path(__file__).resolve().parents[1] / 'daynest.py')
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)
url = 'https://caldav.icloud.com/test/'
start = datetime.now(m.LOCAL_TZ).replace(hour=0, minute=0, second=0, microsecond=0)
end = start + timedelta(days=8)

class Server:
    def __init__(self):
        self.items = {url + 'a.ics': ('"a1"', 'body a1'), url + 'b.ics': ('"b1"', 'body b1')}
        self.downloads = []
        self.listings = 0
        self.multigets = 0
        self.barrier = None
        self.partial = False
        self.delete_during_download = None

    def request(self, method, endpoint, xml, depth='0'):
        assert endpoint == url and method == 'REPORT'
        query = ET.fromstring(xml)
        listing = query.tag.endswith('calendar-query')
        root = ET.Element('{DAV:}multistatus')
        if listing:
            assert query.find('.//c:calendar-data', m.NS) is None
            self.listings += 1
            hrefs = list(self.items)
            if self.barrier:
                self.barrier.wait(timeout=3)
        else:
            assert query.tag.endswith('calendar-multiget')
            assert all(element.text.startswith('/') and '://' not in element.text
                       for element in query.findall('d:href', m.NS))
            self.multigets += 1
            hrefs = [m.urljoin(url, element.text) for element in query.findall('d:href', m.NS)]
            assert len(hrefs) <= 100
            self.downloads.extend(hrefs)
            if self.partial:
                hrefs = hrefs[:-1]
        for href in hrefs:
            response = ET.SubElement(root, '{DAV:}response')
            ET.SubElement(response, '{DAV:}href').text = href
            if not listing and href == self.delete_during_download:
                ET.SubElement(response, '{DAV:}status').text = 'HTTP/1.1 404 Not Found'
                continue
            propstat = ET.SubElement(response, '{DAV:}propstat')
            prop = ET.SubElement(propstat, '{DAV:}prop')
            etag, raw = self.items[href]
            if etag:
                ET.SubElement(prop, '{DAV:}getetag').text = etag
            if not listing:
                ET.SubElement(prop, '{urn:ietf:params:xml:ns:caldav}calendar-data').text = raw
            ET.SubElement(propstat, '{DAV:}status').text = 'HTTP/1.1 200 OK'
        return root

with patch.object(m, 'get_logger', return_value=MagicMock()):
    server = Server()
    store = m.ResourceCache()
    client = m.CalDAV('test', 'fake', store)
    client.request = server.request
    assert len(client.events(url, start, end)) == 2
    assert len(server.downloads) == 2
    client.events(url, start, end)
    assert len(server.downloads) == 2 and server.multigets == 1
    server.items[url + 'a.ics'] = ('"a2"', 'body a2')
    current = client.events(url, start, end)
    assert server.downloads[-1] == url + 'a.ics' and len(server.downloads) == 3
    assert next(r for r in current if r['href'].endswith('a.ics'))['raw'] == 'body a2'
    del server.items[url + 'b.ics']
    server.items[url + 'c&1.ics'] = ('"c1"', 'body c1')
    current = client.events(url, start, end)
    assert {r['href'] for r in current} == set(server.items)
    assert server.downloads[-1] == url + 'c&1.ics'

    # Reuse survives a restart and is shared across nearby and monthly ranges.
    restarted = m.ResourceCache({'username': 'test', 'resource_cache': store.snapshot()}, 'test')
    second = m.CalDAV('test', 'fake', restarted)
    second.request = server.request
    count = len(server.downloads)
    second.events(url, start, end + timedelta(days=23))
    assert len(server.downloads) == count
    isolated = m.ResourceCache({'username': 'other', 'resource_cache': store.snapshot()}, 'test')
    assert isolated.get(url, url + 'a.ics') is None

    # Missing ETags are never treated as proof that the body is unchanged.
    server.items[url + 'a.ics'] = (None, 'no etag')
    client.events(url, start, end)
    count = len(server.downloads)
    client.events(url, start, end)
    assert len(server.downloads) == count + 1

    # Do not commit incomplete responses as empty calendars or partial updates.
    old = store.get(url, url + 'a.ics')
    server.items[url + 'a.ics'] = ('"a3"', 'body a3')
    server.partial = True
    try:
        client.events(url, start, end)
        raise AssertionError('Expected incomplete-response failure')
    except ValueError:
        pass
    assert store.get(url, url + 'a.ics') == old
    server.partial = False
    server.delete_during_download = url + 'a.ics'
    assert all(r['href'] != url + 'a.ics' for r in client.events(url, start, end))
    assert store.get(url, url + 'a.ics') is None

    # Two simultaneous range requests download identical resources only once.
    server = Server()
    server.barrier = threading.Barrier(2)
    store = m.ResourceCache()
    clients = [m.CalDAV('test', 'fake', store) for _ in range(2)]
    for c in clients:
        c.request = server.request
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda c: c.events(url, start, end), clients))
    assert len(server.downloads) == 2 and server.multigets == 1
    assert all(len(result) == 2 for result in results)

    server = Server()
    server.items = {url + f'{i}.ics': (f'"{i}"', f'body {i}') for i in range(205)}
    client = m.CalDAV('test', 'fake')
    client.request = server.request
    assert len(client.events(url, start, end)) == 205
    assert server.multigets == 3 and len(server.downloads) == 205
print('Incremental fetch, restart reuse, deletion, concurrency, missing ETags, partial responses and batching passed.')
