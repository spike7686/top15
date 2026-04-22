import csv
import json
import math
import urllib.parse
from datetime import datetime, timedelta, timezone
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Dict, List

HOST = '0.0.0.0'
PORT = 8090
ALLOWED_SYMBOLS = {'BTCUSDT', 'ETHUSDT', 'SOLUSDT', 'BNBUSDT'}
ALLOWED_INTERVALS = {'15m', '1h', '4h'}
TZ_BJT = timezone(timedelta(hours=8))
ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = ROOT / 'data' / 'klines_platform'
RAW_DIR = DATA_DIR / 'raw'
EXPORT_DIR = DATA_DIR / 'export'
APP_DIR = ROOT / 'apps' / 'klines-platform'
FIXED_START_MS = int(datetime(2024, 1, 1, tzinfo=timezone.utc).timestamp() * 1000)
FIXED_END_MS = int(datetime(2026, 3, 1, tzinfo=timezone.utc).timestamp() * 1000)

for path in [RAW_DIR, EXPORT_DIR]:
    path.mkdir(parents=True, exist_ok=True)


def bjt_input_to_utc_ms(value: str) -> int:
    dt = datetime.strptime(value, '%Y-%m-%dT%H:%M')
    dt = dt.replace(tzinfo=TZ_BJT)
    return int(dt.astimezone(timezone.utc).timestamp() * 1000)


class ReadonlyStore:
    def raw_path(self, symbol: str, interval: str) -> Path:
        return RAW_DIR / f'{symbol}_{interval}.csv'

    def export_path(self, symbol: str, interval: str) -> Path:
        return EXPORT_DIR / f'{symbol}_{interval}_20240101_20260301.csv'

    def read_rows(self, symbol: str, interval: str) -> List[Dict[str, str]]:
        path = self.raw_path(symbol, interval)
        if not path.exists():
            return []
        with path.open('r', encoding='utf-8', newline='') as f:
            return list(csv.DictReader(f))

    def query_rows(self, symbol: str, interval: str) -> List[Dict[str, str]]:
        rows = self.read_rows(symbol, interval)
        return [r for r in rows if FIXED_START_MS <= int(r['open_time_ms']) <= FIXED_END_MS]

    def paginate_rows(self, rows: List[Dict[str, str]], page: int, page_size: int):
        total_rows = len(rows)
        total_pages = max(1, math.ceil(total_rows / page_size))
        page = min(max(1, page), total_pages)
        start = (page - 1) * page_size
        end = start + page_size
        return rows[start:end], {
            'page': page,
            'page_size': page_size,
            'total_rows': total_rows,
            'total_pages': total_pages,
        }

    def export_query(self, symbol: str, interval: str) -> Path:
        rows = self.query_rows(symbol, interval)
        path = self.export_path(symbol, interval)
        with path.open('w', encoding='utf-8', newline='') as f:
            writer = csv.DictWriter(f, fieldnames=[
                'open_time_ms', 'open_time_bjt', 'open', 'high', 'low', 'close', 'volume',
                'close_time_ms', 'quote_asset_volume', 'number_of_trades',
                'taker_buy_base_asset_volume', 'taker_buy_quote_asset_volume',
                'ema5', 'ema21', 'ema144'
            ])
            writer.writeheader()
            writer.writerows(rows)
        return path

    def cache_status(self) -> List[Dict[str, str]]:
        items = []
        for path in sorted(RAW_DIR.glob('*.csv')):
            with path.open('r', encoding='utf-8', newline='') as f:
                rows = list(csv.DictReader(f))
            if rows:
                stem = path.stem
                symbol = '_'.join(stem.split('_')[:-1]) if stem.count('_') > 1 else stem.split('_')[0]
                interval = stem.split('_')[-1]
                items.append({
                    'file_name': path.name,
                    'symbol': symbol,
                    'interval': interval,
                    'row_count': len(rows),
                    'first_open_time_bjt': rows[0]['open_time_bjt'],
                    'last_open_time_bjt': rows[-1]['open_time_bjt'],
                })
        return items


STORE = ReadonlyStore()


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        if parsed.path == '/':
            return self.serve_file(APP_DIR / 'index.html', 'text/html; charset=utf-8')
        if parsed.path == '/static/styles.css':
            return self.serve_file(APP_DIR / 'styles.css', 'text/css; charset=utf-8')
        if parsed.path == '/static/app.js':
            return self.serve_file(APP_DIR / 'app.js', 'application/javascript; charset=utf-8')
        if parsed.path == '/api/cache-status':
            return self.send_json({'items': STORE.cache_status()})
        if parsed.path == '/api/download':
            params = urllib.parse.parse_qs(parsed.query)
            try:
                symbol = params.get('symbol', [''])[0]
                interval = params.get('interval', [''])[0]
                self.validate_symbol_interval(symbol, interval)
                path = STORE.export_query(symbol, interval)
                return self.serve_file(path, 'text/csv; charset=utf-8', as_attachment=True)
            except Exception as exc:
                return self.send_json({'error': str(exc)}, HTTPStatus.BAD_REQUEST)
        return self.send_json({'error': 'Not found'}, HTTPStatus.NOT_FOUND)

    def do_POST(self):
        parsed = urllib.parse.urlparse(self.path)
        if parsed.path != '/api/query':
            return self.send_json({'error': 'Not found'}, HTTPStatus.NOT_FOUND)
        try:
            length = int(self.headers.get('Content-Length', '0'))
            payload = json.loads(self.rfile.read(length).decode('utf-8'))
            symbol = payload['symbol']
            interval = payload['interval']
            page = int(payload.get('page', 1))
            page_size = int(payload.get('page_size', 100))
            start_ms = bjt_input_to_utc_ms(payload['start_bjt'])
            end_ms = bjt_input_to_utc_ms(payload['end_bjt'])
            self.validate_symbol_interval(symbol, interval)
            if start_ms != FIXED_START_MS or end_ms != FIXED_END_MS:
                raise ValueError('当前平台只支持固定时间区间 20240101 到 20260301')
            if page_size <= 0 or page_size > 1000:
                raise ValueError('page_size 需在 1 到 1000 之间')
            rows = STORE.query_rows(symbol, interval)
            page_rows, pagination = STORE.paginate_rows(rows, page, page_size)
            return self.send_json({'rows': page_rows, 'pagination': pagination})
        except Exception as exc:
            return self.send_json({'error': str(exc)}, HTTPStatus.BAD_REQUEST)

    def validate_symbol_interval(self, symbol: str, interval: str) -> None:
        if symbol not in ALLOWED_SYMBOLS:
            raise ValueError(f'不支持的币种：{symbol}')
        if interval not in ALLOWED_INTERVALS:
            raise ValueError(f'不支持的周期：{interval}')

    def serve_file(self, path: Path, content_type: str, as_attachment: bool = False):
        if not path.exists():
            return self.send_json({'error': f'文件不存在：{path.name}'}, HTTPStatus.NOT_FOUND)
        data = path.read_bytes()
        self.send_response(HTTPStatus.OK)
        self.send_header('Content-Type', content_type)
        self.send_header('Content-Length', str(len(data)))
        if as_attachment:
            self.send_header('Content-Disposition', f'attachment; filename="{path.name}"')
        self.end_headers()
        self.wfile.write(data)

    def send_json(self, payload, status=HTTPStatus.OK):
        data = json.dumps(payload, ensure_ascii=False).encode('utf-8')
        self.send_response(status)
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        self.send_header('Content-Length', str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, fmt, *args):
        return


if __name__ == '__main__':
    server = ThreadingHTTPServer((HOST, PORT), Handler)
    print(f'Kline readonly platform running on http://{HOST}:{PORT}')
    server.serve_forever()
