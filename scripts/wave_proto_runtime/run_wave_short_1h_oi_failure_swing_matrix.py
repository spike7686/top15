#!/usr/bin/env python3
from __future__ import annotations

import json
import statistics
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta
from pathlib import Path

import run_wave_short_kline_backtest as base
import run_wave_short_perp_context_loader as ctx


LAB_DIR = Path(__file__).resolve().parent
OUTPUT_DIR = LAB_DIR / "output"
OUTPUT_JSON_PATH = OUTPUT_DIR / "wave_short_1h_oi_failure_swing_matrix_latest.json"
OUTPUT_MD_PATH = OUTPUT_DIR / "wave_short_1h_oi_failure_swing_matrix_latest.md"

STARTING_EQUITY_USD = 10000.0
RISK_PCT = 4.0
MAX_GROSS_PCT = 200.0
ENTRY_COOLDOWN_HOURS = 12.0
PRE_BREAKOUT_RANGE_HOURS = 12
MIN_BUFFER_PCT = 0.25


@dataclass(frozen=True)
class EntryProfile:
    profile_id: str
    description: str
    min_runup_24h_pct: float
    min_trend_7d_pct: float
    peak_lookback_hours: int
    min_peak_age_hours: int
    max_peak_age_hours: int
    min_breakout_margin_pct: float
    min_retrace_from_peak_pct: float
    max_retrace_from_peak_pct: float
    min_lower_high_gap_pct: float
    weakness_score_min: int
    require_below_slow_ma: bool
    require_below_trend_ma: bool


@dataclass(frozen=True)
class OIProfile:
    profile_id: str
    description: str
    min_oi_12h_pct: float | None = None
    min_oi_24h_pct: float | None = None
    min_oi_1h_pct: float | None = None
    max_oi_1h_pct: float | None = None
    min_oi_4h_pct: float | None = None
    max_oi_4h_pct: float | None = None
    min_oi_to_vol_ratio: float | None = None
    min_price_change_4h_pct: float | None = None
    min_price_oi_divergence_4h: float | None = None


@dataclass(frozen=True)
class StopProfile:
    profile_id: str
    description: str
    stop_floor_pct: float
    stop_cap_pct: float
    stop_atr_buffer_mult: float


@dataclass(frozen=True)
class ExitProfile:
    profile_id: str
    description: str
    min_hold_hours: float
    max_hold_hours: float
    tp1_r: float
    tp1_ratio: float
    tp2_r: float
    resume_ma_period: int
    resume_confirm_bars: int


ENTRY_PROFILES = [
    EntryProfile(
        profile_id="entry_core",
        description="标准 1h 失败突破：24h 有明显拉升，假突破后 lower high，并重新跌回快均线下方。",
        min_runup_24h_pct=9.0,
        min_trend_7d_pct=8.0,
        peak_lookback_hours=12,
        min_peak_age_hours=1,
        max_peak_age_hours=5,
        min_breakout_margin_pct=1.2,
        min_retrace_from_peak_pct=1.0,
        max_retrace_from_peak_pct=7.0,
        min_lower_high_gap_pct=0.5,
        weakness_score_min=4,
        require_below_slow_ma=False,
        require_below_trend_ma=False,
    ),
    EntryProfile(
        profile_id="entry_deeper_retrace",
        description="更深回踩后再空，优先改善入场位置，减少过早空在高位横盘中的概率。",
        min_runup_24h_pct=10.0,
        min_trend_7d_pct=8.0,
        peak_lookback_hours=14,
        min_peak_age_hours=2,
        max_peak_age_hours=6,
        min_breakout_margin_pct=1.2,
        min_retrace_from_peak_pct=2.5,
        max_retrace_from_peak_pct=10.0,
        min_lower_high_gap_pct=0.7,
        weakness_score_min=5,
        require_below_slow_ma=True,
        require_below_trend_ma=False,
    ),
    EntryProfile(
        profile_id="entry_late_structure",
        description="更慢的 1h 结构转弱：要求更强的前期拉升、更成熟的回落与更明确的均线破坏。",
        min_runup_24h_pct=12.0,
        min_trend_7d_pct=10.0,
        peak_lookback_hours=16,
        min_peak_age_hours=2,
        max_peak_age_hours=8,
        min_breakout_margin_pct=1.5,
        min_retrace_from_peak_pct=3.5,
        max_retrace_from_peak_pct=12.0,
        min_lower_high_gap_pct=0.8,
        weakness_score_min=6,
        require_below_slow_ma=True,
        require_below_trend_ma=True,
    ),
]


OI_PROFILES = [
    OIProfile(
        profile_id="oi_none",
        description="不加 OI 过滤，作为基线对照。",
    ),
    OIProfile(
        profile_id="oi_crowded_rollover",
        description="过去 12h 明显拥挤，但最近 1h/4h OI 已经放缓或停滞，偏向顶部拥挤后开始松动。",
        min_oi_12h_pct=8.0,
        max_oi_1h_pct=0.5,
        max_oi_4h_pct=2.0,
        min_oi_to_vol_ratio=0.06,
    ),
    OIProfile(
        profile_id="oi_crowded_unwind",
        description="过去 12h OI 明显扩张，但最近 1h 已转负，偏向第一段多头去杠杆。",
        min_oi_12h_pct=8.0,
        max_oi_1h_pct=-1.0,
        max_oi_4h_pct=0.0,
        min_oi_to_vol_ratio=0.06,
    ),
    OIProfile(
        profile_id="oi_still_expanding",
        description="OI 仍在扩张，测试是否存在更晚的拥挤顶部空点。",
        min_oi_12h_pct=10.0,
        min_oi_1h_pct=1.0,
        min_oi_to_vol_ratio=0.08,
    ),
    OIProfile(
        profile_id="oi_price_divergence",
        description="价格 4h 仍偏强，但 4h OI 已经不再配合，偏向价格强而参与度先弱化的分歧顶部。",
        max_oi_4h_pct=0.0,
        min_price_change_4h_pct=2.5,
        min_price_oi_divergence_4h=3.0,
    ),
]


STOP_PROFILES = [
    StopProfile(
        profile_id="stop_balanced",
        description="平衡止损：4% 地板，10% 上限，ATR 缓冲 0.35。",
        stop_floor_pct=4.0,
        stop_cap_pct=10.0,
        stop_atr_buffer_mult=0.35,
    ),
    StopProfile(
        profile_id="stop_wider",
        description="更宽止损：5% 地板，12% 上限，允许顶部波动更大。",
        stop_floor_pct=5.0,
        stop_cap_pct=12.0,
        stop_atr_buffer_mult=0.45,
    ),
    StopProfile(
        profile_id="stop_tighter",
        description="更紧止损：3.5% 地板，8.5% 上限，验证更好的入场是否能覆盖更紧保护。",
        stop_floor_pct=3.5,
        stop_cap_pct=8.5,
        stop_atr_buffer_mult=0.25,
    ),
]


EXIT_PROFILES = [
    ExitProfile(
        profile_id="exit_12h_tail",
        description="最少持有 12h，1R 先落 35%，剩余仓位看 1h 恢复出场，偏向保留长尾。",
        min_hold_hours=12.0,
        max_hold_hours=72.0,
        tp1_r=1.0,
        tp1_ratio=0.35,
        tp2_r=3.0,
        resume_ma_period=8,
        resume_confirm_bars=2,
    ),
    ExitProfile(
        profile_id="exit_8h_fastpay",
        description="最少持有 8h，0.75R 先落 50%，优先更快兑现第一段利润。",
        min_hold_hours=8.0,
        max_hold_hours=48.0,
        tp1_r=0.75,
        tp1_ratio=0.50,
        tp2_r=2.0,
        resume_ma_period=8,
        resume_confirm_bars=2,
    ),
    ExitProfile(
        profile_id="exit_21ema_guard",
        description="更慢退出：最少持有 12h，并要求 21EMA 恢复确认后才离场。",
        min_hold_hours=12.0,
        max_hold_hours=72.0,
        tp1_r=1.0,
        tp1_ratio=0.40,
        tp2_r=2.5,
        resume_ma_period=21,
        resume_confirm_bars=2,
    ),
]


def safe_float(value):
    return base.safe_float(value)


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


def robustness_penalty(trade_count):
    trade_count = int(trade_count or 0)
    if trade_count >= 12:
        return 0.0
    if trade_count >= 8:
        return 1.5
    if trade_count >= 5:
        return 4.0
    if trade_count >= 3:
        return 7.0
    return 10.0


def ema_value(state, period, idx):
    if period == 8:
        return state["ema8_1h"][idx]
    if period == 21:
        return state["ema21_1h"][idx]
    if period == 55:
        return state["ema55_1h"][idx]
    raise ValueError(f"unsupported ema period: {period}")


def quote_volume_sum(candles):
    values = [safe_float(c.quote_volume) for c in candles]
    values = [v for v in values if v is not None]
    return sum(values) if values else None


def compute_state_snapshots(state):
    one_h = state["1h"]
    snapshots = [None] * len(one_h)
    for idx in range(168, len(one_h)):
        candle = one_h[idx]
        prev = one_h[idx - 1]
        dt = candle.close_dt

        ema8 = state["ema8_1h"][idx]
        ema8_prev = state["ema8_1h"][idx - 1]
        ema21 = state["ema21_1h"][idx]
        ema21_prev = state["ema21_1h"][idx - 1]
        ema55 = state["ema55_1h"][idx]
        ema55_prev = state["ema55_1h"][idx - 1]

        window_24h = one_h[idx - 23 : idx + 1]
        peak_start = max(0, idx - 16)
        peak_window = one_h[peak_start:idx]
        if len(peak_window) < 8:
            continue
        peak_pos = max(range(peak_start, idx), key=lambda pos: one_h[pos].high_price)
        peak_bar = one_h[peak_pos]
        peak_age_hours = idx - peak_pos

        range_start = max(0, peak_pos - PRE_BREAKOUT_RANGE_HOURS)
        pre_breakout_window = one_h[range_start:peak_pos]
        if len(pre_breakout_window) < 6:
            continue
        pre_breakout_high = max(bar.high_price for bar in pre_breakout_window)
        breakout_margin_pct = ((peak_bar.high_price / pre_breakout_high) - 1.0) * 100.0 if pre_breakout_high else None

        post_peak_window = one_h[peak_pos + 1 : idx + 1]
        if not post_peak_window:
            continue
        post_peak_high = max(bar.high_price for bar in post_peak_window)
        lower_high_gap_pct = ((peak_bar.high_price - post_peak_high) / peak_bar.high_price) * 100.0 if peak_bar.high_price else None

        low_24h = min(bar.low_price for bar in window_24h)
        runup_24h_pct = ((peak_bar.high_price / low_24h) - 1.0) * 100.0 if low_24h else None
        trend_7d_pct = base.pct_change(one_h[idx - 168].close_price, candle.close_price)
        trend_7d_label = base.interval_trend_label(one_h[idx - 168].close_price, candle.close_price)
        trend_48h_label = base.interval_trend_label(one_h[idx - 48].close_price, candle.close_price)
        trend_24h_label = base.interval_trend_label(one_h[idx - 24].close_price, candle.close_price)
        price_change_4h_pct = base.pct_change(one_h[idx - 4].close_price, candle.close_price)
        retrace_from_peak_pct = ((peak_bar.high_price - candle.close_price) / peak_bar.high_price) * 100.0 if peak_bar.high_price else None

        breakout_failed = (
            peak_age_hours >= 1
            and breakout_margin_pct is not None
            and peak_bar.close_price > pre_breakout_high
            and candle.close_price < pre_breakout_high
        )
        lower_high_confirmed = (
            lower_high_gap_pct is not None
            and prev.high_price < peak_bar.high_price
            and candle.high_price < peak_bar.high_price
        )

        below_fast_ma = candle.close_price < ema8
        below_slow_ma = candle.close_price < ema21
        below_trend_ma = candle.close_price < ema55
        fast_rollover = ema8 <= ema8_prev
        slow_rollover = ema21 <= ema21_prev
        trend_rollover = ema55 <= ema55_prev
        close_below_prev_low = candle.close_price < prev.low_price
        lower_close_pair = candle.close_price < prev.close_price and prev.close_price < one_h[idx - 2].close_price
        red_bar = candle.close_price < candle.open_price
        two_bar_negative_pct = base.pct_change(one_h[idx - 2].close_price, candle.close_price)

        weakness_score = 0
        weakness_score += 2 if breakout_failed else 0
        weakness_score += 1 if lower_high_confirmed else 0
        weakness_score += 1 if below_fast_ma else 0
        weakness_score += 1 if below_slow_ma else 0
        weakness_score += 1 if fast_rollover else 0
        weakness_score += 1 if close_below_prev_low else 0
        weakness_score += 1 if lower_close_pair else 0
        weakness_score += 1 if red_bar else 0
        weakness_score += 1 if (two_bar_negative_pct or 999.0) <= -1.0 else 0

        atr_pct = base.compute_atr_1h_pct(one_h, dt, candle.close_price)

        oi_1h_pct = ctx.pct_change_by_steps(state["oi_value_1h_aligned"], idx, 1)
        oi_4h_pct = ctx.pct_change_by_steps(state["oi_value_1h_aligned"], idx, 4)
        oi_12h_pct = ctx.pct_change_by_steps(state["oi_value_1h_aligned"], idx, 12)
        oi_24h_pct = ctx.pct_change_by_steps(state["oi_value_1h_aligned"], idx, 24)
        current_oi_value = safe_float(state["oi_value_1h_aligned"][idx])
        quote_volume_24h = quote_volume_sum(window_24h)
        oi_to_vol_ratio = current_oi_value / quote_volume_24h if current_oi_value and quote_volume_24h else None
        price_oi_divergence_4h = None
        if price_change_4h_pct is not None and oi_4h_pct is not None:
            price_oi_divergence_4h = price_change_4h_pct - oi_4h_pct

        snapshots[idx] = {
            "symbol": state["symbol"],
            "entry_dt": dt,
            "entry_price": candle.close_price,
            "peak_idx": peak_pos,
            "peak_price": peak_bar.high_price,
            "peak_age_hours": peak_age_hours,
            "pre_breakout_high": pre_breakout_high,
            "breakout_margin_pct": breakout_margin_pct,
            "runup_24h_pct": runup_24h_pct,
            "trend_7d_pct": trend_7d_pct,
            "trend_7d_label": trend_7d_label,
            "trend_48h_label": trend_48h_label,
            "trend_24h_label": trend_24h_label,
            "price_change_4h_pct": price_change_4h_pct,
            "retrace_from_peak_pct": retrace_from_peak_pct,
            "lower_high_gap_pct": lower_high_gap_pct,
            "breakout_failed": breakout_failed,
            "lower_high_confirmed": lower_high_confirmed,
            "below_fast_ma": below_fast_ma,
            "below_slow_ma": below_slow_ma,
            "below_trend_ma": below_trend_ma,
            "fast_rollover": fast_rollover,
            "slow_rollover": slow_rollover,
            "trend_rollover": trend_rollover,
            "close_below_prev_low": close_below_prev_low,
            "lower_close_pair": lower_close_pair,
            "red_bar": red_bar,
            "two_bar_negative_pct": two_bar_negative_pct,
            "weakness_score": weakness_score,
            "atr_1h_pct": atr_pct,
            "oi_1h_pct": oi_1h_pct,
            "oi_4h_pct": oi_4h_pct,
            "oi_12h_pct": oi_12h_pct,
            "oi_24h_pct": oi_24h_pct,
            "oi_value_usd": current_oi_value,
            "quote_volume_24h": quote_volume_24h,
            "oi_to_vol_ratio": oi_to_vol_ratio,
            "price_oi_divergence_4h": price_oi_divergence_4h,
        }
    return snapshots


def snapshot_matches_entry(snapshot, profile: EntryProfile):
    return (
        snapshot["trend_7d_label"] in {"Up", "StrongUp"}
        and snapshot["trend_48h_label"] in {"Up", "StrongUp"}
        and snapshot["trend_24h_label"] in {"Range", "Up", "StrongUp"}
        and (snapshot["runup_24h_pct"] or -999.0) >= profile.min_runup_24h_pct
        and (snapshot["trend_7d_pct"] or -999.0) >= profile.min_trend_7d_pct
        and profile.min_peak_age_hours <= snapshot["peak_age_hours"] <= profile.max_peak_age_hours
        and (snapshot["breakout_margin_pct"] or -999.0) >= profile.min_breakout_margin_pct
        and snapshot["retrace_from_peak_pct"] is not None
        and profile.min_retrace_from_peak_pct <= snapshot["retrace_from_peak_pct"] <= profile.max_retrace_from_peak_pct
        and (snapshot["lower_high_gap_pct"] or -999.0) >= profile.min_lower_high_gap_pct
        and snapshot["breakout_failed"]
        and snapshot["lower_high_confirmed"]
        and snapshot["weakness_score"] >= profile.weakness_score_min
        and (snapshot["below_slow_ma"] if profile.require_below_slow_ma else snapshot["below_fast_ma"])
        and ((not profile.require_below_trend_ma) or snapshot["below_trend_ma"])
    )


def snapshot_matches_oi(snapshot, profile: OIProfile):
    checks = [
        (profile.min_oi_12h_pct, snapshot["oi_12h_pct"], lambda a, b: b is not None and b >= a),
        (profile.min_oi_24h_pct, snapshot["oi_24h_pct"], lambda a, b: b is not None and b >= a),
        (profile.min_oi_1h_pct, snapshot["oi_1h_pct"], lambda a, b: b is not None and b >= a),
        (profile.max_oi_1h_pct, snapshot["oi_1h_pct"], lambda a, b: b is not None and b <= a),
        (profile.min_oi_4h_pct, snapshot["oi_4h_pct"], lambda a, b: b is not None and b >= a),
        (profile.max_oi_4h_pct, snapshot["oi_4h_pct"], lambda a, b: b is not None and b <= a),
        (profile.min_oi_to_vol_ratio, snapshot["oi_to_vol_ratio"], lambda a, b: b is not None and b >= a),
        (profile.min_price_change_4h_pct, snapshot["price_change_4h_pct"], lambda a, b: b is not None and b >= a),
        (profile.min_price_oi_divergence_4h, snapshot["price_oi_divergence_4h"], lambda a, b: b is not None and b >= a),
    ]
    for expected, actual, fn in checks:
        if expected is not None and not fn(expected, actual):
            return False
    return True


def build_signal(snapshot, stop_profile: StopProfile):
    stop_buffer_pct = max(MIN_BUFFER_PCT, (snapshot["atr_1h_pct"] or 0.0) * stop_profile.stop_atr_buffer_mult)
    raw_stop_price = snapshot["peak_price"] * (1.0 + stop_buffer_pct / 100.0)
    raw_stop_pct = ((raw_stop_price / snapshot["entry_price"]) - 1.0) * 100.0 if snapshot["entry_price"] else None
    if raw_stop_pct is None:
        return None
    effective_stop_pct = max(stop_profile.stop_floor_pct, raw_stop_pct)
    if effective_stop_pct > stop_profile.stop_cap_pct:
        return None
    stop_price = (
        raw_stop_price
        if raw_stop_pct >= stop_profile.stop_floor_pct
        else snapshot["entry_price"] * (1.0 + effective_stop_pct / 100.0)
    )
    return {
        **snapshot,
        "raw_stop_pct": raw_stop_pct,
        "stop_pct": effective_stop_pct,
        "stop_price": stop_price,
    }


def resolve_position_notional(equity_usd, stop_pct):
    if stop_pct in (None, 0):
        return None
    risk_usd = equity_usd * (RISK_PCT / 100.0)
    gross_cap_usd = equity_usd * (MAX_GROSS_PCT / 100.0)
    return min(risk_usd / (stop_pct / 100.0), gross_cap_usd)


def strength_resume_signal(state, idx, exit_profile: ExitProfile):
    selected_ema = ema_value(state, exit_profile.resume_ma_period, idx)
    selected_ema_prev = ema_value(state, exit_profile.resume_ma_period, idx - 1)
    candle = state["1h"][idx]
    prev = state["1h"][idx - 1]
    return (
        candle.close_price > selected_ema
        and selected_ema >= selected_ema_prev
        and candle.close_price > prev.close_price
        and state["ema8_1h"][idx] >= state["ema8_1h"][idx - 1]
    )


def build_candidate_list(states, entry_profile, oi_profile, stop_profile):
    signals = []
    cooldown = timedelta(hours=ENTRY_COOLDOWN_HOURS)
    for state in states:
        active = False
        last_entry_dt = None
        for idx, snapshot in enumerate(state["snapshots"]):
            if snapshot is None:
                continue
            matched = snapshot_matches_entry(snapshot, entry_profile) and snapshot_matches_oi(snapshot, oi_profile)
            if matched and not active:
                if last_entry_dt is None or (snapshot["entry_dt"] - last_entry_dt) >= cooldown:
                    signal = build_signal(snapshot, stop_profile)
                    if signal:
                        signals.append({"state": state, "index": idx, "signal": signal})
                        last_entry_dt = snapshot["entry_dt"]
                        active = True
            elif not matched:
                active = False
    signals.sort(key=lambda item: item["signal"]["entry_dt"])
    return signals


def simulate_trade(state, entry_idx, signal, equity_usd, exit_profile: ExitProfile):
    candles = state["1h"]
    entry_price = signal["entry_price"]
    stop_price = signal["stop_price"]
    stop_pct = signal["stop_pct"]
    entry_dt = signal["entry_dt"]
    notional_usd = resolve_position_notional(equity_usd, stop_pct)
    if notional_usd in (None, 0):
        return None

    qty = notional_usd / entry_price if entry_price else None
    risk_abs = stop_price - entry_price
    tp1_price = entry_price - risk_abs * exit_profile.tp1_r
    tp2_price = entry_price - risk_abs * exit_profile.tp2_r
    min_hold_dt = entry_dt + timedelta(hours=exit_profile.min_hold_hours)
    end_dt = entry_dt + timedelta(hours=exit_profile.max_hold_hours)

    remaining_weight = 1.0
    realized_return_pct = 0.0
    best_path_return_pct = None
    worst_path_return_pct = None
    exit_code = "timeout"
    exit_dt = None
    exit_price = None
    tp1_taken = False
    tp2_taken = False
    stop_price_live = stop_price
    resume_hits = 0

    for j in range(entry_idx + 1, len(candles)):
        bar = candles[j]
        if bar.close_dt > end_dt:
            break

        if bar.high_price >= stop_price_live:
            stop_return = base.short_return_pct(entry_price, stop_price_live)
            realized_return_pct += remaining_weight * (stop_return or 0.0)
            remaining_weight = 0.0
            exit_code = "stop_after_tp1" if tp1_taken else "stop_loss"
            exit_dt = bar.close_dt
            exit_price = stop_price_live
            break

        best_bar_return = base.short_return_pct(entry_price, bar.low_price)
        close_return = base.short_return_pct(entry_price, bar.close_price)
        worst_bar_return = base.short_return_pct(entry_price, bar.high_price)
        if best_bar_return is not None:
            best_path_return_pct = best_bar_return if best_path_return_pct is None else max(best_path_return_pct, best_bar_return)
        if worst_bar_return is not None:
            worst_path_return_pct = worst_bar_return if worst_path_return_pct is None else min(worst_path_return_pct, worst_bar_return)

        if not tp1_taken and bar.low_price <= tp1_price and remaining_weight > 0:
            ratio = min(exit_profile.tp1_ratio, remaining_weight)
            realized_return_pct += ratio * (stop_pct * exit_profile.tp1_r)
            remaining_weight -= ratio
            tp1_taken = True
            stop_price_live = min(stop_price_live, entry_price)

        if tp1_taken and not tp2_taken and bar.low_price <= tp2_price and remaining_weight > 0:
            realized_return_pct += remaining_weight * (stop_pct * exit_profile.tp2_r)
            remaining_weight = 0.0
            tp2_taken = True
            exit_code = "take_profit_tail"
            exit_dt = bar.close_dt
            exit_price = tp2_price
            break

        if bar.close_dt >= min_hold_dt:
            resumed_now = strength_resume_signal(state, j, exit_profile)
            resume_hits = resume_hits + 1 if resumed_now else 0
            if resume_hits >= exit_profile.resume_confirm_bars:
                realized_return_pct += remaining_weight * (close_return or 0.0)
                remaining_weight = 0.0
                exit_code = "strength_resume_after_tp1" if tp1_taken else "strength_resume"
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
        timeout_return = base.short_return_pct(entry_price, timeout_bar.close_price)
        realized_return_pct += remaining_weight * (timeout_return or 0.0)
        exit_code = "timeout_after_tp1" if tp1_taken else "timeout"
        exit_dt = timeout_bar.close_dt
        exit_price = timeout_bar.close_price

    pnl_usd = notional_usd * (realized_return_pct / 100.0)
    realized_r = realized_return_pct / stop_pct if stop_pct else None
    hold_hours = (exit_dt - entry_dt).total_seconds() / 3600.0 if exit_dt else None
    return {
        "symbol": state["symbol"],
        "entry_dt": entry_dt.isoformat(),
        "exit_dt": exit_dt.isoformat() if exit_dt else None,
        "entry_price": entry_price,
        "exit_price": exit_price,
        "stop_pct": stop_pct,
        "tp1_price": tp1_price,
        "tp2_price": tp2_price,
        "position_notional_usd": notional_usd,
        "qty": qty,
        "realized_return_pct": realized_return_pct,
        "realized_r": realized_r,
        "realized_pnl_usd": pnl_usd,
        "best_path_return_pct": best_path_return_pct,
        "worst_path_return_pct": worst_path_return_pct,
        "hold_hours": hold_hours,
        "exit_code": exit_code,
        "tp1_taken": tp1_taken,
        "tp2_taken": tp2_taken,
        "signal": {
            "runup_24h_pct": signal["runup_24h_pct"],
            "trend_7d_pct": signal["trend_7d_pct"],
            "retrace_from_peak_pct": signal["retrace_from_peak_pct"],
            "peak_age_hours": signal["peak_age_hours"],
            "breakout_margin_pct": signal["breakout_margin_pct"],
            "lower_high_gap_pct": signal["lower_high_gap_pct"],
            "weakness_score": signal["weakness_score"],
            "oi_1h_pct": signal["oi_1h_pct"],
            "oi_4h_pct": signal["oi_4h_pct"],
            "oi_12h_pct": signal["oi_12h_pct"],
            "oi_24h_pct": signal["oi_24h_pct"],
            "oi_to_vol_ratio": signal["oi_to_vol_ratio"],
            "price_oi_divergence_4h": signal["price_oi_divergence_4h"],
        },
    }


def run_variant(states, entry_profile, oi_profile, stop_profile, exit_profile):
    signals = build_candidate_list(states, entry_profile, oi_profile, stop_profile)
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
        trade = simulate_trade(item["state"], item["index"], item["signal"], equity_usd, exit_profile)
        if not trade:
            continue
        trades.append(trade)
        equity_usd += trade["realized_pnl_usd"]
        peak = max(peak, equity_usd)
        dd = ((peak - equity_usd) / peak * 100.0) if peak else 0.0
        max_dd = max(max_dd, dd)
        exit_code_counts[trade["exit_code"]] = exit_code_counts.get(trade["exit_code"], 0) + 1
        open_until = datetime.fromisoformat(trade["exit_dt"]) if trade["exit_dt"] else None
        equity_curve.append(
            {
                "ts": trade["exit_dt"],
                "equity_usd": equity_usd,
                "symbol": trade["symbol"],
                "pnl_usd": trade["realized_pnl_usd"],
            }
        )

    pnl_values = [t["realized_pnl_usd"] for t in trades]
    hold_values = [t["hold_hours"] for t in trades]
    realized_r_values = [t["realized_r"] for t in trades]
    realized_pct_values = [t["realized_return_pct"] for t in trades]
    best_path_values = [t["best_path_return_pct"] for t in trades]
    worst_path_values = [t["worst_path_return_pct"] for t in trades]
    large_winner_count = sum(1 for t in trades if (safe_float(t["realized_r"]) or -999.0) >= 2.0)
    stopout_count = sum(1 for t in trades if t["exit_code"] in {"stop_loss", "stop_after_tp1"})
    research_score = (
        ((equity_usd - STARTING_EQUITY_USD) / STARTING_EQUITY_USD * 100.0)
        - max_dd * 0.9
        + (mean(realized_r_values) or 0.0) * 4.0
        + min(len(trades), 24) * 0.25
        + large_winner_count * 0.8
        - stopout_count * 0.15
    )
    robust_research_score = research_score - robustness_penalty(len(trades))
    variant_id = "__".join(
        [entry_profile.profile_id, oi_profile.profile_id, stop_profile.profile_id, exit_profile.profile_id]
    )
    return {
        "variant_id": variant_id,
        "description": " ".join(
            [
                entry_profile.description,
                oi_profile.description,
                stop_profile.description,
                exit_profile.description,
            ]
        ),
        "profiles": {
            "entry": asdict(entry_profile),
            "oi": asdict(oi_profile),
            "stop": asdict(stop_profile),
            "exit": asdict(exit_profile),
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
            "avg_realized_r": mean(realized_r_values),
            "median_realized_r": median(realized_r_values),
            "avg_realized_return_pct": mean(realized_pct_values),
            "avg_best_path_return_pct": mean(best_path_values),
            "avg_worst_path_return_pct": mean(worst_path_values),
            "max_drawdown_pct": max_dd,
            "tp1_hit_ratio": ratio_true(t["tp1_taken"] for t in trades),
            "tp2_hit_ratio": ratio_true(t["tp2_taken"] for t in trades),
            "large_winner_count": large_winner_count,
            "stopout_count": stopout_count,
            "exit_code_counts": exit_code_counts,
            "research_score": research_score,
            "robust_research_score": robust_research_score,
        },
        "trades": trades,
        "equity_curve": equity_curve,
    }


def build_markdown(payload):
    ranked = sorted(payload["variants"], key=lambda item: item["summary"]["robust_research_score"], reverse=True)
    lines = [
        "# 1h OI Failure Swing Matrix",
        "",
        "## Theory",
        "",
        "- 主触发不再依赖 30m 首次转弱，而是 `1h failure breakout + lower high + reclaim below EMA`。",
        "- OI 不拿来单独发信号，而是作为顶部拥挤 / 分歧 / 去杠杆阶段的过滤器。",
        "- 持仓至少 8h~12h，避免被 30m 级别小反弹提前洗掉。",
        "- 退出仍以 1h 恢复为主，允许先兑现一部分，再让尾仓吃更长回落。",
        "",
        "## Dataset",
        "",
        f"- Symbols loaded: {payload['dataset']['symbol_count']}",
        f"- 1h coverage: {payload['dataset']['start_at']} -> {payload['dataset']['end_at']}",
        f"- Variants tested: {len(payload['variants'])}",
        "",
        "## Top Variants",
        "",
        "| variant | return | max DD | trades | win rate | avg R | avg hold | robust score |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for item in ranked[:12]:
        s = item["summary"]
        lines.append(
            "| {variant} | {ret:.2f}% | {dd:.2f}% | {trades} | {win:.1f}% | {avg_r:.2f} | {hold:.2f}h | {score:.2f} |".format(
                variant=item["variant_id"],
                ret=s["return_pct"],
                dd=s["max_drawdown_pct"] or 0.0,
                trades=s["executed_trade_count"],
                win=(s["win_rate"] or 0.0) * 100.0,
                avg_r=s["avg_realized_r"] or 0.0,
                hold=s["avg_hold_hours"] or 0.0,
                score=s["robust_research_score"] or 0.0,
            )
        )

    if ranked:
        best = ranked[0]
        lines.extend(
            [
                "",
                "## Best Variant",
                "",
                f"- Variant: `{best['variant_id']}`",
                f"- Return: {best['summary']['return_pct']:.2f}%",
                f"- Max drawdown: {best['summary']['max_drawdown_pct']:.2f}%",
                f"- Trades: {best['summary']['executed_trade_count']}",
                f"- Avg hold: {best['summary']['avg_hold_hours']:.2f}h" if best['summary']['avg_hold_hours'] is not None else "- Avg hold: --",
                "",
                "### Sample Trades",
                "",
            ]
        )
        for trade in best["trades"][:12]:
            sig = trade["signal"]
            lines.append(
                "- `{symbol}` {entry} -> {exit} | {ret:.2f}% | {hold:.1f}h | `{code}` | oi1h={oi1:.1f}% | oi12h={oi12:.1f}% | retrace={retrace:.1f}%".format(
                    symbol=trade["symbol"],
                    entry=trade["entry_dt"],
                    exit=trade["exit_dt"],
                    ret=trade["realized_return_pct"] or 0.0,
                    hold=trade["hold_hours"] or 0.0,
                    code=trade["exit_code"],
                    oi1=sig["oi_1h_pct"] or 0.0,
                    oi12=sig["oi_12h_pct"] or 0.0,
                    retrace=sig["retrace_from_peak_pct"] or 0.0,
                )
            )
    return "\n".join(lines)


def main():
    states = ctx.load_perp_context_states()
    for state in states:
        state["snapshots"] = compute_state_snapshots(state)

    variants = []
    for entry_profile in ENTRY_PROFILES:
        for oi_profile in OI_PROFILES:
            for stop_profile in STOP_PROFILES:
                for exit_profile in EXIT_PROFILES:
                    variants.append(run_variant(states, entry_profile, oi_profile, stop_profile, exit_profile))

    ranked = sorted(variants, key=lambda item: item["summary"]["robust_research_score"], reverse=True)
    payload = {
        "ok": True,
        "study_id": "wave_short_1h_oi_failure_swing_matrix_v1",
        "generated_at_utc": datetime.utcnow().isoformat() + "Z",
        "dataset": ctx.dataset_summary(states),
        "config": {
            "starting_equity_usd": STARTING_EQUITY_USD,
            "risk_pct": RISK_PCT,
            "max_gross_pct": MAX_GROSS_PCT,
            "entry_cooldown_hours": ENTRY_COOLDOWN_HOURS,
        },
        "variants": variants,
        "top_variant": {
            "variant_id": ranked[0]["variant_id"] if ranked else None,
            "robust_research_score": ranked[0]["summary"]["robust_research_score"] if ranked else None,
        },
    }

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    OUTPUT_JSON_PATH.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    OUTPUT_MD_PATH.write_text(build_markdown(payload), encoding="utf-8")
    print(
        json.dumps(
            {
                "ok": True,
                "output_json": str(OUTPUT_JSON_PATH),
                "output_md": str(OUTPUT_MD_PATH),
                "top_variant": payload["top_variant"],
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
