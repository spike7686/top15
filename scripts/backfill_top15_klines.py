#!/usr/bin/env python3
import argparse
import csv
import json
import sys
import time
import urllib.parse
import urllib.request
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

HEADERS = {"user-agent": "OpenClaw/1.0", "accept": "application/json"}
WORKDIR = Path(__file__).resolve().parents[1]
DATA_DIR = WORKDIR / "data" / "top15_tracker"
KLINES_DIR = DATA_DIR / "klines"
KLINES_META_DIR = DATA_DIR / "meta" / "klines"
DEFAULT_HISTORY_JSONL = DATA_DIR / "archive" / "local_reset_20260413T151029" / "history.jsonl"
FILTER_RULE = "24h_volume_usd_gt_15m_excluding_stablecoins_binance_spot_only"
CN_TZ = timezone(timedelta(hours=8))
BINANCE_SPOT_KLINES_URL = "https://api.binance.com/api/v3/klines"
KLINE_LIMIT = 1000
INTERVAL_MS = {
    "1h": 60 * 60 * 1000,
}
CSV_FIELDNAMES = [
    "symbol","binance_pair","interval","open_time_ms","open_time_utc","open_time_cst",
    "open_price","high_price","low_price","close_price","volume_base",
    "close_time_ms","close_time_utc","close_time_cst","quote_volume",
    "trade_count","taker_buy_base_volume","taker_buy_quote_volume","source","fetched_at_utc"
]


def safe_json(url, timeout=30):
    req = urllib.request.Request(url, headers=HEADERS)
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.load(resp)


def ts_ms(dt: datetime) -> int:
    return int(dt.timestamp() * 1000)


def load_history_ranges(history_jsonl: Path, symbols=None):
    symbol_set = {symbol.upper() for symbol in (symbols or [])}
    ranges = defaultdict(lambda: {"binance_pair": None, "min_dt": None, "max_dt": None})
    with history_jsonl.open("r", encoding="utf-8") as handle:
        for raw_line in handle:
            line = raw_line.strip()
            if not line:
                continue
            row = json.loads(line)
            if row.get("filter_rule") != FILTER_RULE:
                continue
            symbol = (row.get("symbol") or "").upper()
            if symbol_set and symbol not in symbol_set:
                continue
            pair = (row.get("binance_pair") or "").upper()
            if not pair:
                continue
            dt = datetime.fromisoformat(row["captured_at_utc"])
            item = ranges[symbol]
            item["binance_pair"] = pair
            item["min_dt"] = dt if item["min_dt"] is None or dt < item["min_dt"] else item["min_dt"]
            item["max_dt"] = dt if item["max_dt"] is None or dt > item["max_dt"] else item["max_dt"]
    return dict(ranges)


def klines_csv_path(symbol: str, interval: str) -> Path:
    return KLINES_DIR / symbol.upper() / interval / "candles.csv"


def klines_manifest_path(symbol: str, interval: str) -> Path:
    return KLINES_META_DIR / f"{symbol.upper()}__{interval}.json"


def load_existing_rows(path: Path):
    rows = {}
    if not path.exists():
        return rows
    with path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        for row in reader:
            try:
                rows[int(row["open_time_ms"])] = row
            except Exception:
                continue
    return rows


def write_rows(path: Path, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=CSV_FIELDNAMES)
        writer.writeheader()
        for row in rows:
            writer.writerow({key: row.get(key) for key in CSV_FIELDNAMES})


def fetch_spot_klines(symbol_pair: str, interval: str, start_ms: int, end_ms: int, sleep_sec: float):
    all_rows = []
    step_ms = INTERVAL_MS[interval]
    current = start_ms
    while current < end_ms:
        query = urllib.parse.urlencode(
            {
                "symbol": symbol_pair,
                "interval": interval,
                "startTime": current,
                "endTime": end_ms,
                "limit": KLINE_LIMIT,
            }
        )
        payload = safe_json(f"{BINANCE_SPOT_KLINES_URL}?{query}", timeout=30)
        if not payload:
            break
        all_rows.extend(payload)
        next_open_ms = int(payload[-1][0]) + step_ms
        if next_open_ms <= current:
            break
        current = next_open_ms
        if sleep_sec > 0:
            time.sleep(sleep_sec)
    return all_rows


def normalize_kline_rows(symbol: str, binance_pair: str, interval: str, payload, fetched_at: datetime):
    rows = []
    for item in payload:
        open_time_ms = int(item[0])
        close_time_ms = int(item[6])
        open_dt = datetime.fromtimestamp(open_time_ms / 1000, tz=timezone.utc)
        close_dt = datetime.fromtimestamp(close_time_ms / 1000, tz=timezone.utc)
        rows.append(
            {
                "symbol": symbol.upper(),
                "binance_pair": binance_pair.upper(),
                "interval": interval,
                "open_time_ms": open_time_ms,
                "open_time_utc": open_dt.isoformat(),
                "open_time_cst": open_dt.astimezone(CN_TZ).isoformat(),
                "open_price": item[1],
                "high_price": item[2],
                "low_price": item[3],
                "close_price": item[4],
                "volume_base": item[5],
                "close_time_ms": close_time_ms,
                "close_time_utc": close_dt.isoformat(),
                "close_time_cst": close_dt.astimezone(CN_TZ).isoformat(),
                "quote_volume": item[7],
                "trade_count": item[8],
                "taker_buy_base_volume": item[9],
                "taker_buy_quote_volume": item[10],
                "source": "Binance",
                "fetched_at_utc": fetched_at.isoformat(),
            }
        )
    return rows


def save_manifest(symbol: str, interval: str, binance_pair: str, start_dt: datetime, end_dt: datetime, row_count: int):
    payload = {
        "symbol": symbol.upper(),
        "binance_pair": binance_pair.upper(),
        "interval": interval,
        "backfill_start_utc": start_dt.isoformat(),
        "backfill_end_utc": end_dt.isoformat(),
        "row_count": row_count,
        "updated_at_utc": datetime.now(timezone.utc).isoformat(),
        "csv_path": str(klines_csv_path(symbol, interval).relative_to(WORKDIR)),
    }
    path = klines_manifest_path(symbol, interval)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def main():
    parser = argparse.ArgumentParser(description="Backfill TOP15 spot klines from archived history ranges")
    parser.add_argument("--history-jsonl", default=str(DEFAULT_HISTORY_JSONL), help="Archived history.jsonl path")
    parser.add_argument("--interval", default="1h", choices=sorted(INTERVAL_MS.keys()))
    parser.add_argument("--symbols", nargs="*", help="Optional symbol allowlist")
    parser.add_argument("--warmup-hours", type=int, default=72, help="Extra hours before first seen snapshot")
    parser.add_argument("--tail-hours", type=int, default=24, help="Extra hours after last seen snapshot")
    parser.add_argument("--sleep", type=float, default=0.15, help="Sleep seconds between Binance requests")
    args = parser.parse_args()

    history_jsonl = Path(args.history_jsonl)
    if not history_jsonl.exists():
        raise FileNotFoundError(f"history jsonl not found: {history_jsonl}")

    ranges = load_history_ranges(history_jsonl, args.symbols)
    if not ranges:
        raise RuntimeError("no symbols/ranges found in history jsonl")

    summary = []
    fetched_at = datetime.now(timezone.utc)
    for symbol in sorted(ranges):
        item = ranges[symbol]
        start_dt = item["min_dt"] - timedelta(hours=args.warmup_hours)
        end_dt = item["max_dt"] + timedelta(hours=args.tail_hours)
        payload = fetch_spot_klines(item["binance_pair"], args.interval, ts_ms(start_dt), ts_ms(end_dt), args.sleep)
        normalized_rows = normalize_kline_rows(symbol, item["binance_pair"], args.interval, payload, fetched_at)
        existing = load_existing_rows(klines_csv_path(symbol, args.interval))
        for row in normalized_rows:
            existing[int(row["open_time_ms"])] = row
        merged_rows = [existing[key] for key in sorted(existing)]
        write_rows(klines_csv_path(symbol, args.interval), merged_rows)
        save_manifest(symbol, args.interval, item["binance_pair"], start_dt, end_dt, len(merged_rows))
        summary.append(
            {
                "symbol": symbol,
                "binance_pair": item["binance_pair"],
                "start_utc": start_dt.isoformat(),
                "end_utc": end_dt.isoformat(),
                "fetched_rows": len(normalized_rows),
                "merged_rows": len(merged_rows),
                "csv_path": str(klines_csv_path(symbol, args.interval).relative_to(WORKDIR)),
            }
        )

    print(json.dumps({"ok": True, "history_jsonl": str(history_jsonl.relative_to(WORKDIR)), "interval": args.interval, "symbols": summary}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(json.dumps({"ok": False, "error": repr(exc)}, ensure_ascii=False), file=sys.stderr)
        raise
