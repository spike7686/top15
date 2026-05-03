#!/usr/bin/env python3
from __future__ import annotations

import csv
import json
import math
import statistics
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path


LAB_DIR = Path(__file__).resolve().parent
KLINES_DIR = LAB_DIR / "data" / "top15_tracker" / "klines"
OUTPUT_DIR = LAB_DIR / "output"
OUTPUT_JSON_PATH = OUTPUT_DIR / "wave_short_kline_backtest_latest.json"
OUTPUT_MD_PATH = OUTPUT_DIR / "wave_short_kline_backtest_latest.md"

STARTING_EQUITY_USD = 10000.0
RISK_PCT = 5.0
MAX_GROSS_PCT = 250.0
MAX_CONCURRENT = 1
MIN_STOP_PCT = 3.0
MAX_STOP_PCT = 20.0
PARTIAL_TAKE_PROFIT_PCT = 2.5
PARTIAL_TAKE_PROFIT_RATIO = 0.67
MAX_HOLD_HOURS = 24.0
ENTRY_COOLDOWN_HOURS = 6.0
STRUCTURE_FRONT_HIGH_LOOKBACK_H = 2.0
STRUCTURE_VOL_LOOKBACK_H = 1.0
STRUCTURE_ATR_PERIOD = 14
STRUCTURE_STOP_BUFFER_MULT = 0.35
STRUCTURE_MIN_BUFFER_PCT = 0.15


@dataclass
class Candle:
    symbol: str
    interval: str
    open_dt: datetime
    close_dt: datetime
    open_price: float
    high_price: float
    low_price: float
    close_price: float
    quote_volume: float | None


def safe_float(value):
    try:
        num = float(value)
    except (TypeError, ValueError):
        return None
    return num if math.isfinite(num) else None


def parse_dt(value):
    if not value:
        return None
    return datetime.fromisoformat(value)


def pct_change(first_value, last_value):
    first = safe_float(first_value)
    last = safe_float(last_value)
    if first in (None, 0) or last is None:
        return None
    return ((last - first) / first) * 100.0


def short_return_pct(entry_price, exit_price):
    entry = safe_float(entry_price)
    exit = safe_float(exit_price)
    if entry in (None, 0) or exit is None:
        return None
    return ((entry - exit) / entry) * 100.0


def interval_trend_label(first_close, last_close):
    chg = pct_change(first_close, last_close)
    if chg is None:
        return "Unknown"
    if chg >= 10:
        return "StrongUp"
    if chg >= 2:
        return "Up"
    if chg <= -10:
        return "StrongDown"
    if chg <= -2:
        return "Down"
    return "Range"


def breakout_label(rows):
    if not rows or len(rows) < 5:
        return "Unknown"
    last = rows[-1]
    prev = rows[:-1]
    highs = [row.high_price for row in prev if row.high_price is not None]
    quotes = [row.quote_volume for row in prev if row.quote_volume is not None]
    if last.close_price is None or not highs:
        return "Unknown"
    if last.close_price > max(highs):
        avg_quote = sum(quotes) / len(quotes) if quotes else None
        if avg_quote and last.quote_volume and last.quote_volume > avg_quote * 1.3:
            return "VolumeBreakout"
        return "PriceBreakout"
    return "NoBreakout"


def load_candles(csv_path: Path):
    rows = []
    with csv_path.open("r", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        for item in reader:
            open_dt = parse_dt(item.get("open_time_utc"))
            close_dt = parse_dt(item.get("close_time_utc"))
            if not open_dt or not close_dt:
                continue
            rows.append(
                Candle(
                    symbol=str(item.get("symbol") or csv_path.parents[2].name),
                    interval=str(item.get("interval") or csv_path.parents[1].name),
                    open_dt=open_dt,
                    close_dt=close_dt,
                    open_price=safe_float(item.get("open_price")) or 0.0,
                    high_price=safe_float(item.get("high_price")) or 0.0,
                    low_price=safe_float(item.get("low_price")) or 0.0,
                    close_price=safe_float(item.get("close_price")) or 0.0,
                    quote_volume=safe_float(item.get("quote_volume")),
                )
            )
    rows.sort(key=lambda x: x.close_dt)
    return rows


def latest_closed_before(candles, dt):
    eligible = [c for c in candles if c.close_dt <= dt]
    return eligible[-1] if eligible else None


def recent_closed_window(candles, dt, limit):
    eligible = [c for c in candles if c.close_dt <= dt]
    return eligible[-limit:]


def compute_atr_1h_pct(candles_1h, entry_dt, entry_price):
    eligible = [c for c in candles_1h if c.close_dt <= entry_dt]
    if len(eligible) < STRUCTURE_ATR_PERIOD + 1:
        return None
    window = eligible[-(STRUCTURE_ATR_PERIOD + 1) :]
    true_ranges = []
    prev_close = None
    for candle in window:
        high = candle.high_price
        low = candle.low_price
        if prev_close is None:
            tr = high - low
        else:
            tr = max(high - low, abs(high - prev_close), abs(low - prev_close))
        true_ranges.append(tr)
        prev_close = candle.close_price
    recent = true_ranges[-STRUCTURE_ATR_PERIOD:]
    if not recent or entry_price in (None, 0):
        return None
    atr_abs = sum(recent) / len(recent)
    return atr_abs / entry_price * 100.0


def compute_structure_context(candles_1h, entry_dt, entry_price):
    closed = [c for c in candles_1h if c.close_dt <= entry_dt]
    if not closed:
        return None
    front_cutoff = entry_dt - timedelta(hours=STRUCTURE_FRONT_HIGH_LOOKBACK_H)
    front_highs = [c.high_price for c in closed if c.close_dt > front_cutoff]
    front_high_price = max(front_highs) if front_highs else entry_price

    vol_cutoff = entry_dt - timedelta(hours=STRUCTURE_VOL_LOOKBACK_H)
    vol_window = [c for c in closed if c.close_dt > vol_cutoff]
    snapshot_range_1h_pct = None
    if vol_window and entry_price:
        window_high = max(c.high_price for c in vol_window)
        window_low = min(c.low_price for c in vol_window)
        snapshot_range_1h_pct = ((window_high - window_low) / entry_price) * 100.0

    atr_1h_pct = compute_atr_1h_pct(candles_1h, entry_dt, entry_price)
    vol_base_pct = atr_1h_pct if atr_1h_pct is not None else snapshot_range_1h_pct
    stop_anchor_price = max(front_high_price, entry_price)
    stop_buffer_pct = max(STRUCTURE_MIN_BUFFER_PCT, (vol_base_pct or 0.0) * STRUCTURE_STOP_BUFFER_MULT)
    stop_price = stop_anchor_price * (1.0 + stop_buffer_pct / 100.0)
    stop_pct = ((stop_price / entry_price) - 1.0) * 100.0 if entry_price else None
    return {
        "front_high_price": front_high_price,
        "atr_1h_pct": atr_1h_pct,
        "stop_price": stop_price,
        "stop_pct": stop_pct,
    }


def build_symbol_state(symbol_dir: Path):
    symbol = symbol_dir.name.upper()
    one_h = load_candles(symbol_dir / "1h" / "candles.csv")
    four_h = load_candles(symbol_dir / "4h" / "candles.csv")
    one_d = load_candles(symbol_dir / "1d" / "candles.csv")
    if len(one_h) < 48 or len(four_h) < 8 or len(one_d) < 8:
        return None
    return {"symbol": symbol, "1h": one_h, "4h": four_h, "1d": one_d}


def compute_entry_signal(state, idx):
    one_h = state["1h"]
    candle = one_h[idx]
    dt = candle.close_dt

    window_1h = recent_closed_window(one_h, dt, 24)
    window_4h = recent_closed_window(state["4h"], dt, 12)
    window_1d = recent_closed_window(state["1d"], dt, 7)
    if len(window_1h) < 24 or len(window_4h) < 2 or len(window_1d) < 7:
        return None

    trend_1h = interval_trend_label(window_1h[0].close_price, window_1h[-1].close_price)
    trend_4h = interval_trend_label(window_4h[0].close_price, window_4h[-1].close_price)
    trend_1d = interval_trend_label(window_1d[0].close_price, window_1d[-1].close_price)
    breakout_1h = breakout_label(window_1h[-24:])
    price_change_4h_window_pct = pct_change(window_4h[-2].close_price, window_4h[-1].close_price)
    price_change_7d_pct = pct_change(window_1d[0].close_price, window_1d[-1].close_price)

    structure = compute_structure_context(one_h, dt, candle.close_price)
    if structure is None:
        return None

    signal = {
        "symbol": state["symbol"],
        "entry_dt": dt,
        "entry_price": candle.close_price,
        "trend_1h": trend_1h,
        "trend_4h": trend_4h,
        "trend_1d": trend_1d,
        "breakout_1h": breakout_1h,
        "price_change_4h_window_pct": price_change_4h_window_pct,
        "price_change_7d_pct": price_change_7d_pct,
        **structure,
    }
    signal["openable"] = (
        trend_1d == "StrongUp"
        and trend_4h in {"Up", "StrongUp"}
        and trend_1h in {"Range", "Down", "StrongDown"}
        and breakout_1h == "NoBreakout"
        and (price_change_4h_window_pct or -999.0) >= 6.0
        and (price_change_7d_pct or -999.0) >= 10.0
        and signal["stop_pct"] is not None
        and MIN_STOP_PCT <= signal["stop_pct"] <= MAX_STOP_PCT
    )
    return signal


def resolve_position_notional(equity_usd, stop_pct):
    if stop_pct in (None, 0):
        return None
    risk_usd = equity_usd * (RISK_PCT / 100.0)
    gross_cap_usd = equity_usd * (MAX_GROSS_PCT / 100.0)
    return min(risk_usd / (stop_pct / 100.0), gross_cap_usd)


def simulate_trade(state, entry_idx, signal, equity_usd):
    candles = state["1h"]
    entry_price = signal["entry_price"]
    stop_price = signal["stop_price"]
    stop_pct = signal["stop_pct"]
    entry_dt = signal["entry_dt"]
    notional_usd = resolve_position_notional(equity_usd, stop_pct)
    if notional_usd in (None, 0):
        return None
    qty = notional_usd / entry_price if entry_price else None
    remaining_weight = 1.0
    realized_return_pct = 0.0
    took_partial = False
    exit_code = "timeout"
    exit_dt = None
    exit_price = None
    end_dt = entry_dt + timedelta(hours=MAX_HOLD_HOURS)
    best_path_return_pct = None
    worst_path_return_pct = None

    for j in range(entry_idx + 1, len(candles)):
        bar = candles[j]
        if bar.close_dt > end_dt:
            break
        # stop first on adverse move
        if bar.high_price >= stop_price:
            realized_return_pct += remaining_weight * (-stop_pct)
            remaining_weight = 0.0
            exit_code = "stop_loss"
            exit_dt = bar.close_dt
            exit_price = stop_price
            break

        best_bar_return = short_return_pct(entry_price, bar.low_price)
        close_return = short_return_pct(entry_price, bar.close_price)
        worst_bar_return = short_return_pct(entry_price, bar.high_price)
        if best_bar_return is not None:
            best_path_return_pct = best_bar_return if best_path_return_pct is None else max(best_path_return_pct, best_bar_return)
        if worst_bar_return is not None:
            worst_path_return_pct = worst_bar_return if worst_path_return_pct is None else min(worst_path_return_pct, worst_bar_return)

        partial_tp_price = entry_price * (1.0 - PARTIAL_TAKE_PROFIT_PCT / 100.0)
        if not took_partial and bar.low_price <= partial_tp_price and remaining_weight > 0:
            ratio = min(PARTIAL_TAKE_PROFIT_RATIO, remaining_weight)
            realized_return_pct += ratio * PARTIAL_TAKE_PROFIT_PCT
            remaining_weight -= ratio
            took_partial = True

        trend_signal = compute_entry_signal(state, j)
        trend_resumed = bool(
            trend_signal
            and (
                trend_signal["trend_1h"] in {"Up", "StrongUp"}
                or trend_signal["breakout_1h"] in {"PriceBreakout", "VolumeBreakout"}
            )
        )
        if trend_resumed:
            realized_return_pct += remaining_weight * (close_return or 0.0)
            remaining_weight = 0.0
            exit_code = "trend_resume"
            exit_dt = bar.close_dt
            exit_price = bar.close_price
            break

    if remaining_weight > 0:
        timeout_bar = None
        for j in range(entry_idx + 1, len(candles)):
            bar = candles[j]
            if bar.close_dt > end_dt:
                break
            timeout_bar = bar
        if timeout_bar is None:
            return None
        timeout_return = short_return_pct(entry_price, timeout_bar.close_price)
        realized_return_pct += remaining_weight * (timeout_return or 0.0)
        exit_code = "timeout"
        exit_dt = timeout_bar.close_dt
        exit_price = timeout_bar.close_price

    pnl_usd = notional_usd * (realized_return_pct / 100.0)
    hold_hours = (exit_dt - entry_dt).total_seconds() / 3600.0 if exit_dt else None
    return {
        "symbol": state["symbol"],
        "entry_dt": entry_dt.isoformat(),
        "exit_dt": exit_dt.isoformat() if exit_dt else None,
        "entry_price": entry_price,
        "exit_price": exit_price,
        "stop_pct": stop_pct,
        "position_notional_usd": notional_usd,
        "qty": qty,
        "realized_return_pct": realized_return_pct,
        "realized_pnl_usd": pnl_usd,
        "best_path_return_pct": best_path_return_pct,
        "worst_path_return_pct": worst_path_return_pct,
        "hold_hours": hold_hours,
        "exit_code": exit_code,
        "took_partial": took_partial,
        "signal": {
            "trend_1d": signal["trend_1d"],
            "trend_4h": signal["trend_4h"],
            "trend_1h": signal["trend_1h"],
            "breakout_1h": signal["breakout_1h"],
            "price_change_4h_window_pct": signal["price_change_4h_window_pct"],
            "price_change_7d_pct": signal["price_change_7d_pct"],
        },
    }


def mean(values):
    cleaned = [safe_float(v) for v in values]
    cleaned = [v for v in cleaned if v is not None]
    return sum(cleaned) / len(cleaned) if cleaned else None


def median(values):
    cleaned = [safe_float(v) for v in values]
    cleaned = [v for v in cleaned if v is not None]
    return statistics.median(cleaned) if cleaned else None


def ratio_true(values):
    vals = [v for v in values if v is not None]
    return sum(1 for v in vals if v) / len(vals) if vals else None


def build_markdown(payload):
    s = payload["summary"]
    lines = [
        "# Wave Short Kline Backtest",
        "",
        "## Summary",
        "",
        f"- Symbols loaded: {payload['dataset']['symbol_count']}",
        f"- Raw signal count: {s['raw_signal_count']}",
        f"- Executed trades: {s['executed_trade_count']}",
        f"- Final equity: ${s['final_equity_usd']:.2f}",
        f"- Total pnl: ${s['total_pnl_usd']:.2f}",
        f"- Return pct: {s['return_pct']:.2f}%",
        f"- Win rate: {s['win_rate'] * 100:.1f}%" if s["win_rate"] is not None else "- Win rate: --",
        f"- Avg pnl / trade: ${s['avg_pnl_usd']:.2f}" if s["avg_pnl_usd"] is not None else "- Avg pnl / trade: --",
        f"- Avg hold hours: {s['avg_hold_hours']:.2f}h" if s["avg_hold_hours"] is not None else "- Avg hold hours: --",
        f"- Max drawdown pct: {s['max_drawdown_pct']:.2f}%" if s["max_drawdown_pct"] is not None else "- Max drawdown pct: --",
        "",
        "## Exit Codes",
        "",
    ]
    for k, v in s["exit_code_counts"].items():
        lines.append(f"- `{k}`: {v}")
    lines.append("")
    return "\n".join(lines)


def main():
    symbol_dirs = [p for p in sorted(KLINES_DIR.iterdir()) if p.is_dir()]
    states = [build_symbol_state(p) for p in symbol_dirs]
    states = [s for s in states if s]

    signals = []
    for state in states:
        active = False
        last_entry_dt = None
        for idx in range(24, len(state["1h"])):
            sig = compute_entry_signal(state, idx)
            if not sig:
                continue
            if sig["openable"] and not active:
                if last_entry_dt is None or (sig["entry_dt"] - last_entry_dt) >= timedelta(hours=ENTRY_COOLDOWN_HOURS):
                    signals.append({"state": state, "index": idx, "signal": sig})
                    last_entry_dt = sig["entry_dt"]
                    active = True
            elif not sig["openable"]:
                active = False

    signals.sort(key=lambda item: item["signal"]["entry_dt"])
    equity_usd = STARTING_EQUITY_USD
    peak = equity_usd
    max_dd = 0.0
    open_until = None
    trades = []
    exit_code_counts = {}
    equity_curve = []
    for item in signals:
        sig_dt = item["signal"]["entry_dt"]
        if open_until and sig_dt < open_until:
            continue
        trade = simulate_trade(item["state"], item["index"], item["signal"], equity_usd)
        if not trade:
            continue
        trades.append(trade)
        equity_usd += trade["realized_pnl_usd"]
        peak = max(peak, equity_usd)
        dd = ((peak - equity_usd) / peak * 100.0) if peak else 0.0
        max_dd = max(max_dd, dd)
        exit_code_counts[trade["exit_code"]] = exit_code_counts.get(trade["exit_code"], 0) + 1
        open_until = datetime.fromisoformat(trade["exit_dt"]) if trade["exit_dt"] else None
        equity_curve.append({"ts": trade["exit_dt"], "equity_usd": equity_usd, "symbol": trade["symbol"], "pnl_usd": trade["realized_pnl_usd"]})

    pnl_values = [t["realized_pnl_usd"] for t in trades]
    hold_values = [t["hold_hours"] for t in trades]
    payload = {
        "ok": True,
        "study_id": "wave_short_kline_backtest_v1",
        "generated_at_utc": datetime.utcnow().isoformat() + "Z",
        "dataset": {
            "klines_dir": str(KLINES_DIR),
            "symbol_count": len(states),
        },
        "config": {
            "risk_pct": RISK_PCT,
            "max_gross_pct": MAX_GROSS_PCT,
            "max_concurrent": MAX_CONCURRENT,
            "min_stop_pct": MIN_STOP_PCT,
            "max_stop_pct": MAX_STOP_PCT,
            "partial_take_profit_pct": PARTIAL_TAKE_PROFIT_PCT,
            "partial_take_profit_ratio": PARTIAL_TAKE_PROFIT_RATIO,
            "max_hold_hours": MAX_HOLD_HOURS,
            "entry_cooldown_hours": ENTRY_COOLDOWN_HOURS,
        },
        "summary": {
            "raw_signal_count": len(signals),
            "executed_trade_count": len(trades),
            "final_equity_usd": equity_usd,
            "total_pnl_usd": equity_usd - STARTING_EQUITY_USD,
            "return_pct": (equity_usd - STARTING_EQUITY_USD) / STARTING_EQUITY_USD * 100.0,
            "win_rate": ratio_true((safe_float(x) or -999999.0) > 0 for x in pnl_values),
            "avg_pnl_usd": mean(pnl_values),
            "median_pnl_usd": median(pnl_values),
            "avg_hold_hours": mean(hold_values),
            "median_hold_hours": median(hold_values),
            "max_drawdown_pct": max_dd,
            "exit_code_counts": exit_code_counts,
        },
        "trades": trades[:500],
        "equity_curve": equity_curve,
    }

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    OUTPUT_JSON_PATH.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    OUTPUT_MD_PATH.write_text(build_markdown(payload), encoding="utf-8")
    print(json.dumps({"ok": True, "output_json": str(OUTPUT_JSON_PATH), "output_md": str(OUTPUT_MD_PATH)}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
