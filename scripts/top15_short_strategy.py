#!/usr/bin/env python3
import csv
import json
from collections import OrderedDict
from datetime import datetime, timedelta
from pathlib import Path

WORKDIR = Path(__file__).resolve().parents[1]
DATA_DIR = WORKDIR / "data" / "top15_tracker"
KLINES_DIR = DATA_DIR / "klines"
SHORT_STRATEGY_CONFIG_PATH = WORKDIR / "config" / "short_strategy.post_confirm_weak_turn_v1.json"
KLINE_CACHE = {}


def load_short_strategy_config():
    if not SHORT_STRATEGY_CONFIG_PATH.exists():
        return {}
    try:
        payload = json.loads(SHORT_STRATEGY_CONFIG_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return payload if isinstance(payload, dict) else {}


SHORT_STRATEGY_CONFIG = load_short_strategy_config()
STRATEGY_CONFIG = SHORT_STRATEGY_CONFIG.get("strategy") or {}
ANCHOR_CONFIG = STRATEGY_CONFIG.get("anchor") or {}
WEAKENING_CONFIG = STRATEGY_CONFIG.get("weakening") or {}
CONFIRMATION_CONFIG = STRATEGY_CONFIG.get("confirmations") or {}
DEFAULT_CONFIRM_CONFIG = CONFIRMATION_CONFIG.get("default") or {}
HISTORICAL_SNIPER_CONFIG = CONFIRMATION_CONFIG.get("historical_sniper") or {}
LIVE_SNIPER_CONFIG = CONFIRMATION_CONFIG.get("live_sniper") or {}
STRUCTURE_CONFIG = SHORT_STRATEGY_CONFIG.get("structure") or {}
RISK_CONFIG = SHORT_STRATEGY_CONFIG.get("risk") or {}
RECENT_OVERLAP_WINDOW_H = float(ANCHOR_CONFIG.get("recent_overlap_window_hours") or 2.0)

STRUCTURE_FRONT_HIGH_LOOKBACK_H = float(STRUCTURE_CONFIG.get("front_high_lookback_h") or 2.0)
STRUCTURE_VOL_LOOKBACK_H = float(STRUCTURE_CONFIG.get("vol_lookback_h") or 1.0)
STRUCTURE_ATR_PERIOD = int(STRUCTURE_CONFIG.get("atr_period") or 14)
STRUCTURE_STOP_BUFFER_MULT = float(STRUCTURE_CONFIG.get("stop_buffer_mult") or 0.35)
STRUCTURE_MIN_BUFFER_PCT = float(STRUCTURE_CONFIG.get("min_buffer_pct") or 0.15)
STRUCTURE_STOP_MIN_PCT = float(STRUCTURE_CONFIG.get("stop_window_min_pct") or 0.8)
STRUCTURE_STOP_MAX_PCT = float(STRUCTURE_CONFIG.get("stop_window_max_pct") or 4.5)
CONTROL_STOP_WINDOW_MIN_PCT = 3.0
CONTROL_STOP_WINDOW_MAX_PCT = 20.0
CONTROL_TARGET_R_MULTIPLE = 1.5

SHADOW_STRATEGY_LAYERS = OrderedDict(
    [
        (
            "A_post_confirm_weak_turn",
            {
                "code": "A",
                "signal_name": STRATEGY_CONFIG.get("signal_name") or "post_confirm_weak_turn",
                "label": "A / 严格后确认转弱",
                "short_label": "A层",
                "entry_filters": ["no_breakout_1h", "chg_3_8"],
                "requires_no_breakout_exit": True,
                "target_r_multiple": 1.0,
                "description": "当前正式规则：确认锚点成立后，等 1h 趋势转弱、无突破、24h 涨幅回到 3%~8% 再做结构空。",
            },
        ),
        (
            "B_no_breakout_fade",
            {
                "code": "B",
                "signal_name": "no_breakout_fade",
                "label": "B / NoBreakout Fade",
                "short_label": "B层",
                "entry_filters": [],
                "requires_no_breakout_exit": True,
                "target_r_multiple": 1.0,
                "description": "仍在交叉候选池内，30m 排名和交叉分同步转弱，且 1h 已无突破结构。",
            },
        ),
        (
            "B_no_breakout_fade_wide",
            {
                "code": "B+",
                "signal_name": "no_breakout_fade_wide",
                "label": "B+ / NoBreakout Wide",
                "short_label": "B+层",
                "entry_filters": [],
                "requires_no_breakout_exit": True,
                "stop_window_min_pct": CONTROL_STOP_WINDOW_MIN_PCT,
                "stop_window_max_pct": CONTROL_STOP_WINDOW_MAX_PCT,
                "target_r_multiple": CONTROL_TARGET_R_MULTIPLE,
                "description": "B 对照组：结构止损窗口放宽到 3%~20%，止盈改为 1.5R，专门验证大波动回撤能否带来更大跌幅。",
            },
        ),
        (
            "C_overheat_fade",
            {
                "code": "C",
                "signal_name": "overheat_fade",
                "label": "C / Overheat Fade",
                "short_label": "C层",
                "entry_filters": [],
                "requires_no_breakout_exit": False,
                "target_r_multiple": 1.0,
                "description": "仍在交叉候选池内，24h 涨幅和换手已过热，30m 动能开始转弱。",
            },
        ),
        (
            "C_overheat_fade_wide",
            {
                "code": "C+",
                "signal_name": "overheat_fade_wide",
                "label": "C+ / Overheat Wide",
                "short_label": "C+层",
                "entry_filters": [],
                "requires_no_breakout_exit": False,
                "stop_window_min_pct": CONTROL_STOP_WINDOW_MIN_PCT,
                "stop_window_max_pct": CONTROL_STOP_WINDOW_MAX_PCT,
                "target_r_multiple": CONTROL_TARGET_R_MULTIPLE,
                "description": "C 对照组：结构止损窗口放宽到 3%~20%，止盈改为 1.5R，优先捕捉过热后的一段大跌幅。",
            },
        ),
        (
            "D_extreme_overheat_fade",
            {
                "code": "D",
                "signal_name": "extreme_overheat_fade",
                "label": "D / Extreme Overheat Fade",
                "short_label": "D层",
                "entry_filters": [],
                "requires_no_breakout_exit": False,
                "target_r_multiple": 1.0,
                "description": "仍在交叉候选池内，进入极端过热区后，darkhorse 和 overlap 分数同时转弱。",
            },
        ),
        (
            "D_extreme_overheat_fade_wide",
            {
                "code": "D+",
                "signal_name": "extreme_overheat_fade_wide",
                "label": "D+ / Extreme Wide",
                "short_label": "D+层",
                "entry_filters": [],
                "requires_no_breakout_exit": False,
                "stop_window_min_pct": CONTROL_STOP_WINDOW_MIN_PCT,
                "stop_window_max_pct": CONTROL_STOP_WINDOW_MAX_PCT,
                "target_r_multiple": CONTROL_TARGET_R_MULTIPLE,
                "description": "D 对照组：结构止损窗口放宽到 3%~20%，止盈改为 1.5R，专门测试极端过热后的大幅回撤。",
            },
        ),
    ]
)


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


def get_current_price(row):
    return safe_float(row.get("binance_last_price")) or safe_float(row.get("price_usd"))


def count_true(*flags):
    return sum(1 for flag in flags if flag)


def short_tier_label(tier):
    return {"sniper": "高置信狙击", "standard": "标准开空", "watch": "观察", "none": "未触发"}.get(tier, "--")


def shadow_layer_label(strategy_id):
    return (SHADOW_STRATEGY_LAYERS.get(strategy_id) or {}).get("label") or strategy_id


def stop_tradable_for_window(stop_pct, min_pct, max_pct):
    stop_pct = safe_float(stop_pct)
    min_pct = safe_float(min_pct)
    max_pct = safe_float(max_pct)
    return stop_pct is not None and min_pct is not None and max_pct is not None and min_pct <= stop_pct <= max_pct


def stop_window_blocker(stop_pct, min_pct, max_pct):
    return f"结构止损{stop_pct:.2f}%不在{min_pct:.1f}%~{max_pct:.1f}%"


def compute_short_target_price(entry_price, stop_price, target_r_multiple=1.0):
    entry_price = safe_float(entry_price)
    stop_price = safe_float(stop_price)
    target_r_multiple = safe_float(target_r_multiple) or 1.0
    if entry_price in (None, 0) or stop_price is None or target_r_multiple <= 0:
        return None
    risk_abs = stop_price - entry_price
    if risk_abs <= 0:
        return None
    return entry_price - risk_abs * target_r_multiple


def load_symbol_1h_klines(symbol: str):
    symbol = (symbol or "").upper()
    if symbol in KLINE_CACHE:
        return KLINE_CACHE[symbol]

    path = KLINES_DIR / symbol / "1h" / "candles.csv"
    rows = []
    if path.exists():
        with path.open("r", encoding="utf-8", newline="") as handle:
            reader = csv.DictReader(handle)
            for row in reader:
                open_dt = parse_dt(row.get("open_time_utc"))
                close_dt = parse_dt(row.get("close_time_utc"))
                high = safe_float(row.get("high_price"))
                low = safe_float(row.get("low_price"))
                close = safe_float(row.get("close_price"))
                if not open_dt or not close_dt or high is None or low is None or close is None:
                    continue
                rows.append(
                    {
                        "open_dt": open_dt,
                        "close_dt": close_dt,
                        "high": high,
                        "low": low,
                        "close": close,
                    }
                )
    rows.sort(key=lambda item: item["open_dt"])
    KLINE_CACHE[symbol] = rows
    return rows


def compute_atr_1h_pct(candles, entry_dt, entry_price):
    if entry_price in (None, 0):
        return None

    closed = [candle for candle in candles if candle["close_dt"] <= entry_dt]
    if len(closed) < STRUCTURE_ATR_PERIOD + 1:
        return None

    true_ranges = []
    prev_close = closed[0]["close"]
    for candle in closed[1:]:
        true_ranges.append(
            max(
                candle["high"] - candle["low"],
                abs(candle["high"] - prev_close),
                abs(candle["low"] - prev_close),
            )
        )
        prev_close = candle["close"]

    recent_trs = true_ranges[-STRUCTURE_ATR_PERIOD:]
    if len(recent_trs) < STRUCTURE_ATR_PERIOD:
        return None

    atr_abs = sum(recent_trs) / len(recent_trs)
    return (atr_abs / entry_price) * 100 if entry_price else None


def compute_structure_context(row):
    entry_dt = parse_dt(row.get("captured_at_utc"))
    entry_price = get_current_price(row)
    if not entry_dt or entry_price in (None, 0):
        return {}

    candles = load_symbol_1h_klines(row.get("symbol"))
    if not candles:
        return {}

    closed = [candle for candle in candles if candle["close_dt"] <= entry_dt]
    if not closed:
        return {}

    front_cutoff = entry_dt - timedelta(hours=STRUCTURE_FRONT_HIGH_LOOKBACK_H)
    front_highs = [candle["high"] for candle in closed if candle["close_dt"] > front_cutoff]
    front_high_price = max(front_highs) if front_highs else entry_price

    vol_cutoff = entry_dt - timedelta(hours=STRUCTURE_VOL_LOOKBACK_H)
    vol_window = [candle for candle in closed if candle["close_dt"] > vol_cutoff]
    snapshot_range_1h_pct = None
    if vol_window and entry_price:
        window_high = max(candle["high"] for candle in vol_window)
        window_low = min(candle["low"] for candle in vol_window)
        snapshot_range_1h_pct = ((window_high - window_low) / entry_price) * 100

    atr_1h_pct = compute_atr_1h_pct(candles, entry_dt, entry_price)
    vol_base_pct = atr_1h_pct if atr_1h_pct is not None else snapshot_range_1h_pct
    vol_source = "kline_1h_atr14" if atr_1h_pct is not None else ("kline_1h_range_proxy" if snapshot_range_1h_pct is not None else None)
    stop_anchor_price = max(front_high_price, entry_price)
    stop_buffer_pct = max(STRUCTURE_MIN_BUFFER_PCT, (vol_base_pct or 0) * STRUCTURE_STOP_BUFFER_MULT)
    stop_price = stop_anchor_price * (1 + stop_buffer_pct / 100)
    stop_pct = ((stop_price / entry_price) - 1) * 100 if entry_price else None
    risk_abs = stop_price - entry_price if stop_price is not None else None
    target_price_r1 = entry_price - risk_abs if risk_abs is not None else None
    stop_tradable = stop_pct is not None and STRUCTURE_STOP_MIN_PCT <= stop_pct <= STRUCTURE_STOP_MAX_PCT

    return {
        "structure_front_high_price": front_high_price,
        "structure_stop_anchor_price": stop_anchor_price,
        "structure_atr_1h_pct": atr_1h_pct,
        "structure_snapshot_range_1h_pct": snapshot_range_1h_pct,
        "structure_vol_base_pct": vol_base_pct,
        "structure_vol_source": vol_source,
        "structure_stop_buffer_pct": stop_buffer_pct,
        "structure_stop_price": stop_price,
        "structure_stop_pct": stop_pct,
        "structure_target_price_r1": target_price_r1,
        "structure_stop_tradable": stop_tradable,
        "structure_stop_window_min_pct": STRUCTURE_STOP_MIN_PCT,
        "structure_stop_window_max_pct": STRUCTURE_STOP_MAX_PCT,
    }


def build_short_signal(row):
    enriched = {**row, **compute_structure_context(row)}
    overlap = bool(enriched.get("overlap_candidate"))
    recent_overlap = bool(enriched.get("recent_overlap_candidate_2h"))
    overlap_anchor_active = overlap or recent_overlap
    trend_1h = str(enriched.get("trend_1h") or "")
    weak_trend_values = set(WEAKENING_CONFIG.get("trend_1h_values") or ["Range", "Down", "StrongDown"])
    weak_trend = trend_1h in weak_trend_values
    overlap_score_delta = safe_float(enriched.get("overlap_score_delta_30m"))
    overlap_delta_cap = safe_float(WEAKENING_CONFIG.get("overlap_score_delta_30m_max"))
    if overlap_delta_cap is None:
        overlap_delta_cap = 0.0
    overlap_delta_weak = overlap_score_delta is not None and overlap_score_delta <= overlap_delta_cap
    breakout_required = str(WEAKENING_CONFIG.get("breakout_1h_required") or "NoBreakout")
    no_breakout = str(enriched.get("breakout_1h") or "") == breakout_required
    change_24h = safe_float(enriched.get("change_24h_pct"))
    change_min = safe_float(WEAKENING_CONFIG.get("change_24h_min_pct"))
    change_max = safe_float(WEAKENING_CONFIG.get("change_24h_max_pct"))
    if change_min is None:
        change_min = 3.0
    if change_max is None:
        change_max = 8.0
    change_in_range = change_24h is not None and change_min <= change_24h <= change_max
    top15_hours = safe_float(enriched.get("top15_persistence_hours"))
    min_top15_hours = safe_float(ANCHOR_CONFIG.get("min_top15_persistence_hours"))
    if min_top15_hours is None:
        min_top15_hours = 1.0
    enough_persistence = (top15_hours is not None and top15_hours >= min_top15_hours) or overlap_anchor_active

    structure_stop_pct = safe_float(enriched.get("structure_stop_pct"))
    stop_tradable = bool(enriched.get("structure_stop_tradable"))

    oi_change_1h_pct = safe_float(enriched.get("oi_change_1h_pct"))
    oi_expand_min = safe_float(HISTORICAL_SNIPER_CONFIG.get("oi_change_1h_pct_min_exclusive"))
    if oi_expand_min is None:
        oi_expand_min = safe_float(LIVE_SNIPER_CONFIG.get("oi_change_1h_pct_min_exclusive"))
    if oi_expand_min is None:
        oi_expand_min = 0.0
    oi_expanding = oi_change_1h_pct is not None and oi_change_1h_pct > oi_expand_min
    perp_premium_pct = safe_float(enriched.get("perp_premium_pct_vs_spot"))
    premium_discount_max = safe_float(LIVE_SNIPER_CONFIG.get("perp_premium_pct_vs_spot_max"))
    if premium_discount_max is None:
        premium_discount_max = -0.4
    premium_deep_discount = perp_premium_pct is not None and perp_premium_pct <= premium_discount_max

    basis_rate_latest = safe_float(enriched.get("basis_rate_latest"))
    basis_rate_delta_vs_mean_1h = safe_float(enriched.get("basis_rate_delta_vs_mean_1h"))
    top_trader_account_lsr_latest = safe_float(enriched.get("top_trader_account_lsr_latest"))
    top_trader_position_lsr_change_1h_pct = safe_float(enriched.get("top_trader_position_lsr_change_1h_pct"))
    basis_weakening_max = safe_float(DEFAULT_CONFIRM_CONFIG.get("basis_rate_delta_vs_mean_1h_max"))
    if basis_weakening_max is None:
        basis_weakening_max = 0.0
    basis_weakening = basis_rate_delta_vs_mean_1h is not None and basis_rate_delta_vs_mean_1h <= basis_weakening_max
    top_position_unwinding_max = safe_float(DEFAULT_CONFIRM_CONFIG.get("top_trader_position_lsr_change_1h_pct_max"))
    if top_position_unwinding_max is None:
        top_position_unwinding_max = 0.0
    top_position_unwinding = (
        top_trader_position_lsr_change_1h_pct is not None and top_trader_position_lsr_change_1h_pct < top_position_unwinding_max
    )
    basis_extreme_discount_max = safe_float(HISTORICAL_SNIPER_CONFIG.get("basis_rate_latest_max"))
    if basis_extreme_discount_max is None:
        basis_extreme_discount_max = -0.006
    basis_extreme_discount = basis_rate_latest is not None and basis_rate_latest <= basis_extreme_discount_max
    top_account_crowded_min = safe_float(HISTORICAL_SNIPER_CONFIG.get("top_trader_account_lsr_latest_min"))
    if top_account_crowded_min is None:
        top_account_crowded_min = 1.18
    top_account_crowded = top_trader_account_lsr_latest is not None and top_trader_account_lsr_latest >= top_account_crowded_min

    base_signal = overlap_anchor_active and weak_trend and overlap_delta_weak
    standard_ready = base_signal and no_breakout and change_in_range and enough_persistence and stop_tradable
    historical_default_confirm = basis_weakening or top_position_unwinding
    historical_sniper_confirm = oi_expanding and (basis_extreme_discount or top_account_crowded)
    live_replacement_sniper = oi_expanding and premium_deep_discount
    sniper_ready = standard_ready and (historical_sniper_confirm or live_replacement_sniper)
    tier = "sniper" if sniper_ready else ("standard" if standard_ready else ("watch" if base_signal else None))

    blockers = []
    if not overlap_anchor_active:
        blockers.append(f"当前及近{RECENT_OVERLAP_WINDOW_H:g}h未进入确认锚点")
    if overlap_anchor_active and not weak_trend:
        blockers.append("1h趋势尚未转弱")
    if overlap_anchor_active and weak_trend and not overlap_delta_weak:
        blockers.append("30m交叉分仍在上行")
    if base_signal and not no_breakout:
        blockers.append("1h仍有突破结构")
    if base_signal and not change_in_range:
        blockers.append(f"24h涨幅不在{change_min:g}%~{change_max:g}%")
    if base_signal and not enough_persistence:
        blockers.append("确认锚点和在榜时长都不足")
    if base_signal and structure_stop_pct is None:
        blockers.append("缺少结构止损上下文")
    if base_signal and structure_stop_pct is not None and not stop_tradable:
        blockers.append(f"结构止损{structure_stop_pct:.2f}%不在{STRUCTURE_STOP_MIN_PCT:.1f}%~{STRUCTURE_STOP_MAX_PCT:.1f}%")
    if standard_ready and not historical_default_confirm:
        blockers.append("默认确认层未点亮或字段待补采")
    if standard_ready and not historical_sniper_confirm and not live_replacement_sniper:
        blockers.append("高置信确认层未点亮")

    quality_score = count_true(
        overlap_anchor_active,
        weak_trend,
        overlap_delta_weak,
        no_breakout,
        change_in_range,
        enough_persistence,
        stop_tradable,
        oi_expanding,
        premium_deep_discount,
        historical_default_confirm,
        historical_sniper_confirm,
    )

    historical_default_status = (
        "已点亮"
        if historical_default_confirm
        else ("待补采" if basis_rate_delta_vs_mean_1h is None and top_trader_position_lsr_change_1h_pct is None else "未点亮")
    )
    historical_sniper_status = (
        "已点亮"
        if historical_sniper_confirm
        else ("待补采" if basis_rate_latest is None and top_trader_account_lsr_latest is None else "未点亮")
    )
    live_replacement_status = (
        "已点亮" if live_replacement_sniper else ("待补采" if oi_change_1h_pct is None and perp_premium_pct is None else "未点亮")
    )

    signal_summary = (
        "确认锚点已成立且动能转弱，在线高置信替代确认点亮：OI 1h 扩张 + 永续贴水加深。"
        if sniper_ready
        else (
            "最近确认过的强趋势已经转弱，满足结构止损标准开空。"
            if standard_ready
            else (
                "最近确认过的强趋势已进入转弱观察阶段，先观察，不提前开空。"
                if base_signal
                else "当前仍未形成可执行的后确认转弱信号。"
            )
        )
    )

    return {
        "row": enriched,
        "symbol": enriched.get("symbol"),
        "name": enriched.get("name"),
        "tier": tier,
        "quality_score": quality_score,
        "openable": tier in {"standard", "sniper"},
        "current_price": get_current_price(enriched),
        "structure_stop_price": safe_float(enriched.get("structure_stop_price")),
        "structure_stop_pct": structure_stop_pct,
        "structure_target_price_r1": safe_float(enriched.get("structure_target_price_r1")),
        "front_high_price": safe_float(enriched.get("structure_front_high_price")),
        "atr_1h_pct": safe_float(enriched.get("structure_atr_1h_pct")),
        "stop_tradable": stop_tradable,
        "overlap": overlap,
        "recent_overlap": recent_overlap,
        "overlap_anchor_active": overlap_anchor_active,
        "weak_trend": weak_trend,
        "overlap_delta_weak": overlap_delta_weak,
        "no_breakout": no_breakout,
        "change_in_range": change_in_range,
        "enough_persistence": enough_persistence,
        "historical_default_confirm": historical_default_confirm,
        "historical_sniper_confirm": historical_sniper_confirm,
        "live_replacement_sniper": live_replacement_sniper,
        "historical_default_status": historical_default_status,
        "historical_sniper_status": historical_sniper_status,
        "live_replacement_status": live_replacement_status,
        "signal_summary": signal_summary,
        "blockers": blockers,
        "oi_expanding": oi_expanding,
        "premium_deep_discount": premium_deep_discount,
        "basis_weakening": basis_weakening,
        "top_position_unwinding": top_position_unwinding,
        "basis_extreme_discount": basis_extreme_discount,
        "top_account_crowded": top_account_crowded,
        "base_signal": base_signal,
        "standard_ready": standard_ready,
        "sniper_ready": sniper_ready,
    }


def build_shadow_strategy_signals(row):
    base_signal = build_short_signal(row)
    enriched = base_signal.get("row") or dict(row or {})
    overlap = bool(base_signal.get("overlap"))
    overlap_score_delta_30m = safe_float(enriched.get("overlap_score_delta_30m"))
    rank_change_30m = safe_float(enriched.get("rank_change_30m"))
    darkhorse_score_delta_30m = safe_float(enriched.get("darkhorse_score_delta_30m"))
    change_24h_pct = safe_float(enriched.get("change_24h_pct"))
    turnover_ratio_24h = safe_float(enriched.get("turnover_ratio_24h"))
    no_breakout = bool(base_signal.get("no_breakout"))
    stop_tradable = bool(base_signal.get("stop_tradable"))
    current_price = base_signal.get("current_price")
    structure_stop_price = base_signal.get("structure_stop_price")
    structure_stop_pct = base_signal.get("structure_stop_pct")
    standard_target_r_multiple = 1.0
    standard_target_price = base_signal.get("structure_target_price_r1")
    wide_stop_tradable = stop_tradable_for_window(
        structure_stop_pct,
        CONTROL_STOP_WINDOW_MIN_PCT,
        CONTROL_STOP_WINDOW_MAX_PCT,
    )
    wide_target_r_multiple = CONTROL_TARGET_R_MULTIPLE
    wide_target_price = compute_short_target_price(current_price, structure_stop_price, wide_target_r_multiple)
    generic_weakening = (
        rank_change_30m is not None
        and overlap_score_delta_30m is not None
        and rank_change_30m <= 0
        and overlap_score_delta_30m <= 0
    )
    extreme_weakening = (
        darkhorse_score_delta_30m is not None
        and overlap_score_delta_30m is not None
        and darkhorse_score_delta_30m <= 0
        and overlap_score_delta_30m <= 0
    )

    layers = OrderedDict()
    layers["A_post_confirm_weak_turn"] = {
        "strategy_id": "A_post_confirm_weak_turn",
        "strategy_code": "A",
        "strategy_label": shadow_layer_label("A_post_confirm_weak_turn"),
        "signal_name": SHADOW_STRATEGY_LAYERS["A_post_confirm_weak_turn"]["signal_name"],
        "description": SHADOW_STRATEGY_LAYERS["A_post_confirm_weak_turn"]["description"],
        "row": enriched,
        "tier": base_signal.get("tier"),
        "quality_score": base_signal.get("quality_score"),
        "triggered": bool(base_signal.get("openable")),
        "openable": bool(base_signal.get("openable")),
        "anchor_active": bool(base_signal.get("overlap_anchor_active")),
        "weakness_active": bool(base_signal.get("weak_trend")) and bool(base_signal.get("overlap_delta_weak")),
        "breakout_guard": no_breakout,
        "requires_no_breakout_exit": True,
        "signal_summary": base_signal.get("signal_summary"),
        "blockers": list(base_signal.get("blockers") or []),
        "current_price": current_price,
        "structure_stop_price": structure_stop_price,
        "structure_stop_pct": structure_stop_pct,
        "structure_target_price": standard_target_price,
        "structure_target_price_r1": standard_target_price,
        "target_r_multiple": standard_target_r_multiple,
        "front_high_price": base_signal.get("front_high_price"),
        "atr_1h_pct": base_signal.get("atr_1h_pct"),
        "stop_tradable": stop_tradable,
        "stop_window_min_pct": STRUCTURE_STOP_MIN_PCT,
        "stop_window_max_pct": STRUCTURE_STOP_MAX_PCT,
        "overlap_score": safe_float(enriched.get("overlap_score")),
    }

    b_triggered = overlap and generic_weakening and no_breakout
    b_blockers = []
    if not overlap:
        b_blockers.append("当前不在交叉候选池内")
    if overlap and not generic_weakening:
        b_blockers.append("30m 排名或交叉分尚未转弱")
    if overlap and generic_weakening and not no_breakout:
        b_blockers.append("1h 仍有突破结构")
    if b_triggered and structure_stop_pct is None:
        b_blockers.append("缺少结构止损上下文")
    if b_triggered and structure_stop_pct is not None and not stop_tradable:
        b_blockers.append(stop_window_blocker(structure_stop_pct, STRUCTURE_STOP_MIN_PCT, STRUCTURE_STOP_MAX_PCT))
    layers["B_no_breakout_fade"] = {
        "strategy_id": "B_no_breakout_fade",
        "strategy_code": "B",
        "strategy_label": shadow_layer_label("B_no_breakout_fade"),
        "signal_name": SHADOW_STRATEGY_LAYERS["B_no_breakout_fade"]["signal_name"],
        "description": SHADOW_STRATEGY_LAYERS["B_no_breakout_fade"]["description"],
        "row": enriched,
        "tier": "shadow",
        "quality_score": count_true(overlap, generic_weakening, no_breakout, stop_tradable),
        "triggered": b_triggered,
        "openable": b_triggered and stop_tradable,
        "anchor_active": overlap,
        "weakness_active": generic_weakening,
        "breakout_guard": no_breakout,
        "requires_no_breakout_exit": True,
        "signal_summary": "交叉候选仍在池内，30m 排名和交叉分同步转弱，且 1h 已无突破结构，进入 NoBreakout Fade。",
        "blockers": b_blockers,
        "current_price": current_price,
        "structure_stop_price": structure_stop_price,
        "structure_stop_pct": structure_stop_pct,
        "structure_target_price": standard_target_price,
        "structure_target_price_r1": standard_target_price,
        "target_r_multiple": standard_target_r_multiple,
        "front_high_price": base_signal.get("front_high_price"),
        "atr_1h_pct": base_signal.get("atr_1h_pct"),
        "stop_tradable": stop_tradable,
        "stop_window_min_pct": STRUCTURE_STOP_MIN_PCT,
        "stop_window_max_pct": STRUCTURE_STOP_MAX_PCT,
        "overlap_score": safe_float(enriched.get("overlap_score")),
    }

    b_wide_blockers = []
    if not overlap:
        b_wide_blockers.append("当前不在交叉候选池内")
    if overlap and not generic_weakening:
        b_wide_blockers.append("30m 排名或交叉分尚未转弱")
    if overlap and generic_weakening and not no_breakout:
        b_wide_blockers.append("1h 仍有突破结构")
    if b_triggered and structure_stop_pct is None:
        b_wide_blockers.append("缺少结构止损上下文")
    if b_triggered and structure_stop_pct is not None and not wide_stop_tradable:
        b_wide_blockers.append(stop_window_blocker(structure_stop_pct, CONTROL_STOP_WINDOW_MIN_PCT, CONTROL_STOP_WINDOW_MAX_PCT))
    layers["B_no_breakout_fade_wide"] = {
        "strategy_id": "B_no_breakout_fade_wide",
        "strategy_code": "B+",
        "strategy_label": shadow_layer_label("B_no_breakout_fade_wide"),
        "signal_name": SHADOW_STRATEGY_LAYERS["B_no_breakout_fade_wide"]["signal_name"],
        "description": SHADOW_STRATEGY_LAYERS["B_no_breakout_fade_wide"]["description"],
        "row": enriched,
        "tier": "shadow",
        "quality_score": count_true(overlap, generic_weakening, no_breakout, wide_stop_tradable),
        "triggered": b_triggered,
        "openable": b_triggered and wide_stop_tradable,
        "anchor_active": overlap,
        "weakness_active": generic_weakening,
        "breakout_guard": no_breakout,
        "requires_no_breakout_exit": True,
        "signal_summary": "交叉候选仍在池内，30m 排名和交叉分同步转弱，且 1h 已无突破结构，进入 NoBreakout Wide 对照组。",
        "blockers": b_wide_blockers,
        "current_price": current_price,
        "structure_stop_price": structure_stop_price,
        "structure_stop_pct": structure_stop_pct,
        "structure_target_price": wide_target_price,
        "structure_target_price_r1": standard_target_price,
        "target_r_multiple": wide_target_r_multiple,
        "front_high_price": base_signal.get("front_high_price"),
        "atr_1h_pct": base_signal.get("atr_1h_pct"),
        "stop_tradable": wide_stop_tradable,
        "stop_window_min_pct": CONTROL_STOP_WINDOW_MIN_PCT,
        "stop_window_max_pct": CONTROL_STOP_WINDOW_MAX_PCT,
        "overlap_score": safe_float(enriched.get("overlap_score")),
    }

    c_overheat = (
        change_24h_pct is not None
        and turnover_ratio_24h is not None
        and change_24h_pct >= 15
        and turnover_ratio_24h >= 0.5
    )
    c_triggered = overlap and generic_weakening and c_overheat
    c_blockers = []
    if not overlap:
        c_blockers.append("当前不在交叉候选池内")
    if overlap and not generic_weakening:
        c_blockers.append("30m 排名或交叉分尚未转弱")
    if overlap and generic_weakening and not c_overheat:
        c_blockers.append("24h 涨幅或换手尚未进入过热区")
    if c_triggered and structure_stop_pct is None:
        c_blockers.append("缺少结构止损上下文")
    if c_triggered and structure_stop_pct is not None and not stop_tradable:
        c_blockers.append(stop_window_blocker(structure_stop_pct, STRUCTURE_STOP_MIN_PCT, STRUCTURE_STOP_MAX_PCT))
    layers["C_overheat_fade"] = {
        "strategy_id": "C_overheat_fade",
        "strategy_code": "C",
        "strategy_label": shadow_layer_label("C_overheat_fade"),
        "signal_name": SHADOW_STRATEGY_LAYERS["C_overheat_fade"]["signal_name"],
        "description": SHADOW_STRATEGY_LAYERS["C_overheat_fade"]["description"],
        "row": enriched,
        "tier": "shadow",
        "quality_score": count_true(overlap, generic_weakening, c_overheat, stop_tradable),
        "triggered": c_triggered,
        "openable": c_triggered and stop_tradable,
        "anchor_active": overlap,
        "weakness_active": generic_weakening,
        "breakout_guard": no_breakout,
        "requires_no_breakout_exit": False,
        "signal_summary": "交叉候选已进入过热区，30m 动能开始转弱，进入 Overheat Fade。",
        "blockers": c_blockers,
        "current_price": current_price,
        "structure_stop_price": structure_stop_price,
        "structure_stop_pct": structure_stop_pct,
        "structure_target_price": standard_target_price,
        "structure_target_price_r1": standard_target_price,
        "target_r_multiple": standard_target_r_multiple,
        "front_high_price": base_signal.get("front_high_price"),
        "atr_1h_pct": base_signal.get("atr_1h_pct"),
        "stop_tradable": stop_tradable,
        "stop_window_min_pct": STRUCTURE_STOP_MIN_PCT,
        "stop_window_max_pct": STRUCTURE_STOP_MAX_PCT,
        "overlap_score": safe_float(enriched.get("overlap_score")),
    }

    c_wide_blockers = []
    if not overlap:
        c_wide_blockers.append("当前不在交叉候选池内")
    if overlap and not generic_weakening:
        c_wide_blockers.append("30m 排名或交叉分尚未转弱")
    if overlap and generic_weakening and not c_overheat:
        c_wide_blockers.append("24h 涨幅或换手尚未进入过热区")
    if c_triggered and structure_stop_pct is None:
        c_wide_blockers.append("缺少结构止损上下文")
    if c_triggered and structure_stop_pct is not None and not wide_stop_tradable:
        c_wide_blockers.append(stop_window_blocker(structure_stop_pct, CONTROL_STOP_WINDOW_MIN_PCT, CONTROL_STOP_WINDOW_MAX_PCT))
    layers["C_overheat_fade_wide"] = {
        "strategy_id": "C_overheat_fade_wide",
        "strategy_code": "C+",
        "strategy_label": shadow_layer_label("C_overheat_fade_wide"),
        "signal_name": SHADOW_STRATEGY_LAYERS["C_overheat_fade_wide"]["signal_name"],
        "description": SHADOW_STRATEGY_LAYERS["C_overheat_fade_wide"]["description"],
        "row": enriched,
        "tier": "shadow",
        "quality_score": count_true(overlap, generic_weakening, c_overheat, wide_stop_tradable),
        "triggered": c_triggered,
        "openable": c_triggered and wide_stop_tradable,
        "anchor_active": overlap,
        "weakness_active": generic_weakening,
        "breakout_guard": no_breakout,
        "requires_no_breakout_exit": False,
        "signal_summary": "交叉候选已进入过热区，30m 动能开始转弱，进入 Overheat Wide 对照组。",
        "blockers": c_wide_blockers,
        "current_price": current_price,
        "structure_stop_price": structure_stop_price,
        "structure_stop_pct": structure_stop_pct,
        "structure_target_price": wide_target_price,
        "structure_target_price_r1": standard_target_price,
        "target_r_multiple": wide_target_r_multiple,
        "front_high_price": base_signal.get("front_high_price"),
        "atr_1h_pct": base_signal.get("atr_1h_pct"),
        "stop_tradable": wide_stop_tradable,
        "stop_window_min_pct": CONTROL_STOP_WINDOW_MIN_PCT,
        "stop_window_max_pct": CONTROL_STOP_WINDOW_MAX_PCT,
        "overlap_score": safe_float(enriched.get("overlap_score")),
    }

    d_overheat = (
        change_24h_pct is not None
        and turnover_ratio_24h is not None
        and change_24h_pct >= 20
        and turnover_ratio_24h >= 0.8
    )
    d_triggered = overlap and extreme_weakening and d_overheat
    d_blockers = []
    if not overlap:
        d_blockers.append("当前不在交叉候选池内")
    if overlap and not extreme_weakening:
        d_blockers.append("darkhorse / overlap 30m 分数尚未同步转弱")
    if overlap and extreme_weakening and not d_overheat:
        d_blockers.append("尚未进入极端过热区")
    if d_triggered and structure_stop_pct is None:
        d_blockers.append("缺少结构止损上下文")
    if d_triggered and structure_stop_pct is not None and not stop_tradable:
        d_blockers.append(stop_window_blocker(structure_stop_pct, STRUCTURE_STOP_MIN_PCT, STRUCTURE_STOP_MAX_PCT))
    layers["D_extreme_overheat_fade"] = {
        "strategy_id": "D_extreme_overheat_fade",
        "strategy_code": "D",
        "strategy_label": shadow_layer_label("D_extreme_overheat_fade"),
        "signal_name": SHADOW_STRATEGY_LAYERS["D_extreme_overheat_fade"]["signal_name"],
        "description": SHADOW_STRATEGY_LAYERS["D_extreme_overheat_fade"]["description"],
        "row": enriched,
        "tier": "shadow",
        "quality_score": count_true(overlap, extreme_weakening, d_overheat, stop_tradable),
        "triggered": d_triggered,
        "openable": d_triggered and stop_tradable,
        "anchor_active": overlap,
        "weakness_active": extreme_weakening,
        "breakout_guard": no_breakout,
        "requires_no_breakout_exit": False,
        "signal_summary": "交叉候选进入极端过热区后，darkhorse 与 overlap 分数同步转弱，进入 Extreme Overheat Fade。",
        "blockers": d_blockers,
        "current_price": current_price,
        "structure_stop_price": structure_stop_price,
        "structure_stop_pct": structure_stop_pct,
        "structure_target_price": standard_target_price,
        "structure_target_price_r1": standard_target_price,
        "target_r_multiple": standard_target_r_multiple,
        "front_high_price": base_signal.get("front_high_price"),
        "atr_1h_pct": base_signal.get("atr_1h_pct"),
        "stop_tradable": stop_tradable,
        "stop_window_min_pct": STRUCTURE_STOP_MIN_PCT,
        "stop_window_max_pct": STRUCTURE_STOP_MAX_PCT,
        "overlap_score": safe_float(enriched.get("overlap_score")),
    }

    d_wide_blockers = []
    if not overlap:
        d_wide_blockers.append("当前不在交叉候选池内")
    if overlap and not extreme_weakening:
        d_wide_blockers.append("darkhorse / overlap 30m 分数尚未同步转弱")
    if overlap and extreme_weakening and not d_overheat:
        d_wide_blockers.append("尚未进入极端过热区")
    if d_triggered and structure_stop_pct is None:
        d_wide_blockers.append("缺少结构止损上下文")
    if d_triggered and structure_stop_pct is not None and not wide_stop_tradable:
        d_wide_blockers.append(stop_window_blocker(structure_stop_pct, CONTROL_STOP_WINDOW_MIN_PCT, CONTROL_STOP_WINDOW_MAX_PCT))
    layers["D_extreme_overheat_fade_wide"] = {
        "strategy_id": "D_extreme_overheat_fade_wide",
        "strategy_code": "D+",
        "strategy_label": shadow_layer_label("D_extreme_overheat_fade_wide"),
        "signal_name": SHADOW_STRATEGY_LAYERS["D_extreme_overheat_fade_wide"]["signal_name"],
        "description": SHADOW_STRATEGY_LAYERS["D_extreme_overheat_fade_wide"]["description"],
        "row": enriched,
        "tier": "shadow",
        "quality_score": count_true(overlap, extreme_weakening, d_overheat, wide_stop_tradable),
        "triggered": d_triggered,
        "openable": d_triggered and wide_stop_tradable,
        "anchor_active": overlap,
        "weakness_active": extreme_weakening,
        "breakout_guard": no_breakout,
        "requires_no_breakout_exit": False,
        "signal_summary": "交叉候选进入极端过热区后，darkhorse 与 overlap 分数同步转弱，进入 Extreme Wide 对照组。",
        "blockers": d_wide_blockers,
        "current_price": current_price,
        "structure_stop_price": structure_stop_price,
        "structure_stop_pct": structure_stop_pct,
        "structure_target_price": wide_target_price,
        "structure_target_price_r1": standard_target_price,
        "target_r_multiple": wide_target_r_multiple,
        "front_high_price": base_signal.get("front_high_price"),
        "atr_1h_pct": base_signal.get("atr_1h_pct"),
        "stop_tradable": wide_stop_tradable,
        "stop_window_min_pct": CONTROL_STOP_WINDOW_MIN_PCT,
        "stop_window_max_pct": CONTROL_STOP_WINDOW_MAX_PCT,
        "overlap_score": safe_float(enriched.get("overlap_score")),
    }

    return layers


def compute_short_setup_fields(row):
    signal = build_short_signal(row)
    enriched = signal.get("row") or dict(row)
    structure_fields = {
        key: enriched.get(key)
        for key in [
            "structure_front_high_price",
            "structure_stop_anchor_price",
            "structure_atr_1h_pct",
            "structure_snapshot_range_1h_pct",
            "structure_vol_base_pct",
            "structure_vol_source",
            "structure_stop_buffer_pct",
            "structure_stop_price",
            "structure_stop_pct",
            "structure_target_price_r1",
            "structure_stop_tradable",
            "structure_stop_window_min_pct",
            "structure_stop_window_max_pct",
        ]
    }
    overlap = bool(signal.get("overlap"))
    recent_overlap = bool(signal.get("recent_overlap"))
    anchor_state = "current_confirmed" if overlap else ("recent_confirmed" if recent_overlap else "inactive")
    if signal.get("sniper_ready"):
        weakening_state = "SniperReady"
    elif signal.get("standard_ready"):
        weakening_state = "StandardReady"
    elif signal.get("base_signal"):
        weakening_state = "WeakeningWatch"
    elif signal.get("overlap_anchor_active"):
        weakening_state = "AnchorActive"
    else:
        weakening_state = "Inactive"

    if signal.get("historical_sniper_confirm"):
        unwind_confirm_state = "HistoricalSniperConfirmed"
    elif signal.get("live_replacement_sniper"):
        unwind_confirm_state = "LiveSniperConfirmed"
    elif signal.get("historical_default_confirm"):
        unwind_confirm_state = "DefaultConfirmed"
    elif signal.get("historical_default_status") == "待补采" and signal.get("historical_sniper_status") == "待补采":
        unwind_confirm_state = "PendingData"
    else:
        unwind_confirm_state = "Unconfirmed"

    tier = signal.get("tier") or "none"
    blockers = signal.get("blockers") or []

    return {
        **structure_fields,
        "short_strategy_version": SHORT_STRATEGY_CONFIG.get("strategy_version") or "post_confirm_weak_turn_v1",
        "short_signal_name": STRATEGY_CONFIG.get("signal_name") or "post_confirm_weak_turn",
        "short_setup_tier": tier,
        "short_setup_label": short_tier_label(tier),
        "short_setup_openable": bool(signal.get("openable")),
        "short_setup_quality_score": signal.get("quality_score"),
        "short_signal_openable": bool(signal.get("openable")),
        "short_signal_quality_score": signal.get("quality_score"),
        "short_signal_summary": signal.get("signal_summary"),
        "confirm_anchor_state": anchor_state,
        "confirm_anchor_active": bool(signal.get("overlap_anchor_active")),
        "confirm_anchor_age_hours": safe_float(enriched.get("hours_since_last_overlap_candidate")),
        "confirm_anchor_window_hours": RECENT_OVERLAP_WINDOW_H,
        "weakening_state": weakening_state,
        "weakening_score": signal.get("quality_score"),
        "unwind_confirm_state": unwind_confirm_state,
        "short_blockers": "|".join(blockers),
        "short_blocker_count": len(blockers),
        "short_base_signal": bool(signal.get("base_signal")),
        "short_standard_ready": bool(signal.get("standard_ready")),
        "short_sniper_ready": bool(signal.get("sniper_ready")),
        "short_historical_default_confirm": bool(signal.get("historical_default_confirm")),
        "short_historical_sniper_confirm": bool(signal.get("historical_sniper_confirm")),
        "short_live_replacement_sniper": bool(signal.get("live_replacement_sniper")),
        "short_historical_default_status": signal.get("historical_default_status"),
        "short_historical_sniper_status": signal.get("historical_sniper_status"),
        "short_live_replacement_status": signal.get("live_replacement_status"),
        "short_oi_expanding": bool(signal.get("oi_expanding")),
        "short_premium_deep_discount": bool(signal.get("premium_deep_discount")),
        "short_basis_weakening": bool(signal.get("basis_weakening")),
        "short_top_position_unwinding": bool(signal.get("top_position_unwinding")),
        "short_basis_extreme_discount": bool(signal.get("basis_extreme_discount")),
        "short_top_account_crowded": bool(signal.get("top_account_crowded")),
    }


def enrich_row_with_short_setup(row):
    return {**row, **compute_short_setup_fields(row)}
