#!/usr/bin/env python3
import csv
import json
import mimetypes
import os
import sys
from datetime import datetime, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

BASE_DIR = Path(__file__).resolve().parent
WORKDIR = BASE_DIR.parent.parent
SCRIPTS_DIR = WORKDIR / 'scripts'
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from top15_short_strategy import SHADOW_STRATEGY_LAYERS, compute_short_setup_fields

DATA_DIR = WORKDIR / 'data' / 'top15_tracker'
FRONTEND_DIR = WORKDIR / 'apps' / 'top15-frontend-v2'
LIVE_TRADER_TESTNET_DIR = DATA_DIR / 'live_trader' / 'c_strategy_testnet'
SHORT_STRATEGY_CONFIG_PATH = WORKDIR / 'config' / 'short_strategy.post_confirm_weak_turn_v1.json'
LIVE_TRADER_TESTNET_CONFIG_PATH = WORKDIR / 'config' / 'binance_c_strategy.testnet.json'
KLINES_DIR = DATA_DIR / 'klines'
HOST = os.environ.get('TOP15_BACKEND_HOST', '127.0.0.1')
PORT = int(os.environ.get('TOP15_BACKEND_PORT', '8080'))
KLINE_CACHE = {}


def read_json(path: Path, default=None):
    if not path.exists():
        return default
    return json.loads(path.read_text(encoding='utf-8'))


def read_jsonl_tail(path: Path, limit=50):
    if not path.exists():
        return []
    try:
        lines = [line for line in path.read_text(encoding='utf-8').splitlines() if line.strip()]
    except Exception:
        return []
    out = []
    for line in lines[-max(0, int(limit or 0)):]:
        try:
            item = json.loads(line)
        except Exception:
            continue
        if isinstance(item, dict):
            out.append(item)
    return out


def load_short_strategy_config():
    payload = read_json(SHORT_STRATEGY_CONFIG_PATH, default={}) or {}
    return payload if isinstance(payload, dict) else {}


SHORT_STRATEGY_CONFIG = load_short_strategy_config()
STRUCTURE_CONFIG = SHORT_STRATEGY_CONFIG.get('structure') or {}
RISK_CONFIG = SHORT_STRATEGY_CONFIG.get('risk') or {}
STRATEGY_CONFIG = SHORT_STRATEGY_CONFIG.get('strategy') or {}
STRUCTURE_FRONT_HIGH_LOOKBACK_H = float(STRUCTURE_CONFIG.get('front_high_lookback_h') or 2)
STRUCTURE_VOL_LOOKBACK_H = float(STRUCTURE_CONFIG.get('vol_lookback_h') or 1)
STRUCTURE_ATR_PERIOD = int(STRUCTURE_CONFIG.get('atr_period') or 14)
STRUCTURE_STOP_BUFFER_MULT = float(STRUCTURE_CONFIG.get('stop_buffer_mult') or 0.35)
STRUCTURE_MIN_BUFFER_PCT = float(STRUCTURE_CONFIG.get('min_buffer_pct') or 0.15)
STRUCTURE_STOP_MIN_PCT = float(STRUCTURE_CONFIG.get('stop_window_min_pct') or 0.8)
STRUCTURE_STOP_MAX_PCT = float(STRUCTURE_CONFIG.get('stop_window_max_pct') or 4.5)


def safe_float(value):
    try:
        num = float(value)
    except (TypeError, ValueError):
        return None
    return num if num == num else None


def parse_dt(value):
    if not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


def load_symbol_1h_klines(symbol: str):
    symbol = (symbol or '').upper()
    if symbol in KLINE_CACHE:
        return KLINE_CACHE[symbol]

    path = KLINES_DIR / symbol / '1h' / 'candles.csv'
    rows = []
    if path.exists():
        with path.open('r', encoding='utf-8', newline='') as handle:
            reader = csv.DictReader(handle)
            for row in reader:
                open_dt = parse_dt(row.get('open_time_utc'))
                close_dt = parse_dt(row.get('close_time_utc'))
                high = safe_float(row.get('high_price'))
                low = safe_float(row.get('low_price'))
                close = safe_float(row.get('close_price'))
                if not open_dt or not close_dt or high is None or low is None or close is None:
                    continue
                rows.append({
                    'open_dt': open_dt,
                    'close_dt': close_dt,
                    'high': high,
                    'low': low,
                    'close': close,
                })
    rows.sort(key=lambda item: item['open_dt'])
    KLINE_CACHE[symbol] = rows
    return rows


def compute_atr_1h_pct(candles, entry_dt, entry_price):
    if entry_price in (None, 0):
        return None

    closed = [candle for candle in candles if candle['close_dt'] <= entry_dt]
    if len(closed) < STRUCTURE_ATR_PERIOD + 1:
        return None

    true_ranges = []
    prev_close = closed[0]['close']
    for candle in closed[1:]:
        true_ranges.append(
            max(
                candle['high'] - candle['low'],
                abs(candle['high'] - prev_close),
                abs(candle['low'] - prev_close),
            )
        )
        prev_close = candle['close']

    recent_trs = true_ranges[-STRUCTURE_ATR_PERIOD:]
    if len(recent_trs) < STRUCTURE_ATR_PERIOD:
        return None

    atr_abs = sum(recent_trs) / len(recent_trs)
    return (atr_abs / entry_price) * 100 if entry_price else None


def compute_structure_context(row):
    entry_dt = parse_dt(row.get('captured_at_utc'))
    entry_price = safe_float(row.get('binance_last_price')) or safe_float(row.get('price_usd'))
    if not entry_dt or entry_price in (None, 0):
        return {}

    candles = load_symbol_1h_klines(row.get('symbol'))
    if not candles:
        return {}

    closed = [candle for candle in candles if candle['close_dt'] <= entry_dt]
    if not closed:
        return {}

    front_cutoff = entry_dt - timedelta(hours=STRUCTURE_FRONT_HIGH_LOOKBACK_H)
    front_highs = [candle['high'] for candle in closed if candle['close_dt'] > front_cutoff]
    front_high_price = max(front_highs) if front_highs else entry_price

    vol_cutoff = entry_dt - timedelta(hours=STRUCTURE_VOL_LOOKBACK_H)
    vol_window = [candle for candle in closed if candle['close_dt'] > vol_cutoff]
    snapshot_range_1h_pct = None
    if vol_window and entry_price:
        window_high = max(candle['high'] for candle in vol_window)
        window_low = min(candle['low'] for candle in vol_window)
        snapshot_range_1h_pct = ((window_high - window_low) / entry_price) * 100

    atr_1h_pct = compute_atr_1h_pct(candles, entry_dt, entry_price)
    vol_base_pct = atr_1h_pct if atr_1h_pct is not None else snapshot_range_1h_pct
    vol_source = 'kline_1h_atr14' if atr_1h_pct is not None else ('kline_1h_range_proxy' if snapshot_range_1h_pct is not None else None)
    stop_anchor_price = max(front_high_price, entry_price)
    stop_buffer_pct = max(STRUCTURE_MIN_BUFFER_PCT, (vol_base_pct or 0) * STRUCTURE_STOP_BUFFER_MULT)
    stop_price = stop_anchor_price * (1 + stop_buffer_pct / 100)
    stop_pct = ((stop_price / entry_price) - 1) * 100 if entry_price else None
    risk_abs = stop_price - entry_price if stop_price is not None else None
    target_price_r1 = entry_price - risk_abs if risk_abs is not None else None
    tradable = stop_pct is not None and STRUCTURE_STOP_MIN_PCT <= stop_pct <= STRUCTURE_STOP_MAX_PCT

    return {
        'structure_front_high_price': front_high_price,
        'structure_stop_anchor_price': stop_anchor_price,
        'structure_atr_1h_pct': atr_1h_pct,
        'structure_snapshot_range_1h_pct': snapshot_range_1h_pct,
        'structure_vol_base_pct': vol_base_pct,
        'structure_vol_source': vol_source,
        'structure_stop_buffer_pct': stop_buffer_pct,
        'structure_stop_price': stop_price,
        'structure_stop_pct': stop_pct,
        'structure_target_price_r1': target_price_r1,
        'structure_stop_tradable': tradable,
        'structure_stop_window_min_pct': STRUCTURE_STOP_MIN_PCT,
        'structure_stop_window_max_pct': STRUCTURE_STOP_MAX_PCT,
    }


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


def file_response(handler, path: Path):
    if not path.exists() or not path.is_file():
        return text_response(handler, 'Not Found', 404)
    content_type = mimetypes.guess_type(str(path))[0] or 'application/octet-stream'
    if content_type.startswith('text/') or content_type in ('application/javascript', 'application/json'):
        content_type += '; charset=utf-8'
    data = path.read_bytes()
    handler.send_response(200)
    handler.send_header('Content-Type', content_type)
    handler.send_header('Content-Length', str(len(data)))
    handler.end_headers()
    handler.wfile.write(data)


def latest_manifest():
    return read_json(DATA_DIR / 'latest' / 'manifest.json', default={}) or {}


def latest_display():
    return read_json(DATA_DIR / 'display' / 'latest_display.json', default=[]) or []


def latest_analysis():
    rows = read_json(DATA_DIR / 'latest' / 'latest.json', default=[]) or []
    enriched_rows = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        if row.get('short_strategy_version') and row.get('structure_stop_pct') is not None:
            enriched_rows.append(row)
            continue
        try:
            enriched_rows.append({**row, **compute_short_setup_fields(row)})
        except Exception:
            enriched_rows.append({**row, **compute_structure_context(row)})
    return enriched_rows


def latest_paper_trader():
    payload = read_json(DATA_DIR / 'paper_trader' / 'latest.json', default=None)
    strategy_books = {}
    for strategy_id, layer in SHADOW_STRATEGY_LAYERS.items():
        strategy_books[strategy_id] = {
            'strategy_id': strategy_id,
            'strategy_code': layer.get('code'),
            'strategy_label': layer.get('label'),
            'description': layer.get('description'),
            'entry_live': True,
            'entry_armed_snapshot_id': None,
            'entry_armed_at': None,
            'config': {
                'strategy_id': strategy_id,
                'strategy_code': layer.get('code'),
                'strategy_label': layer.get('label'),
                'signal_name': layer.get('signal_name'),
                'entry_filters': list(layer.get('entry_filters') or []),
                'initial_equity_usd': safe_float(RISK_CONFIG.get('initial_equity_usd')) or 10000.0,
                'risk_pct': safe_float(RISK_CONFIG.get('risk_pct')) or 5.0,
                'max_concurrent': int(RISK_CONFIG.get('max_concurrent') or 3),
                'max_gross_pct': safe_float(RISK_CONFIG.get('max_gross_pct')) or 200.0,
                'leverage': safe_float(RISK_CONFIG.get('leverage')) or 2.0,
                'max_hold_hours': safe_float(STRUCTURE_CONFIG.get('max_hold_hours')) or 12.0,
                'stop_window_min_pct': safe_float(layer.get('stop_window_min_pct')) or STRUCTURE_STOP_MIN_PCT,
                'stop_window_max_pct': safe_float(layer.get('stop_window_max_pct')) or STRUCTURE_STOP_MAX_PCT,
                'target_r_multiple': safe_float(layer.get('target_r_multiple')) or 1.0,
            },
            'summary': {
                'starting_equity_usd': safe_float(RISK_CONFIG.get('initial_equity_usd')) or 10000.0,
                'equity_usd': safe_float(RISK_CONFIG.get('initial_equity_usd')) or 10000.0,
                'realized_pnl_usd': 0.0,
                'unrealized_pnl_usd': 0.0,
                'open_gross_usd': 0.0,
                'gross_cap_usd': 0.0,
                'open_count': 0,
                'closed_count': 0,
                'win_count': 0,
                'loss_count': 0,
                'total_realized_r': 0.0,
                'win_rate': None,
            },
            'open_orders': [],
            'recent_closed_orders': [],
            'recent_events': [],
            'recent_equity_curve': [],
        }
    if isinstance(payload, dict):
        if payload.get('strategy_books'):
            return payload
        legacy = dict(payload)
        strategy_books['A_post_confirm_weak_turn'] = {
            **strategy_books['A_post_confirm_weak_turn'],
            'config': {
                **strategy_books['A_post_confirm_weak_turn']['config'],
                **(legacy.get('config') or {}),
                'signal_name': 'post_confirm_weak_turn',
                'entry_filters': ['no_breakout_1h', 'chg_3_8'],
            },
            'summary': {
                **strategy_books['A_post_confirm_weak_turn']['summary'],
                **(legacy.get('summary') or {}),
            },
            'open_orders': list(legacy.get('open_orders') or []),
            'recent_closed_orders': list(legacy.get('recent_closed_orders') or []),
            'recent_events': list(legacy.get('recent_events') or []),
            'recent_equity_curve': list(legacy.get('recent_equity_curve') or []),
        }
        return {
            **legacy,
            'config': {
                'initial_equity_usd': safe_float(RISK_CONFIG.get('initial_equity_usd')) or 10000.0,
                'risk_pct': safe_float(RISK_CONFIG.get('risk_pct')) or 5.0,
                'max_concurrent': int(RISK_CONFIG.get('max_concurrent') or 3),
                'max_gross_pct': safe_float(RISK_CONFIG.get('max_gross_pct')) or 200.0,
                'leverage': safe_float(RISK_CONFIG.get('leverage')) or 2.0,
                'max_hold_hours': safe_float(STRUCTURE_CONFIG.get('max_hold_hours')) or 12.0,
                'stop_window_min_pct': STRUCTURE_STOP_MIN_PCT,
                'stop_window_max_pct': STRUCTURE_STOP_MAX_PCT,
                'strategy_ids': list(SHADOW_STRATEGY_LAYERS.keys()),
            },
            'summary': {
                **(legacy.get('summary') or {}),
                'strategy_book_count': len(SHADOW_STRATEGY_LAYERS),
            },
            'strategy_books': strategy_books,
        }
    return {
        'ok': True,
        'version': SHORT_STRATEGY_CONFIG.get('paper_trader_version') or 'server_paper_trader_v6_shadow_books_controls_live_launch',
        'config': {
            'initial_equity_usd': safe_float(RISK_CONFIG.get('initial_equity_usd')) or 10000.0,
            'risk_pct': safe_float(RISK_CONFIG.get('risk_pct')) or 5.0,
            'max_concurrent': int(RISK_CONFIG.get('max_concurrent') or 3),
            'max_gross_pct': safe_float(RISK_CONFIG.get('max_gross_pct')) or 200.0,
            'leverage': safe_float(RISK_CONFIG.get('leverage')) or 2.0,
            'max_hold_hours': safe_float(STRUCTURE_CONFIG.get('max_hold_hours')) or 12.0,
            'stop_window_min_pct': STRUCTURE_STOP_MIN_PCT,
            'stop_window_max_pct': STRUCTURE_STOP_MAX_PCT,
            'strategy_ids': list(SHADOW_STRATEGY_LAYERS.keys()),
        },
        'last_processed_snapshot_id': None,
        'last_processed_at': None,
        'summary': {
            'starting_equity_usd': (safe_float(RISK_CONFIG.get('initial_equity_usd')) or 10000.0) * len(SHADOW_STRATEGY_LAYERS),
            'equity_usd': (safe_float(RISK_CONFIG.get('initial_equity_usd')) or 10000.0) * len(SHADOW_STRATEGY_LAYERS),
            'realized_pnl_usd': 0.0,
            'unrealized_pnl_usd': 0.0,
            'open_gross_usd': 0.0,
            'gross_cap_usd': 0.0,
            'open_count': 0,
            'closed_count': 0,
            'win_count': 0,
            'loss_count': 0,
            'total_realized_r': 0.0,
            'win_rate': None,
            'strategy_book_count': len(SHADOW_STRATEGY_LAYERS),
        },
        'open_orders': [],
        'recent_closed_orders': [],
        'recent_events': [],
        'recent_equity_curve': [],
        'strategy_books': strategy_books,
    }


def latest_live_trader_testnet():
    payload = read_json(LIVE_TRADER_TESTNET_DIR / 'latest.json', default=None)
    if isinstance(payload, dict):
        return payload

    config = read_json(LIVE_TRADER_TESTNET_CONFIG_PATH, default={}) or {}
    state = read_json(LIVE_TRADER_TESTNET_DIR / 'state.json', default={}) or {}
    events = read_jsonl_tail(LIVE_TRADER_TESTNET_DIR / 'journal.jsonl', 40)
    events.sort(key=lambda item: item.get('ts') or '', reverse=True)
    active_trades = state.get('active_trades') or {}
    positions = []
    for symbol, trade in active_trades.items():
        if not isinstance(trade, dict):
            continue
        entry = trade.get('entry') or {}
        structure = trade.get('structure') or {}
        positions.append({
            'symbol': symbol,
            'opened_at': trade.get('opened_at'),
            'snapshot_id': trade.get('snapshot_id'),
            'signal_summary': trade.get('signal_summary'),
            'quality_score': safe_float(trade.get('quality_score')),
            'entry_price': safe_float(entry.get('avg_price')),
            'entry_qty': safe_float(entry.get('executed_qty')),
            'entry_notional_usd': safe_float(entry.get('notional_usd')),
            'mark_price': None,
            'position_qty': safe_float(entry.get('executed_qty')),
            'position_notional_usd': safe_float(entry.get('notional_usd')),
            'unrealized_pnl_usd': None,
            'unrealized_pnl_pct': None,
            'stop_price': safe_float(structure.get('stop_price')),
            'target_price': safe_float(structure.get('target_price')),
            'stop_pct': safe_float(structure.get('stop_pct')),
            'front_high_price': safe_float(structure.get('front_high_price')),
            'atr_1h_pct': safe_float(structure.get('atr_1h_pct')),
            'protection': trade.get('protection') or {},
            'algo_orders': [],
        })
    positions.sort(key=lambda item: item.get('opened_at') or '', reverse=True)

    starting_capital_usd = safe_float(((config.get('reporting') or {}).get('starting_capital_usd'))) or 4941.0
    return {
        'ok': True,
        'version': state.get('version') or 'c_strategy_testnet_v1',
        'account_label': config.get('account_label') or 'binance_c_strategy_testnet',
        'strategy_id': ((config.get('strategy') or {}).get('strategy_id')) or 'C_overheat_fade',
        'enabled': bool(config.get('enabled')),
        'snapshot_id': state.get('last_processed_snapshot_id'),
        'last_run_at': state.get('last_run_at'),
        'starting_capital_usd': starting_capital_usd,
        'account': {
            'equity_usd': starting_capital_usd,
            'available_balance_usd': starting_capital_usd,
            'open_gross_usd': sum(safe_float(item.get('position_notional_usd')) or 0.0 for item in positions),
            'gross_cap_usd': None,
        },
        'summary': {
            'starting_capital_usd': starting_capital_usd,
            'equity_usd': starting_capital_usd,
            'total_pnl_usd': 0.0,
            'realized_pnl_usd': 0.0,
            'unrealized_pnl_usd': 0.0,
            'roi_pct': 0.0,
            'open_count': len(positions),
            'recent_event_count': len(events),
        },
        'positions': positions,
        'recent_events': events,
        'runtime': {
            'candidate_count': None,
            'candidate_preview': [],
            'warnings': ['live trader latest.json 尚未生成，当前为 state/journal 兜底视图。'],
            'opened': [],
            'closed': [],
            'failed': [],
        },
    }


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

        if path == '/api/paper-trader':
            return json_response(self, {
                'ok': True,
                'paper_trader': latest_paper_trader(),
            })

        if path == '/api/live-trader-testnet':
            return json_response(self, {
                'ok': True,
                'live_trader_testnet': latest_live_trader_testnet(),
            })

        if path == '/api/short-strategy-config':
            return json_response(self, {
                'ok': True,
                'config': SHORT_STRATEGY_CONFIG,
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

        if path in ('/', '/index.html'):
            return file_response(self, FRONTEND_DIR / 'index.html')
        if path == '/app.js':
            return file_response(self, FRONTEND_DIR / 'app.js')
        if path == '/styles.css':
            return file_response(self, FRONTEND_DIR / 'styles.css')

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
        'frontend_dir': str(FRONTEND_DIR),
    }, ensure_ascii=False))
    server.serve_forever()
