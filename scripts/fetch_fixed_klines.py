#!/usr/bin/env python3
import argparse
import csv
import json
import sys
import time
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

BINANCE_URL = 'https://fapi.binance.com/fapi/v1/klines'
TZ_BJT = timezone(timedelta(hours=8))
FIXED_START_MS = int(datetime(2024, 1, 1, tzinfo=timezone.utc).timestamp() * 1000)
FIXED_END_MS = int(datetime(2026, 3, 1, tzinfo=timezone.utc).timestamp() * 1000)
INTERVAL_MS = {
    '15m': 15 * 60 * 1000,
    '1h': 60 * 60 * 1000,
    '4h': 4 * 60 * 60 * 1000,
}
EMA_PERIODS = [5, 21, 144]
MAX_LIMIT = 1000
DEFAULT_SLEEP = 0.18
ROOT = Path(__file__).resolve().parents[1]
RAW_DIR = ROOT / 'data' / 'klines_platform' / 'raw'
META_DIR = ROOT / 'data' / 'klines_platform' / 'meta'

RAW_DIR.mkdir(parents=True, exist_ok=True)
META_DIR.mkdir(parents=True, exist_ok=True)


def ms_to_bjt(ms: int) -> str:
    return datetime.fromtimestamp(ms / 1000, tz=timezone.utc).astimezone(TZ_BJT).strftime('%Y-%m-%d %H:%M:%S BJT')


def ema_sequence(closes, period: int):
    alpha = 2 / (period + 1)
    out = []
    prev = None
    for close in closes:
        prev = close if prev is None else close * alpha + prev * (1 - alpha)
        out.append(prev)
    return out


def compute_warmup_bars(interval: str, max_period: int = 144) -> dict:
    multiplier_map = {
        '15m': 14,
        '1h': 10,
        '4h': 8,
    }
    floor_map = {
        '15m': 2000,
        '1h': 1500,
        '4h': 1000,
    }
    multiplier = multiplier_map[interval]
    floor_value = floor_map[interval]
    recommended = max(floor_value, max_period * multiplier)
    return {
        'warmup_bars': recommended,
        'multiplier': multiplier,
        'floor': floor_value,
        'max_period': max_period,
    }


def fetch_klines(symbol: str, interval: str, start_ms: int, end_ms: int, sleep_sec: float):
    opener = urllib.request.build_opener()
    opener.addheaders = [('User-Agent', 'Mozilla/5.0 OpenClaw Binance Fetcher')]
    rows = []
    current = start_ms
    requests_count = 0
    step_ms = INTERVAL_MS[interval]
    while current <= end_ms:
        query = urllib.parse.urlencode({
            'symbol': symbol,
            'interval': interval,
            'startTime': current,
            'endTime': end_ms,
            'limit': MAX_LIMIT,
        })
        url = f'{BINANCE_URL}?{query}'
        with opener.open(url, timeout=30) as resp:
            payload = json.loads(resp.read().decode('utf-8'))
        requests_count += 1
        if not payload:
            break
        rows.extend(payload)
        next_current = int(payload[-1][0]) + step_ms
        if next_current <= current:
            break
        current = next_current
        print(f'[fetch] req={requests_count} rows={len(rows)} current={ms_to_bjt(int(payload[-1][0]))}', flush=True)
        time.sleep(sleep_sec)
    return rows, requests_count


def write_csv(symbol: str, interval: str, rows):
    path = RAW_DIR / f'{symbol}_{interval}.csv'
    closes = [float(r[4]) for r in rows]
    ema_map = {period: ema_sequence(closes, period) for period in EMA_PERIODS}
    with path.open('w', encoding='utf-8', newline='') as f:
        writer = csv.writer(f)
        writer.writerow([
            'open_time_ms', 'open_time_bjt', 'open', 'high', 'low', 'close', 'volume',
            'close_time_ms', 'quote_asset_volume', 'number_of_trades',
            'taker_buy_base_asset_volume', 'taker_buy_quote_asset_volume',
            'ema5', 'ema21', 'ema144'
        ])
        for idx, row in enumerate(rows):
            writer.writerow([
                int(row[0]),
                ms_to_bjt(int(row[0])),
                row[1], row[2], row[3], row[4], row[5], row[6], row[7], row[8], row[9], row[10],
                f'{ema_map[5][idx]:.8f}', f'{ema_map[21][idx]:.8f}', f'{ema_map[144][idx]:.8f}',
            ])
    return path


def write_meta(symbol: str, interval: str, raw_rows, request_count: int, warmup_info: dict, warmup_start_ms: int):
    path = META_DIR / f'{symbol}_{interval}.json'
    data = {
        'symbol': symbol,
        'interval': interval,
        'fixed_start_ms': FIXED_START_MS,
        'fixed_end_ms': FIXED_END_MS,
        'fixed_start_bjt': ms_to_bjt(FIXED_START_MS),
        'fixed_end_bjt': ms_to_bjt(FIXED_END_MS),
        'ema_periods': EMA_PERIODS,
        'warmup_strategy': 'max(floor_by_interval, ema_max_period * multiplier_by_interval)',
        'warmup_bars': warmup_info['warmup_bars'],
        'warmup_multiplier': warmup_info['multiplier'],
        'warmup_floor': warmup_info['floor'],
        'warmup_max_period': warmup_info['max_period'],
        'warmup_start_ms': warmup_start_ms,
        'warmup_start_bjt': ms_to_bjt(warmup_start_ms),
        'row_count_total': len(raw_rows),
        'row_count_visible': sum(1 for r in raw_rows if FIXED_START_MS <= int(r[0]) <= FIXED_END_MS),
        'request_count': request_count,
        'generated_at_utc': datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC'),
    }
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')
    return path


def main():
    parser = argparse.ArgumentParser(description='Fetch fixed-range Binance futures klines with stable EMA warmup')
    parser.add_argument('--symbol', required=True, help='e.g. BTCUSDT')
    parser.add_argument('--interval', required=True, choices=sorted(INTERVAL_MS.keys()))
    parser.add_argument('--sleep', type=float, default=DEFAULT_SLEEP, help='sleep seconds between Binance requests')
    parser.add_argument('--warmup-bars', type=int, default=0, help='manual override; 0 means use interval strategy')
    args = parser.parse_args()

    symbol = args.symbol.upper()
    interval = args.interval
    warmup_info = compute_warmup_bars(interval, max(EMA_PERIODS))
    warmup_bars = args.warmup_bars if args.warmup_bars > 0 else warmup_info['warmup_bars']
    if args.warmup_bars > 0:
        warmup_info = {
            **warmup_info,
            'warmup_bars': warmup_bars,
        }
    warmup_start_ms = max(0, FIXED_START_MS - INTERVAL_MS[interval] * warmup_bars)

    print(f'[start] symbol={symbol} interval={interval}', flush=True)
    print(f'[range] visible={ms_to_bjt(FIXED_START_MS)} -> {ms_to_bjt(FIXED_END_MS)}', flush=True)
    print(
        f"[warmup] strategy=max(floor, period*multiplier) bars={warmup_bars} floor={warmup_info['floor']} multiplier={warmup_info['multiplier']} warmup_start={ms_to_bjt(warmup_start_ms)}",
        flush=True,
    )

    rows, request_count = fetch_klines(symbol, interval, warmup_start_ms, FIXED_END_MS, args.sleep)
    if not rows:
        print('[error] no rows fetched', file=sys.stderr, flush=True)
        sys.exit(1)

    rows.sort(key=lambda x: int(x[0]))
    dedup = []
    seen = set()
    for row in rows:
        open_ms = int(row[0])
        if open_ms in seen:
            continue
        seen.add(open_ms)
        dedup.append(row)

    csv_path = write_csv(symbol, interval, dedup)
    meta_path = write_meta(symbol, interval, dedup, request_count, warmup_info, warmup_start_ms)

    visible_rows = sum(1 for r in dedup if FIXED_START_MS <= int(r[0]) <= FIXED_END_MS)
    print(f'[done] total_rows={len(dedup)} visible_rows={visible_rows} requests={request_count}', flush=True)
    print(f'[done] csv={csv_path}', flush=True)
    print(f'[done] meta={meta_path}', flush=True)


if __name__ == '__main__':
    main()
