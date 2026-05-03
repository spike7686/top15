#!/usr/bin/env python3
from __future__ import annotations

import json
from bisect import bisect_right
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path

import run_wave_short_kline_backtest as base


LAB_DIR = Path(__file__).resolve().parent
PERP_CONTEXT_DIR = LAB_DIR / "input" / "perp_context"


@dataclass(frozen=True)
class Candle:
    symbol: str
    interval: str
    open_dt: datetime
    close_dt: datetime
    open_price: float
    high_price: float
    low_price: float
    close_price: float
    volume: float | None
    quote_volume: float | None
    trades: float | None


@dataclass(frozen=True)
class OIRow:
    symbol: str
    interval: str
    ts: datetime
    oi_qty: float | None
    oi_value_usd: float | None


def safe_float(value):
    return base.safe_float(value)


def parse_dt(value):
    if not value:
        return None
    return datetime.fromisoformat(value)


def interval_delta(interval: str):
    if interval == "15m":
        return timedelta(minutes=15)
    if interval == "1h":
        return timedelta(hours=1)
    raise ValueError(f"unsupported interval: {interval}")


def compute_ema_series(candles, period):
    if not candles:
        return []
    alpha = 2.0 / (period + 1.0)
    ema = None
    out = []
    for candle in candles:
        close_price = candle.close_price
        ema = close_price if ema is None else (close_price * alpha + ema * (1.0 - alpha))
        out.append(ema)
    return out


def load_symbols_meta():
    path = PERP_CONTEXT_DIR / "symbols.ndjson"
    meta = {}
    if not path.exists():
        return meta
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            if not line.strip():
                continue
            row = json.loads(line)
            symbol = str(row.get("symbol") or "").upper()
            if symbol:
                meta[symbol] = row
    return meta


def load_kline_ndjson(path: Path, interval: str):
    rows_by_symbol = {}
    delta = interval_delta(interval)
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            if not line.strip():
                continue
            row = json.loads(line)
            symbol = str(row.get("symbol") or "").upper()
            open_dt = parse_dt(row.get("open_time"))
            if not symbol or open_dt is None:
                continue
            candle = Candle(
                symbol=symbol,
                interval=interval,
                open_dt=open_dt,
                close_dt=open_dt + delta,
                open_price=safe_float(row.get("open")) or 0.0,
                high_price=safe_float(row.get("high")) or 0.0,
                low_price=safe_float(row.get("low")) or 0.0,
                close_price=safe_float(row.get("close")) or 0.0,
                volume=safe_float(row.get("volume")),
                quote_volume=safe_float(row.get("quote_volume")),
                trades=safe_float(row.get("trades")),
            )
            rows_by_symbol.setdefault(symbol, []).append(candle)
    for rows in rows_by_symbol.values():
        rows.sort(key=lambda item: item.close_dt)
    return rows_by_symbol


def load_oi_ndjson(path: Path, interval: str):
    rows_by_symbol = {}
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            if not line.strip():
                continue
            row = json.loads(line)
            symbol = str(row.get("symbol") or "").upper()
            ts = parse_dt(row.get("ts"))
            if not symbol or ts is None:
                continue
            item = OIRow(
                symbol=symbol,
                interval=interval,
                ts=ts,
                oi_qty=safe_float(row.get("sum_open_interest")),
                oi_value_usd=safe_float(row.get("sum_open_interest_value")),
            )
            rows_by_symbol.setdefault(symbol, []).append(item)
    for rows in rows_by_symbol.values():
        rows.sort(key=lambda item: item.ts)
    return rows_by_symbol


def align_oi_values(candles, oi_rows):
    if not candles:
        return []
    if not oi_rows:
        return [None] * len(candles)
    oi_times = [item.ts for item in oi_rows]
    oi_values = [item.oi_value_usd for item in oi_rows]
    out = []
    for candle in candles:
        pos = bisect_right(oi_times, candle.close_dt) - 1
        out.append(oi_values[pos] if pos >= 0 else None)
    return out


def pct_change_by_steps(values, idx, steps):
    if idx < steps:
        return None
    current = safe_float(values[idx])
    previous = safe_float(values[idx - steps])
    if current is None or previous in (None, 0):
        return None
    return ((current - previous) / previous) * 100.0


def latest_window_before(candles, close_times, dt, limit):
    end = bisect_right(close_times, dt)
    if end <= 0:
        return []
    start = max(0, end - limit)
    return candles[start:end]


def build_state(symbol, meta, one_h, fifteen_m, oi_1h_rows, oi_15m_rows):
    if len(one_h) < 200 or len(fifteen_m) < 500:
        return None
    oi_1h_aligned = align_oi_values(one_h, oi_1h_rows)
    oi_15m_aligned = align_oi_values(fifteen_m, oi_15m_rows)
    if sum(1 for value in oi_1h_aligned if value is not None) < 150:
        return None
    return {
        "symbol": symbol,
        "meta": meta or {},
        "1h": one_h,
        "15m": fifteen_m,
        "1h_close_times": [c.close_dt for c in one_h],
        "15m_close_times": [c.close_dt for c in fifteen_m],
        "ema8_1h": compute_ema_series(one_h, 8),
        "ema21_1h": compute_ema_series(one_h, 21),
        "ema55_1h": compute_ema_series(one_h, 55),
        "ema21_15m": compute_ema_series(fifteen_m, 21),
        "oi_1h_rows": oi_1h_rows,
        "oi_15m_rows": oi_15m_rows,
        "oi_value_1h_aligned": oi_1h_aligned,
        "oi_value_15m_aligned": oi_15m_aligned,
    }


def load_perp_context_states():
    meta_by_symbol = load_symbols_meta()
    kline_1h = load_kline_ndjson(PERP_CONTEXT_DIR / "kline_1h.ndjson", "1h")
    kline_15m = load_kline_ndjson(PERP_CONTEXT_DIR / "kline_15m.ndjson", "15m")
    oi_1h = load_oi_ndjson(PERP_CONTEXT_DIR / "oi_1h.ndjson", "1h")
    oi_15m = load_oi_ndjson(PERP_CONTEXT_DIR / "oi_15m.ndjson", "15m")

    symbols = sorted(set(kline_1h) & set(kline_15m) & set(oi_1h) & set(oi_15m))
    states = []
    for symbol in symbols:
        state = build_state(
            symbol=symbol,
            meta=meta_by_symbol.get(symbol),
            one_h=kline_1h[symbol],
            fifteen_m=kline_15m[symbol],
            oi_1h_rows=oi_1h[symbol],
            oi_15m_rows=oi_15m[symbol],
        )
        if state:
            states.append(state)
    return states


def dataset_summary(states):
    if not states:
        return {
            "symbol_count": 0,
            "symbols": [],
            "start_at": None,
            "end_at": None,
        }
    starts = [state["1h"][0].open_dt for state in states if state["1h"]]
    ends = [state["1h"][-1].close_dt for state in states if state["1h"]]
    return {
        "symbol_count": len(states),
        "symbols": [state["symbol"] for state in states],
        "start_at": min(starts).isoformat() if starts else None,
        "end_at": max(ends).isoformat() if ends else None,
    }

