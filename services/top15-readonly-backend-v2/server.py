#!/usr/bin/env python3
import csv
import json
import mimetypes
import os
import sys
from datetime import datetime, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

BASE_DIR = Path(__file__).resolve().parent
WORKDIR = BASE_DIR.parent.parent
SCRIPTS_DIR = WORKDIR / 'scripts'
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from top15_short_strategy import SHADOW_STRATEGY_LAYERS, compute_short_setup_fields

DATA_DIR = WORKDIR / 'data' / 'top15_tracker'
FRONTEND_DIR = WORKDIR / 'apps' / 'top15-frontend-v2'
LIVE_TRADER_TESTNET_DIR = DATA_DIR / 'live_trader' / 'c_strategy_testnet'
LIVE_TRADER_ACCOUNTS_DIR = DATA_DIR / 'live_trader' / 'accounts'
SHORT_STRATEGY_CONFIG_PATH = WORKDIR / 'config' / 'short_strategy.post_confirm_weak_turn_v1.json'
LIVE_TRADER_TESTNET_CONFIG_PATH = WORKDIR / 'config' / 'binance_c_strategy.testnet.json'
LIVE_TRADER_ACCOUNTS_CONFIG_DIR = WORKDIR / 'config' / 'live_trader_accounts'
KLINES_DIR = DATA_DIR / 'klines'
HOST = os.environ.get('TOP15_BACKEND_HOST', '127.0.0.1')
PORT = int(os.environ.get('TOP15_BACKEND_PORT', '8080'))
KLINE_CACHE = {}


def read_json(path: Path, default=None):
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding='utf-8'))
    except Exception:
        return default


def write_json(path: Path, payload):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding='utf-8')


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


def slugify_account_id(value):
    text = str(value or '').strip().lower()
    chars = []
    for char in text:
        if char.isalnum():
            chars.append(char)
        elif char in {'-', '_', '.'}:
            chars.append('-')
    slug = ''.join(chars).strip('-')
    while '--' in slug:
        slug = slug.replace('--', '-')
    return slug or 'default'


def resolve_account_id(config, config_path: Path):
    explicit = (config or {}).get('account_id') or (config or {}).get('runtime_dirname')
    if explicit:
        return slugify_account_id(explicit)
    if config_path.name == LIVE_TRADER_TESTNET_CONFIG_PATH.name:
        return 'c_strategy_testnet'
    return slugify_account_id(config_path.stem)


def iter_live_account_configs():
    if not LIVE_TRADER_ACCOUNTS_CONFIG_DIR.exists():
        return []
    items = []
    for path in sorted(LIVE_TRADER_ACCOUNTS_CONFIG_DIR.glob('*.json')):
        if '.example.' in path.name:
            continue
        raw = read_json(path, default=None)
        if not isinstance(raw, dict):
            continue
        account_id = resolve_account_id(raw, path)
        items.append({
            'account_id': account_id,
            'config_path': path,
            'config': raw,
            'runtime_dir': LIVE_TRADER_ACCOUNTS_DIR / account_id,
        })
    return items


def find_live_account_config(account_id):
    target = slugify_account_id(account_id)
    for item in iter_live_account_configs():
        if item['account_id'] == target:
            return item
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


def load_paper_trader_recent_curves(per_strategy_limit=96, aggregate_limit=144):
    path = DATA_DIR / 'paper_trader' / 'equity_curve.csv'
    curves = {}
    if not path.exists():
        return curves

    try:
        with path.open('r', encoding='utf-8', newline='') as handle:
            rows = [dict(row) for row in csv.DictReader(handle) if isinstance(row, dict)]
    except Exception:
        return curves

    for row in rows:
        strategy_id = row.get('strategy_id')
        if not strategy_id:
            continue
        curves.setdefault(strategy_id, []).append(row)

    for strategy_id, items in list(curves.items()):
        items.sort(key=lambda item: item.get('captured_at_utc') or '')
        limit = aggregate_limit if strategy_id == 'aggregate' else per_strategy_limit
        curves[strategy_id] = items[-limit:]

    return curves


def load_paper_trader_curve_history(strategy_id='aggregate', interval_hours=4):
    path = DATA_DIR / 'paper_trader' / 'equity_curve.csv'
    if not path.exists():
        return []

    try:
        bucket_ms = max(1, int(float(interval_hours or 4) * 60 * 60 * 1000))
    except (TypeError, ValueError):
        bucket_ms = 4 * 60 * 60 * 1000

    rows = []
    try:
        with path.open('r', encoding='utf-8', newline='') as handle:
            for row in csv.DictReader(handle):
                if not isinstance(row, dict):
                    continue
                if (row.get('strategy_id') or '') != strategy_id:
                    continue
                captured_at = row.get('captured_at_utc')
                dt = parse_dt(captured_at)
                if not dt:
                    continue
                rows.append({
                    **row,
                    '_ts_ms': int(dt.timestamp() * 1000),
                })
    except Exception:
        return []

    rows.sort(key=lambda item: item['_ts_ms'])
    if not rows:
        return []

    sampled = []
    current_bucket = None
    last_in_bucket = None
    for row in rows:
        bucket = row['_ts_ms'] // bucket_ms
        if current_bucket is None:
            current_bucket = bucket
        if bucket != current_bucket:
            if last_in_bucket is not None:
                sampled.append({key: value for key, value in last_in_bucket.items() if key != '_ts_ms'})
            current_bucket = bucket
        last_in_bucket = row

    if last_in_bucket is not None:
        sampled.append({key: value for key, value in last_in_bucket.items() if key != '_ts_ms'})

    return sampled


def sample_curve_rows(rows, interval_hours=4):
    try:
        bucket_ms = max(1, int(float(interval_hours or 4) * 60 * 60 * 1000))
    except (TypeError, ValueError):
        bucket_ms = 4 * 60 * 60 * 1000

    normalized = []
    for row in rows or []:
        if not isinstance(row, dict):
            continue
        dt = parse_dt(row.get('captured_at_utc'))
        if not dt:
            continue
        normalized.append({**row, '_ts_ms': int(dt.timestamp() * 1000)})

    normalized.sort(key=lambda item: item['_ts_ms'])
    if not normalized:
        return []

    sampled = []
    current_bucket = None
    last_in_bucket = None
    for row in normalized:
        bucket = row['_ts_ms'] // bucket_ms
        if current_bucket is None:
            current_bucket = bucket
        if bucket != current_bucket:
            if last_in_bucket is not None:
                sampled.append({key: value for key, value in last_in_bucket.items() if key != '_ts_ms'})
            current_bucket = bucket
        last_in_bucket = row

    if last_in_bucket is not None:
        sampled.append({key: value for key, value in last_in_bucket.items() if key != '_ts_ms'})

    return sampled


def iso_to_cst(utc_value):
    dt = parse_dt(utc_value)
    if not dt:
        return None
    return (dt + timedelta(hours=8)).isoformat()


def compute_live_trade_pnl(open_event, close_event):
    open_entry = (open_event or {}).get('entry') or {}
    open_resp = open_entry.get('response') or {}
    close_resp = (close_event or {}).get('close_response') or {}

    entry_price = safe_float(open_entry.get('avg_price'))
    if entry_price is None:
        entry_price = safe_float(open_resp.get('avgPrice'))

    close_price = safe_float(close_resp.get('avgPrice'))
    qty = safe_float(close_resp.get('executedQty'))
    if qty is None:
        qty = safe_float(open_entry.get('executed_qty'))
    if qty is None:
        qty = safe_float(open_resp.get('executedQty'))

    if entry_price is None or close_price is None or qty is None:
        return None
    return (entry_price - close_price) * qty


def load_live_curve_rows(runtime_dir: Path):
    path = runtime_dir / 'equity_curve.csv'
    rows = []
    if not path.exists():
        return rows
    try:
        with path.open('r', encoding='utf-8', newline='') as handle:
            for row in csv.DictReader(handle):
                if not isinstance(row, dict):
                    continue
                captured_at = row.get('captured_at_utc')
                if not parse_dt(captured_at):
                    continue
                rows.append(dict(row))
    except Exception:
        return []
    rows.sort(key=lambda item: item.get('captured_at_utc') or '')
    return rows


def build_live_trade_stats(runtime_dir, starting_capital_usd, current_equity_usd, current_unrealized_pnl_usd, last_run_at, current_open_count=None):
    events = read_jsonl_tail(runtime_dir / 'journal.jsonl', 100000)
    events = [item for item in events if isinstance(item, dict)]
    events.sort(key=lambda item: item.get('ts') or '')

    open_events_by_symbol = {}
    closed_count = 0
    opened_count = 0
    matched_closed_count = 0
    win_count = 0
    loss_count = 0
    realized_equity_usd = starting_capital_usd
    curve_rows = load_live_curve_rows(runtime_dir)
    use_event_curve_fallback = not curve_rows

    first_ts = (events[0].get('ts') if events else None) or last_run_at
    if use_event_curve_fallback and first_ts:
        curve_rows.append({
            'captured_at_utc': first_ts,
            'captured_at_cst': iso_to_cst(first_ts),
            'equity_usd': starting_capital_usd,
            'realized_pnl_usd': 0.0,
            'unrealized_pnl_usd': 0.0,
            'open_count': 0,
            'closed_count': 0,
            'win_count': 0,
            'loss_count': 0,
        })

    for event in events:
        event_type = event.get('event_type')
        symbol = event.get('symbol')
        if event_type == 'trade_opened':
            opened_count += 1
            if symbol:
                open_events_by_symbol.setdefault(symbol, []).append(event)
            continue

        if event_type not in ('trade_closed', 'trade_closed_without_market_exit'):
            continue

        closed_count += 1
        pnl_usd = None
        if symbol and open_events_by_symbol.get(symbol):
            open_event = open_events_by_symbol[symbol].pop(0)
            pnl_usd = compute_live_trade_pnl(open_event, event)
            if pnl_usd is not None:
                matched_closed_count += 1
                realized_equity_usd += pnl_usd
                if pnl_usd > 0:
                    win_count += 1
                elif pnl_usd < 0:
                    loss_count += 1

        if use_event_curve_fallback:
            curve_rows.append({
                'captured_at_utc': event.get('ts'),
                'captured_at_cst': iso_to_cst(event.get('ts')),
                'equity_usd': realized_equity_usd,
                'realized_pnl_usd': realized_equity_usd - starting_capital_usd,
                'unrealized_pnl_usd': 0.0,
                'open_count': max(opened_count - closed_count, 0),
                'closed_count': closed_count,
                'win_count': win_count,
                'loss_count': loss_count,
                'pnl_usd': pnl_usd,
            })

    current_equity_known = current_equity_usd is not None
    current_unrealized_pnl_usd = current_unrealized_pnl_usd if current_unrealized_pnl_usd is not None else 0.0
    current_realized_pnl_usd = (
        current_equity_usd - starting_capital_usd - current_unrealized_pnl_usd
        if current_equity_known
        else None
    )
    current_point_ts = last_run_at or first_ts
    if current_point_ts and current_equity_known:
        current_point = {
            'captured_at_utc': current_point_ts,
            'captured_at_cst': iso_to_cst(current_point_ts),
            'equity_usd': current_equity_usd,
            'realized_pnl_usd': current_realized_pnl_usd,
            'unrealized_pnl_usd': current_unrealized_pnl_usd,
            'open_count': max(int(current_open_count if current_open_count is not None else opened_count - closed_count), 0),
            'closed_count': closed_count,
            'win_count': win_count,
            'loss_count': loss_count,
        }
        if not curve_rows or curve_rows[-1].get('captured_at_utc') != current_point_ts or safe_float(curve_rows[-1].get('equity_usd')) != current_equity_usd:
            curve_rows.append(current_point)
        else:
            curve_rows[-1] = current_point

    equity_values = [safe_float(row.get('equity_usd')) for row in curve_rows]
    equity_values = [value for value in equity_values if value is not None]
    peak = None
    max_drawdown_usd = 0.0
    max_drawdown_pct = None
    for value in equity_values:
        peak = value if peak is None else max(peak, value)
        drawdown_usd = peak - value
        drawdown_pct = (drawdown_usd / peak * 100.0) if peak else None
        if drawdown_usd > max_drawdown_usd:
            max_drawdown_usd = drawdown_usd
            max_drawdown_pct = drawdown_pct

    equity_change_last_snapshot_usd = 0.0
    equity_change_last_snapshot_pct = 0.0
    if len(equity_values) >= 2:
        prev = equity_values[-2]
        curr = equity_values[-1]
        equity_change_last_snapshot_usd = curr - prev
        equity_change_last_snapshot_pct = (equity_change_last_snapshot_usd / prev * 100.0) if prev else None

    return {
        'closed_count': closed_count,
        'total_order_count': opened_count + closed_count,
        'win_count': win_count,
        'loss_count': loss_count,
        'win_rate': (win_count / matched_closed_count) if matched_closed_count else None,
        'equity_peak_usd': peak,
        'max_drawdown_usd': max_drawdown_usd,
        'max_drawdown_pct': max_drawdown_pct,
        'equity_change_last_snapshot_usd': equity_change_last_snapshot_usd,
        'equity_change_last_snapshot_pct': equity_change_last_snapshot_pct,
        'curve_point_count': len(curve_rows),
        'recent_equity_curve': curve_rows[-144:],
        'curve_history': curve_rows,
    }


def enrich_live_trader_payload(payload, runtime_dir):
    if not isinstance(payload, dict):
        return payload

    starting_capital_usd = safe_float(payload.get('starting_capital_usd')) or 4941.0
    account = payload.get('account') or {}
    summary = payload.get('summary') or {}
    current_equity_usd = safe_float(account.get('equity_usd'))
    if current_equity_usd is None:
        current_equity_usd = safe_float(summary.get('equity_usd'))
    current_unrealized_pnl_usd = safe_float(summary.get('unrealized_pnl_usd'))
    stats = build_live_trade_stats(
        runtime_dir=runtime_dir,
        starting_capital_usd=starting_capital_usd,
        current_equity_usd=current_equity_usd,
        current_unrealized_pnl_usd=current_unrealized_pnl_usd,
        last_run_at=payload.get('last_run_at'),
        current_open_count=safe_float(summary.get('open_count')),
    )

    summary_patch = {
        **summary,
        'closed_count': stats['closed_count'],
        'total_order_count': stats['total_order_count'],
        'win_count': stats['win_count'],
        'loss_count': stats['loss_count'],
        'win_rate': stats['win_rate'],
        'equity_peak_usd': stats['equity_peak_usd'],
        'max_drawdown_usd': stats['max_drawdown_usd'],
        'max_drawdown_pct': stats['max_drawdown_pct'],
        'equity_change_last_snapshot_usd': stats['equity_change_last_snapshot_usd'],
        'equity_change_last_snapshot_pct': stats['equity_change_last_snapshot_pct'],
        'curve_point_count': stats['curve_point_count'],
    }

    return {
        **payload,
        'summary': summary_patch,
        'recent_equity_curve': stats['recent_equity_curve'],
        '_curve_history': stats['curve_history'],
    }


def latest_paper_trader():
    payload = read_json(DATA_DIR / 'paper_trader' / 'latest.json', default=None)
    curve_rows_by_strategy = load_paper_trader_recent_curves()
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
                'total_order_count': 0,
                'equity_peak_usd': safe_float(RISK_CONFIG.get('initial_equity_usd')) or 10000.0,
                'max_drawdown_usd': 0.0,
                'max_drawdown_pct': 0.0,
                'equity_change_last_snapshot_usd': 0.0,
                'equity_change_last_snapshot_pct': 0.0,
                'curve_point_count': 0,
            },
            'open_orders': [],
            'recent_closed_orders': [],
            'recent_events': [],
            'recent_equity_curve': list(curve_rows_by_strategy.get(strategy_id) or []),
        }
    if isinstance(payload, dict):
        if payload.get('strategy_books'):
            if curve_rows_by_strategy:
                payload = {**payload}
                payload['recent_equity_curve'] = list(curve_rows_by_strategy.get('aggregate') or payload.get('recent_equity_curve') or [])
                patched_books = {}
                for strategy_id, book in (payload.get('strategy_books') or {}).items():
                    patched_books[strategy_id] = {
                        **book,
                        'recent_equity_curve': list(curve_rows_by_strategy.get(strategy_id) or book.get('recent_equity_curve') or []),
                    }
                payload['strategy_books'] = patched_books
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
            'recent_equity_curve': list(curve_rows_by_strategy.get('A_post_confirm_weak_turn') or legacy.get('recent_equity_curve') or []),
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
            'recent_equity_curve': list(curve_rows_by_strategy.get('aggregate') or legacy.get('recent_equity_curve') or []),
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
            'total_order_count': 0,
            'equity_peak_usd': (safe_float(RISK_CONFIG.get('initial_equity_usd')) or 10000.0) * len(SHADOW_STRATEGY_LAYERS),
            'max_drawdown_usd': 0.0,
            'max_drawdown_pct': 0.0,
            'equity_change_last_snapshot_usd': 0.0,
            'equity_change_last_snapshot_pct': 0.0,
            'curve_point_count': 0,
            'strategy_book_count': len(SHADOW_STRATEGY_LAYERS),
        },
        'open_orders': [],
        'recent_closed_orders': [],
        'recent_events': [],
        'recent_equity_curve': list(curve_rows_by_strategy.get('aggregate') or []),
        'strategy_books': strategy_books,
    }


def latest_live_trader_payload(runtime_dir: Path, config_path: Path):
    config = read_json(config_path, default={}) or {}
    account_id = resolve_account_id(config, config_path)

    payload = read_json(runtime_dir / 'latest.json', default=None)
    if isinstance(payload, dict):
        payload = {
            **payload,
            'account_id': account_id,
            'account_label': config.get('account_label') or payload.get('account_label'),
            'enabled': bool(config.get('enabled')),
            'strategy_id': ((config.get('strategy') or {}).get('strategy_id')) or payload.get('strategy_id'),
            'starting_capital_usd': safe_float(((config.get('reporting') or {}).get('starting_capital_usd'))) or payload.get('starting_capital_usd'),
        }
        return enrich_live_trader_payload(payload, runtime_dir)

    state = read_json(runtime_dir / 'state.json', default={}) or {}
    events = read_jsonl_tail(runtime_dir / 'journal.jsonl', 40)
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
    return enrich_live_trader_payload({
        'ok': True,
        'version': state.get('version') or 'c_strategy_testnet_v1',
        'account_id': account_id,
        'account_label': config.get('account_label') or 'binance_c_strategy_testnet',
        'strategy_id': ((config.get('strategy') or {}).get('strategy_id')) or 'C_overheat_fade',
        'enabled': bool(config.get('enabled')),
        'snapshot_id': state.get('last_processed_snapshot_id'),
        'last_run_at': state.get('last_run_at'),
        'starting_capital_usd': starting_capital_usd,
        'account': {
            'equity_usd': None,
            'available_balance_usd': None,
            'open_gross_usd': sum(safe_float(item.get('position_notional_usd')) or 0.0 for item in positions),
            'gross_cap_usd': None,
        },
        'summary': {
            'starting_capital_usd': starting_capital_usd,
            'equity_usd': None,
            'total_pnl_usd': None,
            'realized_pnl_usd': None,
            'unrealized_pnl_usd': None,
            'roi_pct': None,
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
    }, runtime_dir)


def latest_live_trader_testnet():
    return latest_live_trader_payload(LIVE_TRADER_TESTNET_DIR, LIVE_TRADER_TESTNET_CONFIG_PATH)


def latest_live_trader_accounts():
    payloads = []
    for item in iter_live_account_configs():
        payload = latest_live_trader_payload(item['runtime_dir'], item['config_path'])
        if isinstance(payload, dict):
            payloads.append(payload)
    payloads.sort(key=lambda item: (str(item.get('account_label') or ''), str(item.get('account_id') or '')))
    return payloads


def list_snapshots(limit=100):
    raw_dir = DATA_DIR / 'snapshots' / 'raw'
    if not raw_dir.exists():
        return []
    return sorted([p.stem for p in raw_dir.glob('*.json')], reverse=True)[:limit]


class Handler(BaseHTTPRequestHandler):
    def read_json_body(self):
        length = int(self.headers.get('Content-Length') or '0')
        if length <= 0:
            return {}
        raw = self.rfile.read(length)
        if not raw:
            return {}
        try:
            payload = json.loads(raw.decode('utf-8'))
        except Exception:
            return None
        return payload if isinstance(payload, dict) else None

    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path
        query = parse_qs(parsed.query or '')

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

        if path == '/api/paper-trader-curve':
            strategy_id = ((query.get('strategy_id') or ['aggregate'])[0] or 'aggregate').strip()
            interval_hours = (query.get('interval_hours') or ['4'])[0]
            return json_response(self, {
                'ok': True,
                'strategy_id': strategy_id,
                'interval_hours': safe_float(interval_hours) or 4.0,
                'rows': load_paper_trader_curve_history(strategy_id=strategy_id, interval_hours=interval_hours),
            })

        if path == '/api/live-trader-testnet':
            payload = latest_live_trader_testnet() or {}
            if isinstance(payload, dict):
                payload = {key: value for key, value in payload.items() if key != '_curve_history'}
            return json_response(self, {
                'ok': True,
                'live_trader_testnet': payload,
            })

        if path == '/api/live-trader-testnet-curve':
            interval_hours = (query.get('interval_hours') or ['4'])[0]
            payload = latest_live_trader_testnet() or {}
            curve_rows = sample_curve_rows((payload.get('_curve_history') or []), interval_hours=interval_hours)
            return json_response(self, {
                'ok': True,
                'interval_hours': safe_float(interval_hours) or 4.0,
                'rows': curve_rows,
            })

        if path == '/api/live-trader-accounts':
            payloads = []
            for item in latest_live_trader_accounts():
                payloads.append({key: value for key, value in item.items() if key != '_curve_history'})
            return json_response(self, {
                'ok': True,
                'accounts': payloads,
            })

        if path == '/api/live-trader-account':
            account_id = ((query.get('id') or [''])[0] or '').strip()
            account = find_live_account_config(account_id)
            if not account:
                return json_response(self, {'ok': False, 'error': f'account not found: {account_id}'}, status=404)
            payload = latest_live_trader_payload(account['runtime_dir'], account['config_path']) or {}
            if isinstance(payload, dict):
                payload = {key: value for key, value in payload.items() if key != '_curve_history'}
            return json_response(self, {
                'ok': True,
                'account': payload,
            })

        if path == '/api/live-trader-account-curve':
            account_id = ((query.get('id') or [''])[0] or '').strip()
            interval_hours = (query.get('interval_hours') or ['4'])[0]
            account = find_live_account_config(account_id)
            if not account:
                return json_response(self, {'ok': False, 'error': f'account not found: {account_id}'}, status=404)
            payload = latest_live_trader_payload(account['runtime_dir'], account['config_path']) or {}
            curve_rows = sample_curve_rows((payload.get('_curve_history') or []), interval_hours=interval_hours)
            return json_response(self, {
                'ok': True,
                'account_id': account['account_id'],
                'interval_hours': safe_float(interval_hours) or 4.0,
                'rows': curve_rows,
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

    def do_POST(self):
        parsed = urlparse(self.path)
        path = parsed.path

        if path == '/api/live-trader-account-toggle':
            body = self.read_json_body()
            if body is None:
                return json_response(self, {'ok': False, 'error': 'invalid json body'}, status=400)
            account_id = slugify_account_id(body.get('account_id'))
            enabled = body.get('enabled')
            if enabled is None:
                return json_response(self, {'ok': False, 'error': 'enabled is required'}, status=400)
            account = find_live_account_config(account_id)
            if not account:
                return json_response(self, {'ok': False, 'error': f'account not found: {account_id}'}, status=404)
            raw = read_json(account['config_path'], default={}) or {}
            if not isinstance(raw, dict):
                raw = {}
            raw['enabled'] = bool(enabled)
            if not raw.get('account_id'):
                raw['account_id'] = account['account_id']
            write_json(account['config_path'], raw)
            payload = latest_live_trader_payload(account['runtime_dir'], account['config_path']) or {}
            if isinstance(payload, dict):
                payload = {key: value for key, value in payload.items() if key != '_curve_history'}
            return json_response(self, {
                'ok': True,
                'account': payload,
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
        'frontend_dir': str(FRONTEND_DIR),
    }, ensure_ascii=False))
    server.serve_forever()
