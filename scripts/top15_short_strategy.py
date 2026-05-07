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
CONTROL_STOP_FLOOR_PCT = 10.5
OI_POCKET_STOP_MIN_PCT = 3.0
OI_POCKET_STOP_MAX_PCT = 12.0
OI_POCKET_TURNOVER_MIN = 0.5
OI_POCKET_OI_CHANGE_1H_MIN = 1.5
OI_POCKET_FUNDING_MEAN_24H_MIN = 0.0
OI_POCKET_PRICE_CHANGE_4H_MIN = 2.0

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
            "B_no_breakout_fade_wide_hold",
            {
                "code": "B++",
                "signal_name": "no_breakout_fade_wide_hold",
                "label": "B++ / NoBreakout Hold-Split",
                "short_label": "B++层",
                "entry_filters": [],
                "requires_no_breakout_exit": False,
                "stop_window_min_pct": CONTROL_STOP_WINDOW_MIN_PCT,
                "stop_window_max_pct": CONTROL_STOP_WINDOW_MAX_PCT,
                "target_r_multiple": CONTROL_TARGET_R_MULTIPLE,
                "description": "B+ 的持仓拆分版：入场仍要求 NoBreakout + 30m 转弱，但持仓只看重新走强、突破恢复或回到前高，不因 entry 条件自然衰减而提前离场。",
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
            "C_overheat_fade_wide_hold",
            {
                "code": "C++",
                "signal_name": "overheat_fade_wide_hold",
                "label": "C++ / Overheat Hold-Split",
                "short_label": "C++层",
                "entry_filters": [],
                "requires_no_breakout_exit": False,
                "stop_window_min_pct": CONTROL_STOP_WINDOW_MIN_PCT,
                "stop_window_max_pct": CONTROL_STOP_WINDOW_MAX_PCT,
                "target_r_multiple": CONTROL_TARGET_R_MULTIPLE,
                "description": "C+ 的持仓拆分版：入场仍要求过热 + 30m 转弱，但持仓不再要求继续过热或继续 overlap，只在重新走强或回到前高时提前退出。",
            },
        ),
        (
            "C_overheat_fade_wide_hold_floor_10_5",
            {
                "code": "C++++",
                "signal_name": "overheat_fade_wide_hold_floor_10_5",
                "label": "C++++ / Overheat Hold-Floor 10.5",
                "short_label": "C++++层",
                "entry_filters": [],
                "requires_no_breakout_exit": False,
                "stop_window_min_pct": CONTROL_STOP_WINDOW_MIN_PCT,
                "stop_window_max_pct": CONTROL_STOP_WINDOW_MAX_PCT,
                "target_r_multiple": CONTROL_TARGET_R_MULTIPLE,
                "stop_floor_pct": CONTROL_STOP_FLOOR_PCT,
                "description": "C++ 的止损地板版：入场与持有逻辑保持不变，但当结构止损小于 3% 时，统一抬到 10.5% 再计算 1.5R 止盈；3%~20% 保持原结构止损，大于 20% 仍拒绝。",
            },
        ),
        (
            "C_overheat_fade_wide_hold_floor_10_5_pause_3l_60m",
            {
                "code": "C++++p",
                "signal_name": "overheat_fade_wide_hold_floor_10_5_pause_3l_60m",
                "label": "P1 / C++++ Pause 3L 60m",
                "short_label": "C++++p",
                "entry_filters": [],
                "requires_no_breakout_exit": False,
                "stop_window_min_pct": CONTROL_STOP_WINDOW_MIN_PCT,
                "stop_window_max_pct": CONTROL_STOP_WINDOW_MAX_PCT,
                "target_r_multiple": CONTROL_TARGET_R_MULTIPLE,
                "stop_floor_pct": CONTROL_STOP_FLOOR_PCT,
                "paper_loss_pause_after_losses": 3,
                "paper_loss_pause_minutes": 60,
                "description": "C++++ 叠加全局风控版：保留 10.5% 止损地板和 C++ 持仓逻辑，并在虚拟盘内加入连续 3 笔亏损后暂停 60 分钟。",
            },
        ),
        (
            "C_overheat_fade_wide_hold_floor_10_5_pause_plus_pos12",
            {
                "code": "C++++pp12",
                "signal_name": "overheat_fade_wide_hold_floor_10_5_pause_plus_pos12",
                "label": "P2 / C++++ Pause + Pos12",
                "short_label": "C++++p12",
                "entry_filters": [],
                "requires_no_breakout_exit": False,
                "stop_window_min_pct": CONTROL_STOP_WINDOW_MIN_PCT,
                "stop_window_max_pct": CONTROL_STOP_WINDOW_MAX_PCT,
                "target_r_multiple": CONTROL_TARGET_R_MULTIPLE,
                "stop_floor_pct": CONTROL_STOP_FLOOR_PCT,
                "paper_loss_pause_after_losses": 3,
                "paper_loss_pause_minutes": 60,
                "paper_structure_filter": "pos12_range_le_0_5",
                "description": "C++++ 组合风控版：在 3 连亏暂停 60 分钟基础上，再增加开仓前 12h 区间位置过滤，若价格已落入近 12h 区间下半区则不再新开空。",
            },
        ),
        (
            "C_overheat_fade_wide_hold_floor_10_5_paper_copy",
            {
                "code": "P0",
                "signal_name": "overheat_fade_wide_hold_floor_10_5_paper_copy",
                "label": "P0 / C++++ Baseline",
                "short_label": "P0",
                "entry_filters": [],
                "requires_no_breakout_exit": False,
                "stop_window_min_pct": CONTROL_STOP_WINDOW_MIN_PCT,
                "stop_window_max_pct": CONTROL_STOP_WINDOW_MAX_PCT,
                "target_r_multiple": CONTROL_TARGET_R_MULTIPLE,
                "stop_floor_pct": CONTROL_STOP_FLOOR_PCT,
                "description": "模拟盘对照组：完全复制当前 C++++，用于从当前时点起和冻结前高版本做并行比较。",
            },
        ),
        (
            "C_overheat_fade_wide_hold_floor_10_5_frozen_front_high",
            {
                "code": "C++++fh",
                "signal_name": "overheat_fade_wide_hold_floor_10_5_frozen_front_high",
                "label": "C++++ FH / Frozen Front High",
                "short_label": "C++++fh",
                "entry_filters": [],
                "requires_no_breakout_exit": False,
                "stop_window_min_pct": CONTROL_STOP_WINDOW_MIN_PCT,
                "stop_window_max_pct": CONTROL_STOP_WINDOW_MAX_PCT,
                "target_r_multiple": CONTROL_TARGET_R_MULTIPLE,
                "stop_floor_pct": CONTROL_STOP_FLOOR_PCT,
                "paper_hold_exit_mode": "frozen_front_high",
                "description": "模拟盘对照组：入场、止损地板和 strength_resume 与当前 C++++ 一致，只把前高退出改成入场冻结前高。",
            },
        ),
        (
            "OI_pocket_v1_hold_12h",
            {
                "code": "OIh12",
                "signal_name": "oi_pocket_v1_hold_12h",
                "label": "OI pocket V1 / Hold 12h",
                "short_label": "OIh12",
                "entry_filters": [],
                "requires_no_breakout_exit": False,
                "stop_window_min_pct": OI_POCKET_STOP_MIN_PCT,
                "stop_window_max_pct": OI_POCKET_STOP_MAX_PCT,
                "max_hold_hours": 12.0,
                "paper_hold_exit_mode": "hold_12h",
                "description": "模拟盘原型：1d/4h 强、1h 弱、NoBreakout、turnover>=0.5、OI 1h>=1.5、funding24h>=0、近2h非 recent overlap，止损统一 clip 到 3%~12%，持有到 12h 或提前止损。",
            },
        ),
        (
            "OI_pocket_v1_soft_4h_then_12h",
            {
                "code": "OIs4h",
                "signal_name": "oi_pocket_v1_soft_4h_then_12h",
                "label": "OI pocket V1 / 4h Check",
                "short_label": "OIs4h",
                "entry_filters": [],
                "requires_no_breakout_exit": False,
                "stop_window_min_pct": OI_POCKET_STOP_MIN_PCT,
                "stop_window_max_pct": OI_POCKET_STOP_MAX_PCT,
                "max_hold_hours": 12.0,
                "paper_hold_exit_mode": "soft_4h_then_12h",
                "description": "模拟盘原型：entry pocket 与 OI pocket V1 相同；第 4 小时若利润不足 1% 则提前离场，否则继续持有到 12h 或提前止损。",
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
        (
            "D_extreme_overheat_fade_wide_hold",
            {
                "code": "D++",
                "signal_name": "extreme_overheat_fade_wide_hold",
                "label": "D++ / Extreme Hold-Split",
                "short_label": "D++层",
                "entry_filters": [],
                "requires_no_breakout_exit": False,
                "stop_window_min_pct": CONTROL_STOP_WINDOW_MIN_PCT,
                "stop_window_max_pct": CONTROL_STOP_WINDOW_MAX_PCT,
                "target_r_multiple": CONTROL_TARGET_R_MULTIPLE,
                "description": "D+ 的持仓拆分版：入场仍要求极端过热 + 极端转弱，但持仓只在重新增强或回到前高时退出，不因极端过热消退而离场。",
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


def build_effective_short_stop(
    current_price,
    raw_stop_price,
    raw_stop_pct,
    *,
    stop_floor_pct=None,
    stop_window_min_pct=None,
    stop_window_max_pct=None,
    target_r_multiple=1.0,
):
    current_price = safe_float(current_price)
    raw_stop_price = safe_float(raw_stop_price)
    raw_stop_pct = safe_float(raw_stop_pct)
    stop_floor_pct = safe_float(stop_floor_pct)
    stop_window_min_pct = safe_float(stop_window_min_pct)
    stop_window_max_pct = safe_float(stop_window_max_pct)
    target_r_multiple = safe_float(target_r_multiple) or 1.0

    effective_stop_price = raw_stop_price
    effective_stop_pct = raw_stop_pct
    stop_floor_applied = False
    stop_floor_reason = None

    if (
        current_price not in (None, 0)
        and raw_stop_pct is not None
        and stop_floor_pct is not None
        and stop_window_min_pct is not None
        and raw_stop_pct < stop_window_min_pct
    ):
        effective_stop_pct = stop_floor_pct
        effective_stop_price = current_price * (1 + stop_floor_pct / 100.0)
        stop_floor_applied = True
        stop_floor_reason = f"原始结构止损 {raw_stop_pct:.2f}% 小于最小窗口 {stop_window_min_pct:.1f}%，改用 {stop_floor_pct:.1f}% 固定地板。"

    effective_stop_tradable = stop_tradable_for_window(
        effective_stop_pct,
        stop_window_min_pct,
        stop_window_max_pct,
    )
    effective_target_price = compute_short_target_price(
        current_price,
        effective_stop_price,
        target_r_multiple,
    )
    return {
        "raw_structure_stop_price": raw_stop_price,
        "raw_structure_stop_pct": raw_stop_pct,
        "structure_stop_price": effective_stop_price,
        "structure_stop_pct": effective_stop_pct,
        "structure_target_price": effective_target_price,
        "target_r_multiple": target_r_multiple,
        "stop_floor_pct": stop_floor_pct,
        "stop_floor_applied": stop_floor_applied,
        "stop_floor_reason": stop_floor_reason,
        "stop_tradable": effective_stop_tradable,
    }


def build_clipped_short_stop(current_price, raw_stop_pct, *, min_stop_pct, max_stop_pct):
    current_price = safe_float(current_price)
    raw_stop_pct = safe_float(raw_stop_pct)
    min_stop_pct = safe_float(min_stop_pct)
    max_stop_pct = safe_float(max_stop_pct)
    if current_price in (None, 0) or raw_stop_pct is None or min_stop_pct is None or max_stop_pct is None:
        return {
            "raw_structure_stop_pct": raw_stop_pct,
            "structure_stop_pct": None,
            "structure_stop_price": None,
            "stop_tradable": False,
            "stop_clip_reason": None,
        }
    clipped_stop_pct = min(max(raw_stop_pct, min_stop_pct), max_stop_pct)
    if raw_stop_pct < min_stop_pct:
        clip_reason = f"原始结构止损 {raw_stop_pct:.2f}% 小于 {min_stop_pct:.1f}% ，上调到 {clipped_stop_pct:.1f}% 。"
    elif raw_stop_pct > max_stop_pct:
        clip_reason = f"原始结构止损 {raw_stop_pct:.2f}% 大于 {max_stop_pct:.1f}% ，下调到 {clipped_stop_pct:.1f}% 。"
    else:
        clip_reason = None
    return {
        "raw_structure_stop_pct": raw_stop_pct,
        "structure_stop_pct": clipped_stop_pct,
        "structure_stop_price": current_price * (1.0 + clipped_stop_pct / 100.0),
        "stop_tradable": True,
        "stop_clip_reason": clip_reason,
    }


def build_hold_split_state(
    *,
    current_price,
    front_high_price,
    rank_change_30m,
    overlap_score_delta_30m,
    darkhorse_score_delta_30m=None,
    require_no_breakout=False,
    no_breakout=True,
):
    hold_blockers = []

    rank_rebound = rank_change_30m is not None and rank_change_30m > 0
    overlap_rebound = overlap_score_delta_30m is not None and overlap_score_delta_30m > 0
    darkhorse_rebound = darkhorse_score_delta_30m is not None and darkhorse_score_delta_30m > 0
    front_high_price = safe_float(front_high_price)
    front_high_retest = (
        current_price not in (None, 0)
        and front_high_price not in (None, 0)
        and current_price >= front_high_price
    )
    breakout_resumed = require_no_breakout and not no_breakout

    if rank_rebound:
        hold_blockers.append("30m 排名重新抬升，走势重新增强")
    if overlap_rebound:
        hold_blockers.append("30m overlap 共振重新上升")
    if darkhorse_rebound:
        hold_blockers.append("30m darkhorse 强度重新上升")
    if breakout_resumed:
        hold_blockers.append("1h 再次出现突破结构")
    if front_high_retest:
        hold_blockers.append("价格已回到结构前高附近")

    if front_high_retest:
        hold_exit_code = "front_high_retest"
    elif breakout_resumed:
        hold_exit_code = "breakout_resume"
    elif rank_rebound or overlap_rebound or darkhorse_rebound:
        hold_exit_code = "strength_resume"
    else:
        hold_exit_code = None

    return {
        "holdable": not hold_blockers,
        "hold_blockers": hold_blockers,
        "hold_exit_code": hold_exit_code,
        "rank_rebound": rank_rebound,
        "overlap_rebound": overlap_rebound,
        "darkhorse_rebound": darkhorse_rebound,
        "front_high_retest": front_high_retest,
        "breakout_resumed": breakout_resumed,
    }


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


def compute_position_in_recent_range(candles, entry_dt, hours, entry_price):
    if entry_price in (None, 0):
        return None
    cutoff = entry_dt - timedelta(hours=hours)
    window = [candle for candle in candles if cutoff < candle["close_dt"] <= entry_dt]
    if not window:
        return None
    window_high = max(candle["high"] for candle in window)
    window_low = min(candle["low"] for candle in window)
    if window_high <= window_low:
        return None
    return (entry_price - window_low) / (window_high - window_low)


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
    pos_12h_range = compute_position_in_recent_range(candles, entry_dt, 12, entry_price)
    pos_24h_range = compute_position_in_recent_range(candles, entry_dt, 24, entry_price)
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
        "structure_pos_12h_range": pos_12h_range,
        "structure_pos_24h_range": pos_24h_range,
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
    c_floor_stop = build_effective_short_stop(
        current_price,
        structure_stop_price,
        structure_stop_pct,
        stop_floor_pct=CONTROL_STOP_FLOOR_PCT,
        stop_window_min_pct=CONTROL_STOP_WINDOW_MIN_PCT,
        stop_window_max_pct=CONTROL_STOP_WINDOW_MAX_PCT,
        target_r_multiple=wide_target_r_multiple,
    )
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
    trend_1d = str(enriched.get("trend_1d") or "")
    trend_4h = str(enriched.get("trend_4h") or "")
    trend_1h = str(enriched.get("trend_1h") or "")
    funding_rate_mean_24h = safe_float(enriched.get("funding_rate_mean_24h"))
    oi_change_1h_pct = safe_float(enriched.get("oi_change_1h_pct"))
    price_change_4h_window_pct = safe_float(enriched.get("price_change_4h_window_pct"))
    recent_overlap_candidate_2h = bool(enriched.get("recent_overlap_candidate_2h"))
    oi_pocket_stop = build_clipped_short_stop(
        current_price,
        structure_stop_pct,
        min_stop_pct=OI_POCKET_STOP_MIN_PCT,
        max_stop_pct=OI_POCKET_STOP_MAX_PCT,
    )
    oi_pocket_base = (
        trend_1d in {"Up", "StrongUp"}
        and trend_4h in {"Up", "StrongUp"}
        and trend_1h in {"Range", "Down", "StrongDown"}
        and no_breakout
    )
    oi_pocket_triggered = (
        oi_pocket_base
        and turnover_ratio_24h is not None
        and turnover_ratio_24h >= OI_POCKET_TURNOVER_MIN
        and oi_change_1h_pct is not None
        and oi_change_1h_pct >= OI_POCKET_OI_CHANGE_1H_MIN
        and funding_rate_mean_24h is not None
        and funding_rate_mean_24h >= OI_POCKET_FUNDING_MEAN_24H_MIN
        and price_change_4h_window_pct is not None
        and price_change_4h_window_pct >= OI_POCKET_PRICE_CHANGE_4H_MIN
        and not recent_overlap_candidate_2h
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

    b_hold_state = build_hold_split_state(
        current_price=current_price,
        front_high_price=base_signal.get("front_high_price"),
        rank_change_30m=rank_change_30m,
        overlap_score_delta_30m=overlap_score_delta_30m,
        require_no_breakout=True,
        no_breakout=no_breakout,
    )
    layers["B_no_breakout_fade_wide_hold"] = {
        "strategy_id": "B_no_breakout_fade_wide_hold",
        "strategy_code": "B++",
        "strategy_label": shadow_layer_label("B_no_breakout_fade_wide_hold"),
        "signal_name": SHADOW_STRATEGY_LAYERS["B_no_breakout_fade_wide_hold"]["signal_name"],
        "description": SHADOW_STRATEGY_LAYERS["B_no_breakout_fade_wide_hold"]["description"],
        "row": enriched,
        "tier": "shadow",
        "quality_score": count_true(overlap, generic_weakening, no_breakout, wide_stop_tradable),
        "triggered": b_triggered,
        "openable": b_triggered and wide_stop_tradable,
        "holdable": b_hold_state["holdable"],
        "use_holdable_exit": True,
        "hold_blockers": list(b_hold_state["hold_blockers"]),
        "hold_exit_code": b_hold_state["hold_exit_code"],
        "anchor_active": overlap,
        "weakness_active": generic_weakening,
        "breakout_guard": no_breakout,
        "requires_no_breakout_exit": False,
        "signal_summary": "B+ 入场，B++ 持有：仍按 NoBreakout + 30m 转弱开仓，但持仓只在重新走强、突破恢复或回到前高时退出。",
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

    c_hold_state = build_hold_split_state(
        current_price=current_price,
        front_high_price=base_signal.get("front_high_price"),
        rank_change_30m=rank_change_30m,
        overlap_score_delta_30m=overlap_score_delta_30m,
    )
    layers["C_overheat_fade_wide_hold"] = {
        "strategy_id": "C_overheat_fade_wide_hold",
        "strategy_code": "C++",
        "strategy_label": shadow_layer_label("C_overheat_fade_wide_hold"),
        "signal_name": SHADOW_STRATEGY_LAYERS["C_overheat_fade_wide_hold"]["signal_name"],
        "description": SHADOW_STRATEGY_LAYERS["C_overheat_fade_wide_hold"]["description"],
        "row": enriched,
        "tier": "shadow",
        "quality_score": count_true(overlap, generic_weakening, c_overheat, wide_stop_tradable),
        "triggered": c_triggered,
        "openable": c_triggered and wide_stop_tradable,
        "holdable": c_hold_state["holdable"],
        "use_holdable_exit": True,
        "hold_blockers": list(c_hold_state["hold_blockers"]),
        "hold_exit_code": c_hold_state["hold_exit_code"],
        "anchor_active": overlap,
        "weakness_active": generic_weakening,
        "breakout_guard": no_breakout,
        "requires_no_breakout_exit": False,
        "signal_summary": "C+ 入场，C++ 持有：仍按过热 + 30m 转弱开仓，但持仓不再要求继续过热或继续 overlap，只在重新走强或回到前高时退出。",
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
    c_floor_blockers = []
    if not overlap:
        c_floor_blockers.append("当前不在交叉候选池内")
    if overlap and not generic_weakening:
        c_floor_blockers.append("30m 排名或交叉分尚未转弱")
    if overlap and generic_weakening and not c_overheat:
        c_floor_blockers.append("24h 涨幅或换手尚未进入过热区")
    if c_triggered and c_floor_stop["raw_structure_stop_pct"] is None:
        c_floor_blockers.append("缺少结构止损上下文")
    if c_triggered and c_floor_stop["raw_structure_stop_pct"] is not None and not c_floor_stop["stop_tradable"]:
        c_floor_blockers.append(
            stop_window_blocker(
                c_floor_stop["structure_stop_pct"],
                CONTROL_STOP_WINDOW_MIN_PCT,
                CONTROL_STOP_WINDOW_MAX_PCT,
            )
        )
    if c_floor_stop["stop_floor_applied"] and c_floor_stop["stop_floor_reason"]:
        c_floor_blockers = [
            item for item in c_floor_blockers if not str(item).startswith("结构止损")
        ]
    layers["C_overheat_fade_wide_hold_floor_10_5"] = {
        "strategy_id": "C_overheat_fade_wide_hold_floor_10_5",
        "strategy_code": "C++++",
        "strategy_label": shadow_layer_label("C_overheat_fade_wide_hold_floor_10_5"),
        "signal_name": SHADOW_STRATEGY_LAYERS["C_overheat_fade_wide_hold_floor_10_5"]["signal_name"],
        "description": SHADOW_STRATEGY_LAYERS["C_overheat_fade_wide_hold_floor_10_5"]["description"],
        "row": enriched,
        "tier": "shadow",
        "quality_score": count_true(overlap, generic_weakening, c_overheat, c_floor_stop["stop_tradable"]),
        "triggered": c_triggered,
        "openable": c_triggered and c_floor_stop["stop_tradable"],
        "holdable": c_hold_state["holdable"],
        "use_holdable_exit": True,
        "hold_blockers": list(c_hold_state["hold_blockers"]),
        "hold_exit_code": c_hold_state["hold_exit_code"],
        "anchor_active": overlap,
        "weakness_active": generic_weakening,
        "breakout_guard": no_breakout,
        "requires_no_breakout_exit": False,
        "signal_summary": "C++++ 入场与 C++ 持有一致；当结构止损小于 3% 时，改用 10.5% 固定止损地板，仍按 1.5R 计算目标位。",
        "blockers": c_floor_blockers,
        "current_price": current_price,
        "structure_stop_price": c_floor_stop["structure_stop_price"],
        "structure_stop_pct": c_floor_stop["structure_stop_pct"],
        "structure_target_price": c_floor_stop["structure_target_price"],
        "structure_target_price_r1": standard_target_price,
        "target_r_multiple": c_floor_stop["target_r_multiple"],
        "front_high_price": base_signal.get("front_high_price"),
        "atr_1h_pct": base_signal.get("atr_1h_pct"),
        "stop_tradable": c_floor_stop["stop_tradable"],
        "stop_window_min_pct": CONTROL_STOP_WINDOW_MIN_PCT,
        "stop_window_max_pct": CONTROL_STOP_WINDOW_MAX_PCT,
        "stop_floor_pct": c_floor_stop["stop_floor_pct"],
        "stop_floor_applied": c_floor_stop["stop_floor_applied"],
        "stop_floor_reason": c_floor_stop["stop_floor_reason"],
        "raw_structure_stop_price": c_floor_stop["raw_structure_stop_price"],
        "raw_structure_stop_pct": c_floor_stop["raw_structure_stop_pct"],
        "overlap_score": safe_float(enriched.get("overlap_score")),
    }
    layers["C_overheat_fade_wide_hold_floor_10_5_paper_copy"] = {
        **layers["C_overheat_fade_wide_hold_floor_10_5"],
        "strategy_id": "C_overheat_fade_wide_hold_floor_10_5_paper_copy",
        "strategy_code": "P0",
        "strategy_label": shadow_layer_label("C_overheat_fade_wide_hold_floor_10_5_paper_copy"),
        "signal_name": SHADOW_STRATEGY_LAYERS["C_overheat_fade_wide_hold_floor_10_5_paper_copy"]["signal_name"],
        "description": SHADOW_STRATEGY_LAYERS["C_overheat_fade_wide_hold_floor_10_5_paper_copy"]["description"],
        "signal_summary": "P0 / C++++ Baseline：完全复制当前 C++++，作为从同一时间起跑的全新基线对照组。",
    }
    layers["C_overheat_fade_wide_hold_floor_10_5_pause_3l_60m"] = {
        **layers["C_overheat_fade_wide_hold_floor_10_5"],
        "strategy_id": "C_overheat_fade_wide_hold_floor_10_5_pause_3l_60m",
        "strategy_code": "C++++p",
        "strategy_label": shadow_layer_label("C_overheat_fade_wide_hold_floor_10_5_pause_3l_60m"),
        "signal_name": SHADOW_STRATEGY_LAYERS["C_overheat_fade_wide_hold_floor_10_5_pause_3l_60m"]["signal_name"],
        "description": SHADOW_STRATEGY_LAYERS["C_overheat_fade_wide_hold_floor_10_5_pause_3l_60m"]["description"],
        "signal_summary": "C++++ + 3 连亏暂停 60m：入场、止损地板和持有逻辑与当前 C++++ 一致，但虚拟盘内若连续 3 笔亏损则暂停 60 分钟。",
    }
    layers["C_overheat_fade_wide_hold_floor_10_5_pause_plus_pos12"] = {
        **layers["C_overheat_fade_wide_hold_floor_10_5_pause_3l_60m"],
        "strategy_id": "C_overheat_fade_wide_hold_floor_10_5_pause_plus_pos12",
        "strategy_code": "C++++p12",
        "strategy_label": shadow_layer_label("C_overheat_fade_wide_hold_floor_10_5_pause_plus_pos12"),
        "signal_name": SHADOW_STRATEGY_LAYERS["C_overheat_fade_wide_hold_floor_10_5_pause_plus_pos12"]["signal_name"],
        "description": SHADOW_STRATEGY_LAYERS["C_overheat_fade_wide_hold_floor_10_5_pause_plus_pos12"]["description"],
        "signal_summary": "C++++ + 3 连亏暂停 60m + Pos12：在当前 C++++ 基础上，叠加全局暂停和 12h 区间下半区禁开过滤。",
    }
    layers["C_overheat_fade_wide_hold_floor_10_5_frozen_front_high"] = {
        **layers["C_overheat_fade_wide_hold_floor_10_5"],
        "strategy_id": "C_overheat_fade_wide_hold_floor_10_5_frozen_front_high",
        "strategy_code": "C++++fh",
        "strategy_label": shadow_layer_label("C_overheat_fade_wide_hold_floor_10_5_frozen_front_high"),
        "signal_name": SHADOW_STRATEGY_LAYERS["C_overheat_fade_wide_hold_floor_10_5_frozen_front_high"]["signal_name"],
        "description": SHADOW_STRATEGY_LAYERS["C_overheat_fade_wide_hold_floor_10_5_frozen_front_high"]["description"],
        "signal_summary": "C++++ 冻结前高：入场与 strength_resume 和当前 C++++ 一致，只把前高退出改成入场冻结前高。",
    }

    oi_pocket_blockers = []
    if not oi_pocket_base:
        if trend_1d not in {"Up", "StrongUp"}:
            oi_pocket_blockers.append("trend_1d 未处于 Up/StrongUp")
        if trend_4h not in {"Up", "StrongUp"}:
            oi_pocket_blockers.append("trend_4h 未处于 Up/StrongUp")
        if trend_1h not in {"Range", "Down", "StrongDown"}:
            oi_pocket_blockers.append("trend_1h 尚未转弱")
        if not no_breakout:
            oi_pocket_blockers.append("1h 仍有突破结构")
    if oi_pocket_base and (turnover_ratio_24h is None or turnover_ratio_24h < OI_POCKET_TURNOVER_MIN):
        oi_pocket_blockers.append(f"turnover_ratio_24h 未达到 {OI_POCKET_TURNOVER_MIN:g}")
    if oi_pocket_base and (oi_change_1h_pct is None or oi_change_1h_pct < OI_POCKET_OI_CHANGE_1H_MIN):
        oi_pocket_blockers.append(f"oi_change_1h_pct 未达到 {OI_POCKET_OI_CHANGE_1H_MIN:g}%")
    if oi_pocket_base and (funding_rate_mean_24h is None or funding_rate_mean_24h < OI_POCKET_FUNDING_MEAN_24H_MIN):
        oi_pocket_blockers.append("funding_rate_mean_24h 仍为负")
    if oi_pocket_base and (
        price_change_4h_window_pct is None or price_change_4h_window_pct < OI_POCKET_PRICE_CHANGE_4H_MIN
    ):
        oi_pocket_blockers.append(f"price_change_4h_window_pct 未达到 {OI_POCKET_PRICE_CHANGE_4H_MIN:g}%")
    if oi_pocket_base and recent_overlap_candidate_2h:
        oi_pocket_blockers.append("近 2h 仍处于 recent overlap 窗口")
    if oi_pocket_triggered and not oi_pocket_stop["stop_tradable"]:
        oi_pocket_blockers.append("缺少结构止损上下文")
    if oi_pocket_stop["stop_clip_reason"]:
        oi_pocket_blockers.append(oi_pocket_stop["stop_clip_reason"])

    oi_pocket_quality = count_true(
        oi_pocket_base,
        turnover_ratio_24h is not None and turnover_ratio_24h >= OI_POCKET_TURNOVER_MIN,
        oi_change_1h_pct is not None and oi_change_1h_pct >= OI_POCKET_OI_CHANGE_1H_MIN,
        funding_rate_mean_24h is not None and funding_rate_mean_24h >= OI_POCKET_FUNDING_MEAN_24H_MIN,
        price_change_4h_window_pct is not None and price_change_4h_window_pct >= OI_POCKET_PRICE_CHANGE_4H_MIN,
        not recent_overlap_candidate_2h,
        oi_pocket_stop["stop_tradable"],
    )

    layers["OI_pocket_v1_hold_12h"] = {
        "strategy_id": "OI_pocket_v1_hold_12h",
        "strategy_code": "OIh12",
        "strategy_label": shadow_layer_label("OI_pocket_v1_hold_12h"),
        "signal_name": SHADOW_STRATEGY_LAYERS["OI_pocket_v1_hold_12h"]["signal_name"],
        "description": SHADOW_STRATEGY_LAYERS["OI_pocket_v1_hold_12h"]["description"],
        "row": enriched,
        "tier": "shadow",
        "quality_score": oi_pocket_quality,
        "triggered": oi_pocket_triggered,
        "openable": oi_pocket_triggered and oi_pocket_stop["stop_tradable"],
        "anchor_active": True,
        "weakness_active": True,
        "breakout_guard": no_breakout,
        "requires_no_breakout_exit": False,
        "signal_summary": "OI pocket V1：1d/4h 保持强势，1h 已转弱且无 breakout，同时 turnover、OI 1h 与 funding 满足拥挤顶部过滤，模拟盘持有到 12h。",
        "blockers": oi_pocket_blockers,
        "current_price": current_price,
        "structure_stop_price": oi_pocket_stop["structure_stop_price"],
        "structure_stop_pct": oi_pocket_stop["structure_stop_pct"],
        "structure_target_price": None,
        "structure_target_price_r1": None,
        "target_r_multiple": None,
        "front_high_price": base_signal.get("front_high_price"),
        "atr_1h_pct": base_signal.get("atr_1h_pct"),
        "stop_tradable": oi_pocket_stop["stop_tradable"],
        "stop_window_min_pct": OI_POCKET_STOP_MIN_PCT,
        "stop_window_max_pct": OI_POCKET_STOP_MAX_PCT,
        "raw_structure_stop_pct": oi_pocket_stop["raw_structure_stop_pct"],
        "overlap_score": safe_float(enriched.get("overlap_score")),
    }
    layers["OI_pocket_v1_soft_4h_then_12h"] = {
        **layers["OI_pocket_v1_hold_12h"],
        "strategy_id": "OI_pocket_v1_soft_4h_then_12h",
        "strategy_code": "OIs4h",
        "strategy_label": shadow_layer_label("OI_pocket_v1_soft_4h_then_12h"),
        "signal_name": SHADOW_STRATEGY_LAYERS["OI_pocket_v1_soft_4h_then_12h"]["signal_name"],
        "description": SHADOW_STRATEGY_LAYERS["OI_pocket_v1_soft_4h_then_12h"]["description"],
        "signal_summary": "OI pocket V1：entry pocket 不变，但第 4 小时若利润不足 1% 就提前离场，否则继续持有到 12h。",
    }

    d_hold_state = build_hold_split_state(
        current_price=current_price,
        front_high_price=base_signal.get("front_high_price"),
        rank_change_30m=rank_change_30m,
        overlap_score_delta_30m=overlap_score_delta_30m,
        darkhorse_score_delta_30m=darkhorse_score_delta_30m,
    )
    layers["D_extreme_overheat_fade_wide_hold"] = {
        "strategy_id": "D_extreme_overheat_fade_wide_hold",
        "strategy_code": "D++",
        "strategy_label": shadow_layer_label("D_extreme_overheat_fade_wide_hold"),
        "signal_name": SHADOW_STRATEGY_LAYERS["D_extreme_overheat_fade_wide_hold"]["signal_name"],
        "description": SHADOW_STRATEGY_LAYERS["D_extreme_overheat_fade_wide_hold"]["description"],
        "row": enriched,
        "tier": "shadow",
        "quality_score": count_true(overlap, extreme_weakening, d_overheat, wide_stop_tradable),
        "triggered": d_triggered,
        "openable": d_triggered and wide_stop_tradable,
        "holdable": d_hold_state["holdable"],
        "use_holdable_exit": True,
        "hold_blockers": list(d_hold_state["hold_blockers"]),
        "hold_exit_code": d_hold_state["hold_exit_code"],
        "anchor_active": overlap,
        "weakness_active": extreme_weakening,
        "breakout_guard": no_breakout,
        "requires_no_breakout_exit": False,
        "signal_summary": "D+ 入场，D++ 持有：仍按极端过热 + 极端转弱开仓，但持仓只在重新增强或回到前高时退出。",
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
