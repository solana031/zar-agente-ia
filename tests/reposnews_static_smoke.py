"""Real artifact smoke: standard-library HTTP server only, no app imports/network.

Run: python tests/reposnews_static_smoke.py dist/reposnews
"""
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import sys
from threading import Thread
from urllib.request import urlopen
import xml.etree.ElementTree as ET


def smoke(root):
    root = Path(root).resolve()
    urls = [el.text for el in ET.fromstring((root/'sitemap.xml').read_bytes()).iter() if el.tag.split('}')[-1] == 'loc']
    paths = ['/', '/sitemap.xml', '/robots.txt']
    paths += [url.removeprefix('https://www.reposnews.com') for url in urls]
    paths += ['/'+p.relative_to(root).as_posix() for p in (root/'media/reposnews').iterdir() if p.is_file()]

    class QuietHandler(SimpleHTTPRequestHandler):
        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(('127.0.0.1', 0), partial(QuietHandler, directory=str(root)))
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        for path in paths:
            with urlopen('http://127.0.0.1:'+str(server.server_port)+path, timeout=10) as response:
                assert response.status == 200, path
                assert response.read(), path
    finally:
        server.shutdown()
        server.server_close()
        thread.join()
    return dict(static_http_checks=len(paths), all_http_200=True, server='Python SimpleHTTPRequestHandler', backend_required=False, database_required=False, railway_runtime_required=False)


if __name__ == '__main__':
    print(json.dumps(smoke(sys.argv[1]), indent=2))
