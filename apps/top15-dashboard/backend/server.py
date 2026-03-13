#!/usr/bin/env python3
import json
import os
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

APP_DIR = Path(__file__).resolve().parent.parent
WORKDIR = APP_DIR.parent.parent
DATA_DIR = WORKDIR / 'data' / 'top15_tracker'
FRONTEND_DIR = APP_DIR / 'frontend'

HOST = os.environ.get('TOP15_DASHBOARD_HOST', '127.0.0.1')
PORT = int(os.environ.get('TOP15_DASHBOARD_PORT', '3310'))


def read_json(path: Path, default=None):
    if not path.exists():
        return default
    return json.loads(path.read_text(encoding='utf-8'))


def json_response(handler, payload, status=200):
    data = json.dumps(payload, ensure_ascii=False).encode('utf-8')
    handler.send_response(status)
    handler.send_header('Content-Type', 'application/json; charset=utf-8')
    handler.send_header('Content-Length', str(len(data)))
    handler.send_header('Cache-Control', 'no-store')
    handler.end_headers()
    handler.wfile.write(data)


def text_response(handler, text, status=200, content_type='text/plain; charset=utf-8'):
    data = text.encode('utf-8')
    handler.send_response(status)
    handler.send_header('Content-Type', content_type)
    handler.send_header('Content-Length', str(len(data)))
    handler.end_headers()
    handler.wfile.write(data)


def file_response(handler, path: Path, content_type='text/html; charset=utf-8'):
    if not path.exists():
        return text_response(handler, 'Not Found', 404)
    data = path.read_bytes()
    handler.send_response(200)
    handler.send_header('Content-Type', content_type)
    handler.send_header('Content-Length', str(len(data)))
    handler.end_headers()
    handler.wfile.write(data)


def latest_manifest():
    return read_json(DATA_DIR / 'latest' / 'manifest.json', default={}) or {}


def latest_display():
    return read_json(DATA_DIR / 'display' / 'latest_display.json', default=[])


def latest_analysis():
    return read_json(DATA_DIR / 'latest' / 'latest.json', default=[])


def snapshot_display(snapshot_id: str):
    path = DATA_DIR / 'snapshots' / 'display' / f'{snapshot_id}.csv'
    return path


def list_snapshots(limit=50):
    raw_dir = DATA_DIR / 'snapshots' / 'raw'
    if not raw_dir.exists():
        return []
    items = sorted([p.stem for p in raw_dir.glob('*.json')], reverse=True)
    return items[:limit]


def history_display_rows(limit=200):
    path = DATA_DIR / 'history_display.csv'
    if not path.exists():
        return []
    rows = []
    import csv
    with path.open(encoding='utf-8') as f:
        reader = csv.DictReader(f)
        for row in reader:
            rows.append(row)
    return rows[-limit:]


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path
        query = parse_qs(parsed.query)

        if path == '/api/health':
            return json_response(self, {'ok': True, 'service': 'top15-dashboard-api'})

        if path == '/api/manifest':
            manifest = latest_manifest()
            payload = {
                'ok': True,
                'manifest': manifest,
                'available_snapshots': list_snapshots(limit=30),
            }
            return json_response(self, payload)

        if path == '/api/latest-display':
            return json_response(self, {'ok': True, 'rows': latest_display()})

        if path == '/api/latest-analysis':
            return json_response(self, {'ok': True, 'rows': latest_analysis()})

        if path == '/api/history-display':
            try:
                limit = int(query.get('limit', ['200'])[0])
            except Exception:
                limit = 200
            limit = max(1, min(limit, 2000))
            return json_response(self, {'ok': True, 'rows': history_display_rows(limit=limit)})

        if path == '/api/snapshots':
            return json_response(self, {'ok': True, 'snapshots': list_snapshots(limit=100)})

        if path == '/api/latest-summary':
            rows = latest_display() or []
            manifest = latest_manifest()
            payload = {
                'ok': True,
                'snapshot_id': manifest.get('latest_snapshot_id'),
                'captured_at_utc': manifest.get('captured_at_utc'),
                'count_filtered': manifest.get('count_filtered'),
                'top15_count': manifest.get('top15_count'),
                'leaders': rows[:5],
            }
            return json_response(self, payload)

        if path == '/' or path == '/index.html':
            return file_response(self, FRONTEND_DIR / 'index.html', 'text/html; charset=utf-8')
        if path == '/app.js':
            return file_response(self, FRONTEND_DIR / 'app.js', 'application/javascript; charset=utf-8')
        if path == '/styles.css':
            return file_response(self, FRONTEND_DIR / 'styles.css', 'text/css; charset=utf-8')

        return text_response(self, 'Not Found', 404)

    def log_message(self, fmt, *args):
        sys.stderr.write('[top15-dashboard] ' + fmt % args + '\n')


if __name__ == '__main__':
    server = ThreadingHTTPServer((HOST, PORT), Handler)
    print(json.dumps({'ok': True, 'host': HOST, 'port': PORT, 'data_dir': str(DATA_DIR)}, ensure_ascii=False))
    server.serve_forever()
