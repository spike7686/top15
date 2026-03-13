#!/usr/bin/env python3
import json
import os
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

BASE_DIR = Path(__file__).resolve().parent
WORKDIR = BASE_DIR.parent.parent
DATA_DIR = WORKDIR / 'data' / 'top15_tracker'
HOST = os.environ.get('TOP15_BACKEND_HOST', '127.0.0.1')
PORT = int(os.environ.get('TOP15_BACKEND_PORT', '8080'))


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


def text_response(handler, text, status=200):
    data = text.encode('utf-8')
    handler.send_response(status)
    handler.send_header('Content-Type', 'text/plain; charset=utf-8')
    handler.send_header('Content-Length', str(len(data)))
    handler.end_headers()
    handler.wfile.write(data)


def latest_manifest():
    return read_json(DATA_DIR / 'latest' / 'manifest.json', default={}) or {}


def latest_display():
    return read_json(DATA_DIR / 'display' / 'latest_display.json', default=[]) or []


def latest_analysis():
    return read_json(DATA_DIR / 'latest' / 'latest.json', default=[]) or []


def list_snapshots(limit=100):
    raw_dir = DATA_DIR / 'snapshots' / 'raw'
    if not raw_dir.exists():
        return []
    return sorted([p.stem for p in raw_dir.glob('*.json')], reverse=True)[:limit]


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        path = urlparse(self.path).path

        if path == '/api/health':
            return json_response(self, {
                'ok': True,
                'service': 'top15-readonly-backend-v2',
                'host': HOST,
                'port': PORT,
            })

        if path == '/api/manifest':
            return json_response(self, {
                'ok': True,
                'manifest': latest_manifest(),
            })

        if path == '/api/latest-display':
            return json_response(self, {
                'ok': True,
                'rows': latest_display(),
            })

        if path == '/api/latest-analysis':
            return json_response(self, {
                'ok': True,
                'rows': latest_analysis(),
            })

        if path == '/api/latest-summary':
            manifest = latest_manifest()
            rows = latest_display()
            return json_response(self, {
                'ok': True,
                'snapshot_id': manifest.get('latest_snapshot_id'),
                'captured_at_utc': manifest.get('captured_at_utc'),
                'count_filtered': manifest.get('count_filtered'),
                'top15_count': manifest.get('top15_count'),
                'leaders': rows[:5],
            })

        if path == '/api/snapshots':
            return json_response(self, {
                'ok': True,
                'snapshots': list_snapshots(),
            })

        return text_response(self, 'Not Found', 404)

    def log_message(self, fmt, *args):
        sys.stderr.write('[top15-readonly-backend-v2] ' + fmt % args + '\n')


if __name__ == '__main__':
    server = ThreadingHTTPServer((HOST, PORT), Handler)
    print(json.dumps({
        'ok': True,
        'service': 'top15-readonly-backend-v2',
        'host': HOST,
        'port': PORT,
        'data_dir': str(DATA_DIR),
    }, ensure_ascii=False))
    server.serve_forever()
