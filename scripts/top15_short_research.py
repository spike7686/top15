#!/usr/bin/env python3
import argparse
import csv
import json
import statistics
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import OrderedDict, defaultdict
from datetime import datetime, timedelta
from pathlib import Path

from top15_short_strategy import SHADOW_STRATEGY_LAYERS

WORKDIR = Path(__file__).resolve().parents[1]
DATA_DIR = WORKDIR / "data" / "top15_tracker"
ANALYSIS_DIR = WORKDIR / "analysis"
KLINES_DIR = DATA_DIR / "klines"
RESEARCH_CACHE_DIR = DATA_DIR / "research_cache" / "perp_v3"
SHORT_STRATEGY_CONFIG_PATH = WORKDIR / "config" / "short_strategy.post_confirm_weak_turn_v1.json"
DEFAULT_HISTORY_JSONL = DATA_DIR / "history.jsonl"
DEFAULT_OUTPUT_JSON = ANALYSIS_DIR / "top15_short_research_v3.json"
DEFAULT_OUTPUT_MD = ANALYSIS_DIR / "top15_short_research_v3.md"
FILTER_RULE = "24h_volume_usd_gt_15m_excluding_stablecoins_binance_spot_only"
HORIZONS = [1, 4, 12, 24]
HEADERS = {"user-agent": "OpenClaw/1.0", "accept": "application/json"}
BINANCE_SPOT_KLINES_URL = "https://api.binance.com/api/v3/klines"
BINANCE_FUTURES_KLINES_URL = "https://fapi.binance.com/fapi/v1/klines"
BINANCE_FUNDING_URL = "https://fapi.binance.com/fapi/v1/fundingRate"
BINANCE_OI_HIST_URL = "https://fapi.binance.com/futures/data/openInterestHist"
BINANCE_TAKER_LONG_SHORT_URL = "https://fapi.binance.com/futures/data/takerlongshortRatio"
BINANCE_TOP_LONG_SHORT_ACCOUNT_URL = "https://fapi.binance.com/futures/data/topLongShortAccountRatio"
BINANCE_TOP_LONG_SHORT_POSITION_URL = "https://fapi.binance.com/futures/data/topLongShortPositionRatio"
BINANCE_BASIS_URL = "https://fapi.binance.com/futures/data/basis"
FIVE_MIN_MS = 5 * 60 * 1000
ONE_HOUR_MS = 60 * 60 * 1000
ONE_DAY_MS = 24 * 60 * 60 * 1000
PERP_ENRICH_WARMUP_H = 30
PERP_VOLUME_LOOKBACK_MS = ONE_DAY_MS
PERP_FILTER_MIN_COUNT = 3
PERP_CONFIRM_FILTER_MIN_COUNT = 2
FUNDING_EXTREME_NEGATIVE_THRESHOLD = -0.002
PREMIUM_DEEP_DISCOUNT_THRESHOLD = -0.4
PERP_VOLUME_DOMINANT_THRESHOLD = 1.0
TAKER_BUY_DOMINANT_THRESHOLD = 1.0
TAKER_BUY_STRONG_THRESHOLD = 1.2
TOP_TRADER_LONG_SHORT_CROWDED_THRESHOLD = 1.2
TOP_TRADER_ACCOUNT_CONFIRM_THRESHOLD = 1.18
TOP_TRADER_POSITION_CONFIRM_THRESHOLD = 1.24
BASIS_DEEP_DISCOUNT_THRESHOLD = PREMIUM_DEEP_DISCOUNT_THRESHOLD / 100.0
BASIS_EXTREME_DISCOUNT_THRESHOLD = -0.006
PRICE_NONPOSITIVE_THRESHOLD = 0.0


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
STRUCTURE_CONFIG = SHORT_STRATEGY_CONFIG.get("structure") or {}
RISK_CONFIG = SHORT_STRATEGY_CONFIG.get("risk") or {}
RESEARCH_CONFIG = SHORT_STRATEGY_CONFIG.get("research") or {}

FOCUS_SIGNAL_NAME = RESEARCH_CONFIG.get("focus_signal_name") or STRATEGY_CONFIG.get("signal_name") or "post_confirm_weak_turn"
FOCUS_SIGNAL_DEFINITION = (
    RESEARCH_CONFIG.get("focus_signal_definition")
    or "Current overlap_candidate=true or recent 2h overlap_candidate=true, then trend_1h turns to Range/Down/StrongDown and overlap_score_delta_30m <= 0."
)
FOCUS_RECENT_OVERLAP_WINDOW_H = float(ANCHOR_CONFIG.get("recent_overlap_window_hours") or 2.0)
FOCUS_MIN_PERSISTENCE_H = float(ANCHOR_CONFIG.get("min_top15_persistence_hours") or 1.0)
FOCUS_WEAK_TREND_VALUES = set(WEAKENING_CONFIG.get("trend_1h_values") or ["Range", "Down", "StrongDown"])
FOCUS_OVERLAP_DELTA_MAX = float(WEAKENING_CONFIG.get("overlap_score_delta_30m_max") or 0.0)
FOCUS_BREAKOUT_REQUIRED = WEAKENING_CONFIG.get("breakout_1h_required") or "NoBreakout"
FOCUS_CHANGE_MIN_PCT = float(WEAKENING_CONFIG.get("change_24h_min_pct") or 3.0)
FOCUS_CHANGE_MAX_PCT = float(WEAKENING_CONFIG.get("change_24h_max_pct") or 8.0)

STRUCTURE_FRONT_HIGH_LOOKBACK_H = float(STRUCTURE_CONFIG.get("front_high_lookback_h") or 2)
STRUCTURE_VOL_LOOKBACK_H = float(STRUCTURE_CONFIG.get("vol_lookback_h") or 1)
STRUCTURE_ATR_PERIOD = int(STRUCTURE_CONFIG.get("atr_period") or 14)
STRUCTURE_STOP_BUFFER_MULT = float(STRUCTURE_CONFIG.get("stop_buffer_mult") or 0.35)
STRUCTURE_MIN_BUFFER_PCT = float(STRUCTURE_CONFIG.get("min_buffer_pct") or 0.15)
STRUCTURE_STOP_MIN_PCT = float(STRUCTURE_CONFIG.get("stop_window_min_pct") or 0.8)
STRUCTURE_STOP_MAX_PCT = float(STRUCTURE_CONFIG.get("stop_window_max_pct") or 4.5)
EXECUTION_PROFILES = RESEARCH_CONFIG.get("execution_profiles") or []

SIGNAL_DEFINITIONS = OrderedDict(
    [
        (
            "first_overlap",
            "First row where overlap_candidate flips from false to true.",
        ),
        (
            "weak_core",
            "Inside an overlap episode, rank_change_30m <= 0 and overlap_score_delta_30m <= 0.",
        ),
        (
            "weak_all_scores",
            "Inside an overlap episode, rank_change_30m <= 0 and all 30m score deltas <= 0.",
        ),
        (
            FOCUS_SIGNAL_NAME,
            FOCUS_SIGNAL_DEFINITION,
        ),
        (
            "overheat_fade",
            "Inside an overlap episode, 24h change >= 15, turnover >= 0.5, rank_change_30m <= 0, overlap_score_delta_30m <= 0.",
        ),
        (
            "extreme_overheat_fade",
            "Inside an overlap episode, 24h change >= 20, turnover >= 0.8, darkhorse_score_delta_30m <= 0, overlap_score_delta_30m <= 0.",
        ),
        (
            "no_breakout_fade",
            f"Inside an overlap episode, breakout_1h == {FOCUS_BREAKOUT_REQUIRED}, rank_change_30m <= 0, overlap_score_delta_30m <= 0.",
        ),
    ]
)

FOCUS_FILTERS = OrderedDict(
    [
        ("all", lambda event: True),
        ("no_breakout_1h", lambda event: event.get("breakout_1h") == FOCUS_BREAKOUT_REQUIRED),
        ("pos_ge_8", lambda event: (event.get("top15_position") or 0) >= 8),
        ("turnover_ge_0_4", lambda event: (event.get("turnover_ratio_24h") or 0) >= 0.4),
        (
            "chg_3_8",
            lambda event: event.get("change_24h_pct") is not None and FOCUS_CHANGE_MIN_PCT <= event["change_24h_pct"] <= FOCUS_CHANGE_MAX_PCT,
        ),
        ("activity_low", lambda event: event.get("activity_bucket") == "Low"),
    ]
)

FOCUS_FILTER_COMBOS = [
    ("all",),
    ("no_breakout_1h",),
    ("pos_ge_8",),
    ("turnover_ge_0_4",),
    ("chg_3_8",),
    ("activity_low",),
    ("no_breakout_1h", "chg_3_8"),
    ("no_breakout_1h", "pos_ge_8"),
    ("no_breakout_1h", "turnover_ge_0_4"),
    ("pos_ge_8", "chg_3_8"),
    ("no_breakout_1h", "pos_ge_8", "chg_3_8"),
    ("no_breakout_1h", "pos_ge_8", "turnover_ge_0_4", "chg_3_8"),
]

if not EXECUTION_PROFILES:
    EXECUTION_PROFILES = [
        {
            "name": "baseline_tp1_5_sl1_h12",
            "signal": FOCUS_SIGNAL_NAME,
            "filters": [],
            "mode": "fixed_pct",
            "tp_pct": 1.5,
            "sl_pct": 1.0,
            "max_h": 12.0,
        },
        {
            "name": "baseline_tp2_sl1_h12",
            "signal": FOCUS_SIGNAL_NAME,
            "filters": [],
            "mode": "fixed_pct",
            "tp_pct": 2.0,
            "sl_pct": 1.0,
            "max_h": 12.0,
        },
        {
            "name": "selective_tp1_5_sl1_h12",
            "signal": FOCUS_SIGNAL_NAME,
            "filters": ["no_breakout_1h", "chg_3_8"],
            "mode": "fixed_pct",
            "tp_pct": 1.5,
            "sl_pct": 1.0,
            "max_h": 12.0,
        },
        {
            "name": "selective_tp2_sl1_h12",
            "signal": FOCUS_SIGNAL_NAME,
            "filters": ["no_breakout_1h", "chg_3_8"],
            "mode": "fixed_pct",
            "tp_pct": 2.0,
            "sl_pct": 1.0,
            "max_h": 12.0,
        },
        {
            "name": "selective_structure_r1_h12",
            "signal": FOCUS_SIGNAL_NAME,
            "filters": ["no_breakout_1h", "chg_3_8"],
            "mode": "structure_r",
            "tp_r": 1.0,
            "max_h": 12.0,
            "risk_budget_pct": 5.0,
            "min_stop_pct": 0.8,
            "max_stop_pct": 4.5,
        },
        {
            "name": "selective_structure_r2_h12",
            "signal": FOCUS_SIGNAL_NAME,
            "filters": ["no_breakout_1h", "chg_3_8"],
            "mode": "structure_r",
            "tp_r": 2.0,
            "max_h": 12.0,
            "risk_budget_pct": 5.0,
            "min_stop_pct": 0.8,
            "max_stop_pct": 4.5,
        },
    ]

DEFAULT_FOCUS_FILTERS = list(RESEARCH_CONFIG.get("entry_filters") or ["no_breakout_1h", "chg_3_8"])
REFERENCE_FIXED_PROFILE_NAME = next(
    (profile["name"] for profile in EXECUTION_PROFILES if profile.get("mode") == "fixed_pct" and list(profile.get("filters") or []) == DEFAULT_FOCUS_FILTERS and profile.get("tp_pct") == 2.0),
    "selective_tp2_sl1_h12",
)
REFERENCE_STRUCTURE_PROFILE_NAME = next(
    (profile["name"] for profile in EXECUTION_PROFILES if profile.get("mode") == "structure_r" and list(profile.get("filters") or []) == DEFAULT_FOCUS_FILTERS and profile.get("tp_r") == 1.0),
    "selective_structure_r1_h12",
)

PERP_FILTERS = OrderedDict(
    [
        ("all", lambda sample: True),
        ("oi_1h_expanding", lambda sample: sample.get("oi_change_1h_pct") is not None and sample["oi_change_1h_pct"] > 0),
        ("oi_1h_nonexpanding", lambda sample: sample.get("oi_change_1h_pct") is not None and sample["oi_change_1h_pct"] <= 0),
        ("oi_15m_expanding", lambda sample: sample.get("oi_change_15m_pct") is not None and sample["oi_change_15m_pct"] > 0),
        ("oi_15m_nonexpanding", lambda sample: sample.get("oi_change_15m_pct") is not None and sample["oi_change_15m_pct"] <= 0),
        ("oi_4h_nonexpanding", lambda sample: sample.get("oi_change_4h_pct") is not None and sample["oi_change_4h_pct"] <= 0),
        ("funding_nonpositive", lambda sample: sample.get("funding_rate_latest") is not None and sample["funding_rate_latest"] <= 0),
        (
            "funding_extreme_negative",
            lambda sample: sample.get("funding_rate_latest") is not None
            and sample["funding_rate_latest"] <= FUNDING_EXTREME_NEGATIVE_THRESHOLD,
        ),
        (
            "funding_mild_negative",
            lambda sample: sample.get("funding_rate_latest") is not None
            and FUNDING_EXTREME_NEGATIVE_THRESHOLD < sample["funding_rate_latest"] <= 0,
        ),
        (
            "funding_cooling",
            lambda sample: sample.get("funding_rate_latest") is not None
            and sample.get("funding_rate_mean_24h") is not None
            and sample["funding_rate_latest"] <= sample["funding_rate_mean_24h"],
        ),
        (
            "funding_rebound_vs_mean",
            lambda sample: sample.get("funding_rate_latest_delta_vs_mean_24h") is not None
            and sample["funding_rate_latest_delta_vs_mean_24h"] >= 0,
        ),
        ("premium_nonpositive", lambda sample: sample.get("perp_premium_pct_vs_spot") is not None and sample["perp_premium_pct_vs_spot"] <= 0),
        (
            "premium_deep_discount",
            lambda sample: sample.get("perp_premium_pct_vs_spot") is not None
            and sample["perp_premium_pct_vs_spot"] <= PREMIUM_DEEP_DISCOUNT_THRESHOLD,
        ),
        (
            "basis_extreme_discount",
            lambda sample: sample.get("basis_rate_latest") is not None
            and sample["basis_rate_latest"] <= BASIS_EXTREME_DISCOUNT_THRESHOLD,
        ),
        (
            "basis_discount_deepening",
            lambda sample: sample.get("basis_rate_delta_vs_mean_1h") is not None
            and sample["basis_rate_delta_vs_mean_1h"] <= 0,
        ),
        (
            "top_position_unwinding_15m",
            lambda sample: sample.get("top_trader_position_lsr_change_15m_pct") is not None
            and sample["top_trader_position_lsr_change_15m_pct"] < 0,
        ),
        (
            "top_position_unwinding_1h",
            lambda sample: sample.get("top_trader_position_lsr_change_1h_pct") is not None
            and sample["top_trader_position_lsr_change_1h_pct"] < 0,
        ),
        (
            "top_account_unwinding_15m",
            lambda sample: sample.get("top_trader_account_lsr_change_15m_pct") is not None
            and sample["top_trader_account_lsr_change_15m_pct"] < 0,
        ),
        (
            "liq_long_flush_15m",
            lambda sample: sample.get("oi_change_15m_pct") is not None
            and sample.get("perp_price_change_15m_pct") is not None
            and sample["oi_change_15m_pct"] < 0
            and sample["perp_price_change_15m_pct"] <= PRICE_NONPOSITIVE_THRESHOLD,
        ),
        (
            "liq_long_flush_5m",
            lambda sample: sample.get("oi_change_5m_pct") is not None
            and sample.get("perp_price_change_5m_pct") is not None
            and sample["oi_change_5m_pct"] < 0
            and sample["perp_price_change_5m_pct"] <= PRICE_NONPOSITIVE_THRESHOLD,
        ),
        (
            "buy_absorption_proxy_5m",
            lambda sample: sample.get("taker_buy_sell_ratio_latest") is not None
            and sample.get("perp_price_change_5m_pct") is not None
            and sample["taker_buy_sell_ratio_latest"] > TAKER_BUY_DOMINANT_THRESHOLD
            and sample["perp_price_change_5m_pct"] <= PRICE_NONPOSITIVE_THRESHOLD,
        ),
        (
            "top_account_confirm_crowded",
            lambda sample: sample.get("top_trader_account_lsr_latest") is not None
            and sample["top_trader_account_lsr_latest"] >= TOP_TRADER_ACCOUNT_CONFIRM_THRESHOLD,
        ),
        (
            "perp_volume_dominant",
            lambda sample: sample.get("perp_to_spot_volume_ratio_24h") is not None
            and sample["perp_to_spot_volume_ratio_24h"] >= PERP_VOLUME_DOMINANT_THRESHOLD,
        ),
        (
            "oi_1h_nonexpanding+premium_nonpositive",
            lambda sample: sample.get("oi_change_1h_pct") is not None
            and sample["oi_change_1h_pct"] <= 0
            and sample.get("perp_premium_pct_vs_spot") is not None
            and sample["perp_premium_pct_vs_spot"] <= 0,
        ),
        (
            "oi_1h_nonexpanding+funding_cooling",
            lambda sample: sample.get("oi_change_1h_pct") is not None
            and sample["oi_change_1h_pct"] <= 0
            and sample.get("funding_rate_latest") is not None
            and sample.get("funding_rate_mean_24h") is not None
            and sample["funding_rate_latest"] <= sample["funding_rate_mean_24h"],
        ),
        (
            "premium_nonpositive+funding_cooling",
            lambda sample: sample.get("perp_premium_pct_vs_spot") is not None
            and sample["perp_premium_pct_vs_spot"] <= 0
            and sample.get("funding_rate_latest") is not None
            and sample.get("funding_rate_mean_24h") is not None
            and sample["funding_rate_latest"] <= sample["funding_rate_mean_24h"],
        ),
        (
            "oi_1h_nonexpanding+perp_volume_dominant",
            lambda sample: sample.get("oi_change_1h_pct") is not None
            and sample["oi_change_1h_pct"] <= 0
            and sample.get("perp_to_spot_volume_ratio_24h") is not None
            and sample["perp_to_spot_volume_ratio_24h"] >= PERP_VOLUME_DOMINANT_THRESHOLD,
        ),
        (
            "oi_1h_expanding+premium_deep_discount",
            lambda sample: sample.get("oi_change_1h_pct") is not None
            and sample["oi_change_1h_pct"] > 0
            and sample.get("perp_premium_pct_vs_spot") is not None
            and sample["perp_premium_pct_vs_spot"] <= PREMIUM_DEEP_DISCOUNT_THRESHOLD,
        ),
        (
            "oi_1h_expanding+funding_mild_negative",
            lambda sample: sample.get("oi_change_1h_pct") is not None
            and sample["oi_change_1h_pct"] > 0
            and sample.get("funding_rate_latest") is not None
            and FUNDING_EXTREME_NEGATIVE_THRESHOLD < sample["funding_rate_latest"] <= 0,
        ),
        (
            "funding_mild_negative+premium_deep_discount",
            lambda sample: sample.get("funding_rate_latest") is not None
            and FUNDING_EXTREME_NEGATIVE_THRESHOLD < sample["funding_rate_latest"] <= 0
            and sample.get("perp_premium_pct_vs_spot") is not None
            and sample["perp_premium_pct_vs_spot"] <= PREMIUM_DEEP_DISCOUNT_THRESHOLD,
        ),
        (
            "oi_1h_expanding+funding_rebound_vs_mean+premium_deep_discount",
            lambda sample: sample.get("oi_change_1h_pct") is not None
            and sample["oi_change_1h_pct"] > 0
            and sample.get("funding_rate_latest_delta_vs_mean_24h") is not None
            and sample["funding_rate_latest_delta_vs_mean_24h"] >= 0
            and sample.get("perp_premium_pct_vs_spot") is not None
            and sample["perp_premium_pct_vs_spot"] <= PREMIUM_DEEP_DISCOUNT_THRESHOLD,
        ),
        (
            "basis_extreme_discount+top_account_confirm_crowded",
            lambda sample: sample.get("basis_rate_latest") is not None
            and sample["basis_rate_latest"] <= BASIS_EXTREME_DISCOUNT_THRESHOLD
            and sample.get("top_trader_account_lsr_latest") is not None
            and sample["top_trader_account_lsr_latest"] >= TOP_TRADER_ACCOUNT_CONFIRM_THRESHOLD,
        ),
        (
            "basis_extreme_discount+oi_1h_expanding",
            lambda sample: sample.get("basis_rate_latest") is not None
            and sample["basis_rate_latest"] <= BASIS_EXTREME_DISCOUNT_THRESHOLD
            and sample.get("oi_change_1h_pct") is not None
            and sample["oi_change_1h_pct"] > 0,
        ),
        (
            "basis_discount_deepening+top_position_unwinding_15m",
            lambda sample: sample.get("basis_rate_delta_vs_mean_1h") is not None
            and sample["basis_rate_delta_vs_mean_1h"] <= 0
            and sample.get("top_trader_position_lsr_change_15m_pct") is not None
            and sample["top_trader_position_lsr_change_15m_pct"] < 0,
        ),
        (
            "basis_extreme_discount+buy_absorption_proxy_5m",
            lambda sample: sample.get("basis_rate_latest") is not None
            and sample["basis_rate_latest"] <= BASIS_EXTREME_DISCOUNT_THRESHOLD
            and sample.get("taker_buy_sell_ratio_latest") is not None
            and sample.get("perp_price_change_5m_pct") is not None
            and sample["taker_buy_sell_ratio_latest"] > TAKER_BUY_DOMINANT_THRESHOLD
            and sample["perp_price_change_5m_pct"] <= PRICE_NONPOSITIVE_THRESHOLD,
        ),
    ]
)

PERP_CONFIRM_FILTERS = OrderedDict(
    [
        ("all", lambda sample: True),
        (
            "taker_buy_dominant",
            lambda sample: sample.get("taker_buy_sell_ratio_latest") is not None
            and sample["taker_buy_sell_ratio_latest"] > TAKER_BUY_DOMINANT_THRESHOLD,
        ),
        (
            "taker_buy_strong",
            lambda sample: sample.get("taker_buy_sell_ratio_latest") is not None
            and sample["taker_buy_sell_ratio_latest"] >= TAKER_BUY_STRONG_THRESHOLD,
        ),
        (
            "taker_buy_accelerating",
            lambda sample: sample.get("taker_buy_sell_ratio_delta_vs_mean_1h") is not None
            and sample["taker_buy_sell_ratio_delta_vs_mean_1h"] > 0,
        ),
        (
            "top_account_long_crowded",
            lambda sample: sample.get("top_trader_account_lsr_latest") is not None
            and sample["top_trader_account_lsr_latest"] >= TOP_TRADER_LONG_SHORT_CROWDED_THRESHOLD,
        ),
        (
            "top_account_confirm_crowded",
            lambda sample: sample.get("top_trader_account_lsr_latest") is not None
            and sample["top_trader_account_lsr_latest"] >= TOP_TRADER_ACCOUNT_CONFIRM_THRESHOLD,
        ),
        (
            "top_account_long_building",
            lambda sample: sample.get("top_trader_account_lsr_delta_vs_mean_1h") is not None
            and sample["top_trader_account_lsr_delta_vs_mean_1h"] > 0,
        ),
        (
            "top_position_long_crowded",
            lambda sample: sample.get("top_trader_position_lsr_latest") is not None
            and sample["top_trader_position_lsr_latest"] >= TOP_TRADER_LONG_SHORT_CROWDED_THRESHOLD,
        ),
        (
            "top_position_confirm_crowded",
            lambda sample: sample.get("top_trader_position_lsr_latest") is not None
            and sample["top_trader_position_lsr_latest"] >= TOP_TRADER_POSITION_CONFIRM_THRESHOLD,
        ),
        (
            "top_position_long_building",
            lambda sample: sample.get("top_trader_position_lsr_delta_vs_mean_1h") is not None
            and sample["top_trader_position_lsr_delta_vs_mean_1h"] > 0,
        ),
        (
            "basis_discount",
            lambda sample: sample.get("basis_rate_latest") is not None
            and sample["basis_rate_latest"] < 0,
        ),
        (
            "basis_deep_discount",
            lambda sample: sample.get("basis_rate_latest") is not None
            and sample["basis_rate_latest"] <= BASIS_DEEP_DISCOUNT_THRESHOLD,
        ),
        (
            "basis_extreme_discount",
            lambda sample: sample.get("basis_rate_latest") is not None
            and sample["basis_rate_latest"] <= BASIS_EXTREME_DISCOUNT_THRESHOLD,
        ),
        (
            "basis_discount_deepening",
            lambda sample: sample.get("basis_rate_delta_vs_mean_1h") is not None
            and sample["basis_rate_delta_vs_mean_1h"] <= 0,
        ),
        (
            "taker_buy_cooling",
            lambda sample: sample.get("taker_buy_sell_ratio_latest") is not None
            and sample["taker_buy_sell_ratio_latest"] < 1.0
            and sample.get("taker_buy_sell_ratio_delta_vs_mean_1h") is not None
            and sample["taker_buy_sell_ratio_delta_vs_mean_1h"] < 0,
        ),
        (
            "top_position_unwinding_15m",
            lambda sample: sample.get("top_trader_position_lsr_change_15m_pct") is not None
            and sample["top_trader_position_lsr_change_15m_pct"] < 0,
        ),
        (
            "top_position_unwinding_1h",
            lambda sample: sample.get("top_trader_position_lsr_change_1h_pct") is not None
            and sample["top_trader_position_lsr_change_1h_pct"] < 0,
        ),
        (
            "liq_long_flush_5m",
            lambda sample: sample.get("oi_change_5m_pct") is not None
            and sample.get("perp_price_change_5m_pct") is not None
            and sample["oi_change_5m_pct"] < 0
            and sample["perp_price_change_5m_pct"] <= PRICE_NONPOSITIVE_THRESHOLD,
        ),
        (
            "liq_long_flush_15m",
            lambda sample: sample.get("oi_change_15m_pct") is not None
            and sample.get("perp_price_change_15m_pct") is not None
            and sample["oi_change_15m_pct"] < 0
            and sample["perp_price_change_15m_pct"] <= PRICE_NONPOSITIVE_THRESHOLD,
        ),
        (
            "buy_absorption_proxy_5m",
            lambda sample: sample.get("taker_buy_sell_ratio_latest") is not None
            and sample.get("perp_price_change_5m_pct") is not None
            and sample["taker_buy_sell_ratio_latest"] > TAKER_BUY_DOMINANT_THRESHOLD
            and sample["perp_price_change_5m_pct"] <= PRICE_NONPOSITIVE_THRESHOLD,
        ),
        (
            "taker_buy_dominant+top_position_long_crowded",
            lambda sample: sample.get("taker_buy_sell_ratio_latest") is not None
            and sample["taker_buy_sell_ratio_latest"] > TAKER_BUY_DOMINANT_THRESHOLD
            and sample.get("top_trader_position_lsr_latest") is not None
            and sample["top_trader_position_lsr_latest"] >= TOP_TRADER_LONG_SHORT_CROWDED_THRESHOLD,
        ),
        (
            "taker_buy_dominant+top_account_long_crowded",
            lambda sample: sample.get("taker_buy_sell_ratio_latest") is not None
            and sample["taker_buy_sell_ratio_latest"] > TAKER_BUY_DOMINANT_THRESHOLD
            and sample.get("top_trader_account_lsr_latest") is not None
            and sample["top_trader_account_lsr_latest"] >= TOP_TRADER_LONG_SHORT_CROWDED_THRESHOLD,
        ),
        (
            "top_position_long_crowded+basis_deep_discount",
            lambda sample: sample.get("top_trader_position_lsr_latest") is not None
            and sample["top_trader_position_lsr_latest"] >= TOP_TRADER_LONG_SHORT_CROWDED_THRESHOLD
            and sample.get("basis_rate_latest") is not None
            and sample["basis_rate_latest"] <= BASIS_DEEP_DISCOUNT_THRESHOLD,
        ),
        (
            "taker_buy_dominant+top_position_long_crowded+basis_deep_discount",
            lambda sample: sample.get("taker_buy_sell_ratio_latest") is not None
            and sample["taker_buy_sell_ratio_latest"] > TAKER_BUY_DOMINANT_THRESHOLD
            and sample.get("top_trader_position_lsr_latest") is not None
            and sample["top_trader_position_lsr_latest"] >= TOP_TRADER_LONG_SHORT_CROWDED_THRESHOLD
            and sample.get("basis_rate_latest") is not None
            and sample["basis_rate_latest"] <= BASIS_DEEP_DISCOUNT_THRESHOLD,
        ),
        (
            "taker_buy_cooling+top_account_confirm_crowded+basis_extreme_discount",
            lambda sample: sample.get("taker_buy_sell_ratio_latest") is not None
            and sample["taker_buy_sell_ratio_latest"] < 1.0
            and sample.get("taker_buy_sell_ratio_delta_vs_mean_1h") is not None
            and sample["taker_buy_sell_ratio_delta_vs_mean_1h"] < 0
            and sample.get("top_trader_account_lsr_latest") is not None
            and sample["top_trader_account_lsr_latest"] >= TOP_TRADER_ACCOUNT_CONFIRM_THRESHOLD
            and sample.get("basis_rate_latest") is not None
            and sample["basis_rate_latest"] <= BASIS_EXTREME_DISCOUNT_THRESHOLD,
        ),
        (
            "basis_extreme_discount+top_position_unwinding_15m",
            lambda sample: sample.get("basis_rate_latest") is not None
            and sample["basis_rate_latest"] <= BASIS_EXTREME_DISCOUNT_THRESHOLD
            and sample.get("top_trader_position_lsr_change_15m_pct") is not None
            and sample["top_trader_position_lsr_change_15m_pct"] < 0,
        ),
        (
            "buy_absorption_proxy_5m+top_account_confirm_crowded+basis_extreme_discount",
            lambda sample: sample.get("taker_buy_sell_ratio_latest") is not None
            and sample["taker_buy_sell_ratio_latest"] > TAKER_BUY_DOMINANT_THRESHOLD
            and sample.get("perp_price_change_5m_pct") is not None
            and sample["perp_price_change_5m_pct"] <= PRICE_NONPOSITIVE_THRESHOLD
            and sample.get("top_trader_account_lsr_latest") is not None
            and sample["top_trader_account_lsr_latest"] >= TOP_TRADER_ACCOUNT_CONFIRM_THRESHOLD
            and sample.get("basis_rate_latest") is not None
            and sample["basis_rate_latest"] <= BASIS_EXTREME_DISCOUNT_THRESHOLD,
        ),
    ]
)

RESEARCH_CACHE_DIR.mkdir(parents=True, exist_ok=True)


def safe_float(value):
    try:
        if value in (None, ""):
            return None
        return float(value)
    except Exception:
        return None


def safe_int(value):
    try:
        if value in (None, ""):
            return None
        return int(value)
    except Exception:
        return None


def safe_bool(value):
    return str(value).lower() in {"true", "1"}


def mean_or_none(values):
    return sum(values) / len(values) if values else None


def median_or_none(values):
    return statistics.median(values) if values else None


def round_or_none(value, digits=4):
    return round(value, digits) if value is not None else None


def fetch_json(url, timeout=30, retries=3, retry_sleep_sec=1.5):
    last_exc = None
    for attempt in range(retries):
        try:
            req = urllib.request.Request(url, headers=HEADERS)
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return json.load(resp)
        except urllib.error.HTTPError as exc:
            last_exc = exc
            if exc.code not in {418, 429, 500, 502, 503, 504} or attempt >= retries - 1:
                raise
        except urllib.error.URLError as exc:
            last_exc = exc
            if attempt >= retries - 1:
                raise
        time.sleep(retry_sleep_sec * (attempt + 1))
    if last_exc is not None:
        raise last_exc
    raise RuntimeError(f"fetch_json failed without an exception for url={url}")


def paginate_json_list(url_base, params, time_field, next_step_ms, limit=1000, sleep_sec=0.08):
    start_ms = params.get("startTime")
    end_ms = params.get("endTime")
    rows = []
    current = start_ms
    while current is not None and (end_ms is None or current <= end_ms):
        page_params = dict(params)
        page_params["startTime"] = current
        page_params["limit"] = limit
        query = urllib.parse.urlencode(page_params)
        payload = fetch_json(f"{url_base}?{query}", timeout=30)
        if not payload:
            break
        rows.extend(payload)
        if len(payload) < limit:
            break
        last_time = safe_int(payload[-1][time_field]) if isinstance(payload[-1], dict) else safe_int(payload[-1][0])
        if last_time is None:
            break
        next_current = last_time + next_step_ms
        if next_current <= current:
            break
        current = next_current
        if sleep_sec > 0:
            time.sleep(sleep_sec)
    return rows


def load_symbol_1h_klines(symbol, cache):
    symbol = (symbol or "").upper()
    if symbol in cache:
        return cache[symbol]

    path = KLINES_DIR / symbol / "1h" / "candles.csv"
    rows = []
    if path.exists():
        with path.open("r", encoding="utf-8", newline="") as handle:
            reader = csv.DictReader(handle)
            for row in reader:
                try:
                    rows.append(
                        {
                            "open_dt": datetime.fromisoformat(row["open_time_utc"]),
                            "close_dt": datetime.fromisoformat(row["close_time_utc"]),
                            "high": safe_float(row.get("high_price")),
                            "low": safe_float(row.get("low_price")),
                            "close": safe_float(row.get("close_price")),
                        }
                    )
                except Exception:
                    continue
    rows.sort(key=lambda item: item["open_dt"])
    cache[symbol] = rows
    return rows


def compute_atr_1h_pct(symbol, entry_dt, entry_price, kline_cache):
    if entry_price in (None, 0):
        return None, None

    candles = load_symbol_1h_klines(symbol, kline_cache)
    closed = [
        candle
        for candle in candles
        if candle["close_dt"] <= entry_dt
        and candle["high"] is not None
        and candle["low"] is not None
        and candle["close"] is not None
    ]
    if len(closed) < STRUCTURE_ATR_PERIOD + 1:
        return None, None

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
        return None, None

    atr_abs = sum(recent_trs) / len(recent_trs)
    return atr_abs / entry_price * 100, "kline_1h_atr14"


def recent_prices(rows, entry_dt, lookback_hours):
    cutoff = entry_dt - timedelta(hours=lookback_hours)
    prices = []
    for row in rows:
        dt = row.get("_dt")
        if dt is None or dt < cutoff or dt >= entry_dt:
            continue
        price = safe_float(row.get("price_usd"))
        if price is not None:
            prices.append(price)
    return prices


def compute_structure_stop_context(symbol, entry_dt, entry_price, past_rows, kline_cache):
    recent_high_prices = recent_prices(past_rows, entry_dt, STRUCTURE_FRONT_HIGH_LOOKBACK_H)
    if recent_high_prices:
        front_high_price = max(recent_high_prices)
    else:
        front_high_price = entry_price

    atr_1h_pct, atr_source = compute_atr_1h_pct(symbol, entry_dt, entry_price, kline_cache)
    recent_vol_prices = recent_prices(past_rows, entry_dt, STRUCTURE_VOL_LOOKBACK_H)
    recent_vol_prices.append(entry_price)
    recent_vol_prices = [price for price in recent_vol_prices if price is not None]
    snapshot_range_1h_pct = None
    if len(recent_vol_prices) >= 2 and entry_price not in (None, 0):
        snapshot_range_1h_pct = (max(recent_vol_prices) - min(recent_vol_prices)) / entry_price * 100

    vol_base_pct = atr_1h_pct if atr_1h_pct is not None else snapshot_range_1h_pct
    vol_source = atr_source or ("snapshot_1h_range_proxy" if snapshot_range_1h_pct is not None else "min_buffer_only")
    stop_anchor_price = max(front_high_price, entry_price)
    stop_buffer_pct = max(STRUCTURE_MIN_BUFFER_PCT, (vol_base_pct or 0) * STRUCTURE_STOP_BUFFER_MULT)
    structure_stop_price = stop_anchor_price * (1 + stop_buffer_pct / 100)
    structure_stop_pct = (structure_stop_price / entry_price - 1) * 100 if entry_price not in (None, 0) else None

    return {
        "front_high_price": front_high_price,
        "stop_anchor_price": stop_anchor_price,
        "atr_1h_pct": atr_1h_pct,
        "snapshot_range_1h_pct": snapshot_range_1h_pct,
        "vol_base_pct": vol_base_pct,
        "vol_source": vol_source,
        "stop_buffer_pct": stop_buffer_pct,
        "structure_stop_price": structure_stop_price,
        "structure_stop_pct": structure_stop_pct,
    }


def load_rows_by_symbol(history_jsonl_path: Path):
    rows_by_symbol = defaultdict(list)
    total_lines = 0
    valid_rows = 0
    unique_snapshots = set()
    min_dt = None
    max_dt = None

    with history_jsonl_path.open("r", encoding="utf-8") as handle:
        for raw_line in handle:
            total_lines += 1
            line = raw_line.strip()
            if not line:
                continue
            row = json.loads(line)
            if row.get("filter_rule") != FILTER_RULE:
                continue
            dt = datetime.fromisoformat(row["captured_at_utc"])
            row["_dt"] = dt
            rows_by_symbol[row["symbol"]].append(row)
            valid_rows += 1
            unique_snapshots.add(row.get("snapshot_id"))
            min_dt = dt if min_dt is None or dt < min_dt else min_dt
            max_dt = dt if max_dt is None or dt > max_dt else max_dt

    for rows in rows_by_symbol.values():
        rows.sort(key=lambda item: item["_dt"])

    return rows_by_symbol, {
        "total_lines": total_lines,
        "valid_rows": valid_rows,
        "unique_symbols": len(rows_by_symbol),
        "unique_snapshots": len(unique_snapshots),
        "time_start_utc": min_dt.isoformat() if min_dt else None,
        "time_end_utc": max_dt.isoformat() if max_dt else None,
    }


def make_event(signal_name, row, past_rows, future_rows, kline_cache):
    entry_price = safe_float(row.get("price_usd"))
    if entry_price in (None, 0):
        return None
    structure_ctx = compute_structure_stop_context(row.get("symbol"), row["_dt"], entry_price, past_rows, kline_cache)

    event = {
        "signal": signal_name,
        "symbol": row.get("symbol"),
        "binance_pair": row.get("binance_pair"),
        "entry_dt": row["_dt"],
        "entry_dt_utc": row["_dt"].isoformat(),
        "entry_price": entry_price,
        "top15_position": safe_float(row.get("top15_position")),
        "change_24h_pct": safe_float(row.get("change_24h_pct")),
        "turnover_ratio_24h": safe_float(row.get("turnover_ratio_24h")),
        "binance_quote_volume_usd": safe_float(row.get("binance_quote_volume_usd")),
        "binance_trade_count_24h": safe_int(row.get("binance_trade_count_24h")),
        "darkhorse_score": safe_float(row.get("darkhorse_score")),
        "persistence_score": safe_float(row.get("persistence_score")),
        "overlap_score": safe_float(row.get("overlap_score")),
        "rank_change_30m": safe_float(row.get("rank_change_30m")),
        "darkhorse_score_delta_30m": safe_float(row.get("darkhorse_score_delta_30m")),
        "persistence_score_delta_30m": safe_float(row.get("persistence_score_delta_30m")),
        "overlap_score_delta_30m": safe_float(row.get("overlap_score_delta_30m")),
        "trend_1h": row.get("trend_1h") or "",
        "trend_4h": row.get("trend_4h") or "",
        "breakout_1h": row.get("breakout_1h") or "",
        "breakout_4h": row.get("breakout_4h") or "",
        "continuation_risk": row.get("continuation_risk") or "",
        "activity_bucket": row.get("activity_bucket") or "",
        "path_class_v2": row.get("path_class_v2") or "",
        "front_high_price": structure_ctx["front_high_price"],
        "stop_anchor_price": structure_ctx["stop_anchor_price"],
        "atr_1h_pct": structure_ctx["atr_1h_pct"],
        "snapshot_range_1h_pct": structure_ctx["snapshot_range_1h_pct"],
        "vol_base_pct": structure_ctx["vol_base_pct"],
        "vol_source": structure_ctx["vol_source"],
        "stop_buffer_pct": structure_ctx["stop_buffer_pct"],
        "structure_stop_price": structure_ctx["structure_stop_price"],
        "structure_stop_pct": structure_ctx["structure_stop_pct"],
        "future_rows": future_rows,
    }

    for horizon_h in HORIZONS:
        prices = []
        for future_row in future_rows:
            diff_h = (future_row["_dt"] - row["_dt"]).total_seconds() / 3600
            if diff_h <= 0:
                continue
            if diff_h <= horizon_h:
                future_price = safe_float(future_row.get("price_usd"))
                if future_price is not None:
                    prices.append(future_price)
            else:
                break

        if not prices:
            event[f"short_pnl_{horizon_h}h_pct"] = None
            event[f"fav_excursion_{horizon_h}h_pct"] = None
            event[f"adv_excursion_{horizon_h}h_pct"] = None
            event[f"obs_{horizon_h}h"] = 0
            continue

        end_price = prices[-1]
        min_price = min(prices)
        max_price = max(prices)
        event[f"short_pnl_{horizon_h}h_pct"] = -(end_price / entry_price - 1) * 100
        event[f"fav_excursion_{horizon_h}h_pct"] = max(0.0, -(min_price / entry_price - 1) * 100)
        event[f"adv_excursion_{horizon_h}h_pct"] = max(0.0, (max_price / entry_price - 1) * 100)
        event[f"obs_{horizon_h}h"] = len(prices)

    return event


def build_signal_events(rows_by_symbol):
    signal_events = defaultdict(list)
    kline_cache = {}

    for symbol, rows in rows_by_symbol.items():
        overlap_episode = False
        taken_signals = set()
        focus_signal_taken = False
        last_overlap_dt = None

        for idx, row in enumerate(rows):
            oc = safe_bool(row.get("overlap_candidate"))
            prev_row = rows[idx - 1] if idx > 0 else None
            prev_oc = safe_bool(prev_row.get("overlap_candidate")) if prev_row else False
            if oc:
                last_overlap_dt = row["_dt"]
            recent_overlap = bool(
                last_overlap_dt is not None
                and (row["_dt"] - last_overlap_dt).total_seconds() / 3600 <= FOCUS_RECENT_OVERLAP_WINDOW_H
            )
            anchor_active = oc or recent_overlap

            if oc and not prev_oc:
                overlap_episode = True
                taken_signals = set()
                event = make_event("first_overlap", row, rows[:idx], rows[idx + 1 :], kline_cache)
                if event:
                    signal_events["first_overlap"].append(event)
            elif not oc:
                overlap_episode = False
                taken_signals = set()

            rank_change_30m = safe_float(row.get("rank_change_30m"))
            darkhorse_score_delta_30m = safe_float(row.get("darkhorse_score_delta_30m"))
            persistence_score_delta_30m = safe_float(row.get("persistence_score_delta_30m"))
            overlap_score_delta_30m = safe_float(row.get("overlap_score_delta_30m"))
            change_24h_pct = safe_float(row.get("change_24h_pct"))
            turnover_ratio_24h = safe_float(row.get("turnover_ratio_24h"))
            trend_1h = row.get("trend_1h") or ""
            breakout_1h = row.get("breakout_1h") or ""

            if anchor_active:
                focus_ready = trend_1h in FOCUS_WEAK_TREND_VALUES and (
                    overlap_score_delta_30m is not None and overlap_score_delta_30m <= FOCUS_OVERLAP_DELTA_MAX
                )
                if focus_ready and not focus_signal_taken:
                    event = make_event(FOCUS_SIGNAL_NAME, row, rows[:idx], rows[idx + 1 :], kline_cache)
                    if event:
                        signal_events[FOCUS_SIGNAL_NAME].append(event)
                        focus_signal_taken = True
            else:
                focus_signal_taken = False

            if not overlap_episode or not oc or not prev_oc:
                continue

            candidates = []
            if rank_change_30m is not None and overlap_score_delta_30m is not None and rank_change_30m <= 0 and overlap_score_delta_30m <= 0:
                candidates.append("weak_core")
            if (
                rank_change_30m is not None
                and overlap_score_delta_30m is not None
                and darkhorse_score_delta_30m is not None
                and persistence_score_delta_30m is not None
                and rank_change_30m <= 0
                and overlap_score_delta_30m <= 0
                and darkhorse_score_delta_30m <= 0
                and persistence_score_delta_30m <= 0
            ):
                candidates.append("weak_all_scores")
            if (
                change_24h_pct is not None
                and turnover_ratio_24h is not None
                and rank_change_30m is not None
                and overlap_score_delta_30m is not None
                and change_24h_pct >= 15
                and turnover_ratio_24h >= 0.5
                and rank_change_30m <= 0
                and overlap_score_delta_30m <= 0
            ):
                candidates.append("overheat_fade")
            if (
                change_24h_pct is not None
                and turnover_ratio_24h is not None
                and darkhorse_score_delta_30m is not None
                and overlap_score_delta_30m is not None
                and change_24h_pct >= 20
                and turnover_ratio_24h >= 0.8
                and darkhorse_score_delta_30m <= 0
                and overlap_score_delta_30m <= 0
            ):
                candidates.append("extreme_overheat_fade")
            if (
                breakout_1h == FOCUS_BREAKOUT_REQUIRED
                and rank_change_30m is not None
                and overlap_score_delta_30m is not None
                and rank_change_30m <= 0
                and overlap_score_delta_30m <= 0
            ):
                candidates.append("no_breakout_fade")

            for signal_name in candidates:
                if signal_name in taken_signals:
                    continue
                event = make_event(signal_name, row, rows[:idx], rows[idx + 1 :], kline_cache)
                if event:
                    signal_events[signal_name].append(event)
                    taken_signals.add(signal_name)

    return signal_events


def summarize_events(events):
    summary = {"count": len(events)}

    for horizon_h in HORIZONS:
        short_pnls = [event[f"short_pnl_{horizon_h}h_pct"] for event in events if event[f"short_pnl_{horizon_h}h_pct"] is not None]
        favs = [event[f"fav_excursion_{horizon_h}h_pct"] for event in events if event[f"fav_excursion_{horizon_h}h_pct"] is not None]
        advs = [event[f"adv_excursion_{horizon_h}h_pct"] for event in events if event[f"adv_excursion_{horizon_h}h_pct"] is not None]
        if not short_pnls:
            continue

        gross_win = sum(value for value in short_pnls if value > 0)
        gross_loss = -sum(value for value in short_pnls if value < 0)
        summary[f"{horizon_h}h"] = {
            "n": len(short_pnls),
            "short_win_rate": round_or_none(sum(1 for value in short_pnls if value > 0) / len(short_pnls)),
            "short_win_rate_gt_2pct": round_or_none(sum(1 for value in short_pnls if value > 2) / len(short_pnls)),
            "mean_short_pnl_pct": round_or_none(mean_or_none(short_pnls)),
            "median_short_pnl_pct": round_or_none(median_or_none(short_pnls)),
            "mean_fav_excursion_pct": round_or_none(mean_or_none(favs)),
            "median_fav_excursion_pct": round_or_none(median_or_none(favs)),
            "mean_adv_excursion_pct": round_or_none(mean_or_none(advs)),
            "median_adv_excursion_pct": round_or_none(median_or_none(advs)),
            "profit_factor": round_or_none(gross_win / gross_loss) if gross_loss > 0 else None,
        }

    return summary


def apply_filters(events, filter_names):
    subset = list(events)
    for filter_name in filter_names:
        predicate = FOCUS_FILTERS[filter_name]
        subset = [event for event in subset if predicate(event)]
    return subset


def build_filter_study(events, min_count=8):
    out = OrderedDict()
    for combo in FOCUS_FILTER_COMBOS:
        subset = apply_filters(events, combo if combo != ("all",) else [])
        if len(subset) < min_count:
            continue
        out["+".join(combo)] = {
            "filters": list(combo),
            "summary": summarize_events(subset),
        }
    return out


def simulate_fixed_short_trade(event, tp_pct, sl_pct, max_h):
    entry_price = event["entry_price"]
    take_profit_price = entry_price * (1 - tp_pct / 100)
    stop_loss_price = entry_price * (1 + sl_pct / 100)
    last_price = entry_price
    last_hours = 0.0

    for future_row in event["future_rows"]:
        diff_h = (future_row["_dt"] - event["entry_dt"]).total_seconds() / 3600
        if diff_h <= 0:
            continue
        if diff_h > max_h:
            break
        price = safe_float(future_row.get("price_usd"))
        if price is None:
            continue
        last_price = price
        last_hours = diff_h
        if price <= take_profit_price:
            return {
                "pnl_pct": tp_pct,
                "pnl_r": tp_pct / sl_pct if sl_pct else None,
                "equity_pnl_pct": tp_pct,
                "reason": "tp",
                "hours": diff_h,
                "stop_pct": sl_pct,
                "position_notional_pct": None,
            }
        if price >= stop_loss_price:
            return {
                "pnl_pct": -sl_pct,
                "pnl_r": -1.0,
                "equity_pnl_pct": -sl_pct,
                "reason": "sl",
                "hours": diff_h,
                "stop_pct": sl_pct,
                "position_notional_pct": None,
            }

    timeout_pnl = -(last_price / entry_price - 1) * 100
    return {
        "pnl_pct": timeout_pnl,
        "pnl_r": timeout_pnl / sl_pct if sl_pct else None,
        "equity_pnl_pct": timeout_pnl,
        "reason": "timeout",
        "hours": last_hours,
        "stop_pct": sl_pct,
        "position_notional_pct": None,
    }


def simulate_structure_short_trade(event, tp_r, max_h, risk_budget_pct, min_stop_pct, max_stop_pct):
    entry_price = event["entry_price"]
    stop_price = safe_float(event.get("structure_stop_price"))
    stop_pct = safe_float(event.get("structure_stop_pct"))
    if stop_price in (None, 0) or stop_pct is None:
        return None
    if stop_pct < min_stop_pct or stop_pct > max_stop_pct:
        return None

    tp_move_pct = stop_pct * tp_r
    take_profit_price = entry_price * (1 - tp_move_pct / 100)
    last_price = entry_price
    last_hours = 0.0

    for future_row in event["future_rows"]:
        diff_h = (future_row["_dt"] - event["entry_dt"]).total_seconds() / 3600
        if diff_h <= 0:
            continue
        if diff_h > max_h:
            break
        price = safe_float(future_row.get("price_usd"))
        if price is None:
            continue
        last_price = price
        last_hours = diff_h
        if price <= take_profit_price:
            return {
                "pnl_pct": tp_move_pct,
                "pnl_r": tp_r,
                "equity_pnl_pct": risk_budget_pct * tp_r,
                "reason": "tp",
                "hours": diff_h,
                "stop_pct": stop_pct,
                "position_notional_pct": risk_budget_pct / stop_pct * 100 if stop_pct else None,
            }
        if price >= stop_price:
            return {
                "pnl_pct": -stop_pct,
                "pnl_r": -1.0,
                "equity_pnl_pct": -risk_budget_pct,
                "reason": "sl",
                "hours": diff_h,
                "stop_pct": stop_pct,
                "position_notional_pct": risk_budget_pct / stop_pct * 100 if stop_pct else None,
            }

    timeout_pnl_pct = -(last_price / entry_price - 1) * 100
    timeout_r = timeout_pnl_pct / stop_pct if stop_pct else None
    return {
        "pnl_pct": timeout_pnl_pct,
        "pnl_r": timeout_r,
        "equity_pnl_pct": risk_budget_pct * timeout_r if timeout_r is not None else None,
        "reason": "timeout",
        "hours": last_hours,
        "stop_pct": stop_pct,
        "position_notional_pct": risk_budget_pct / stop_pct * 100 if stop_pct else None,
    }


def build_execution_study(signal_events):
    study = OrderedDict()
    for profile in EXECUTION_PROFILES:
        events = apply_filters(signal_events[profile["signal"]], profile["filters"])
        mode = profile.get("mode") or "fixed_pct"
        outcomes = []
        source_mix = defaultdict(int)
        skipped_no_structure = 0
        for event in events:
            if mode == "fixed_pct":
                outcome = simulate_fixed_short_trade(event, profile["tp_pct"], profile["sl_pct"], profile["max_h"])
            else:
                outcome = simulate_structure_short_trade(
                    event,
                    profile["tp_r"],
                    profile["max_h"],
                    profile["risk_budget_pct"],
                    profile["min_stop_pct"],
                    profile["max_stop_pct"],
                )
                if outcome is not None:
                    source_mix[event.get("vol_source") or "unknown"] += 1
            if outcome is None:
                skipped_no_structure += 1
                continue
            outcomes.append(outcome)

        if mode == "fixed_pct":
            pnls = [outcome["pnl_pct"] for outcome in outcomes]
        else:
            pnls = [outcome["equity_pnl_pct"] for outcome in outcomes if outcome["equity_pnl_pct"] is not None]
        gross_win = sum(value for value in pnls if value > 0)
        gross_loss = -sum(value for value in pnls if value < 0)
        payload = {
            "signal": profile["signal"],
            "filters": list(profile["filters"]),
            "mode": mode,
            "max_h": profile["max_h"],
            "n": len(outcomes),
            "raw_signal_count": len(events),
            "skipped_count": skipped_no_structure,
            "win_rate": round_or_none(sum(1 for value in pnls if value > 0) / len(pnls)) if pnls else None,
            "mean_pnl_pct": round_or_none(mean_or_none(pnls)),
            "median_pnl_pct": round_or_none(median_or_none(pnls)),
            "profit_factor": round_or_none(gross_win / gross_loss) if gross_loss > 0 else None,
        }
        payload["tp_rate"] = round_or_none(sum(1 for outcome in outcomes if outcome["reason"] == "tp") / len(outcomes)) if outcomes else None
        payload["sl_rate"] = round_or_none(sum(1 for outcome in outcomes if outcome["reason"] == "sl") / len(outcomes)) if outcomes else None
        payload["timeout_rate"] = round_or_none(sum(1 for outcome in outcomes if outcome["reason"] == "timeout") / len(outcomes)) if outcomes else None
        payload["median_hours_in_trade"] = round_or_none(median_or_none([outcome["hours"] for outcome in outcomes]))

        if mode == "fixed_pct":
            payload["tp_pct"] = profile["tp_pct"]
            payload["sl_pct"] = profile["sl_pct"]
            payload["mean_pnl_r"] = round_or_none(mean_or_none([outcome["pnl_r"] for outcome in outcomes if outcome["pnl_r"] is not None]))
            payload["median_pnl_r"] = round_or_none(median_or_none([outcome["pnl_r"] for outcome in outcomes if outcome["pnl_r"] is not None]))
        else:
            payload["tp_r"] = profile["tp_r"]
            payload["risk_budget_pct"] = profile["risk_budget_pct"]
            payload["min_stop_pct"] = profile["min_stop_pct"]
            payload["max_stop_pct"] = profile["max_stop_pct"]
            payload["mean_pnl_r"] = round_or_none(mean_or_none([outcome["pnl_r"] for outcome in outcomes if outcome["pnl_r"] is not None]))
            payload["median_pnl_r"] = round_or_none(median_or_none([outcome["pnl_r"] for outcome in outcomes if outcome["pnl_r"] is not None]))
            payload["mean_stop_pct"] = round_or_none(mean_or_none([outcome["stop_pct"] for outcome in outcomes if outcome["stop_pct"] is not None]))
            payload["median_stop_pct"] = round_or_none(median_or_none([outcome["stop_pct"] for outcome in outcomes if outcome["stop_pct"] is not None]))
            payload["mean_position_notional_pct"] = round_or_none(
                mean_or_none([outcome["position_notional_pct"] for outcome in outcomes if outcome["position_notional_pct"] is not None])
            )
            payload["median_position_notional_pct"] = round_or_none(
                median_or_none([outcome["position_notional_pct"] for outcome in outcomes if outcome["position_notional_pct"] is not None])
            )
            payload["vol_source_mix"] = dict(sorted(source_mix.items()))
        study[profile["name"]] = payload
    return study


def build_shadow_layer_profiles():
    structure_tp_r = safe_float(STRUCTURE_CONFIG.get("tp_r"))
    max_hold_hours = safe_float(STRUCTURE_CONFIG.get("max_hold_hours"))
    risk_budget_pct = safe_float(RISK_CONFIG.get("risk_pct"))
    profiles = OrderedDict()
    for strategy_id, layer in SHADOW_STRATEGY_LAYERS.items():
        layer_tp_r = safe_float(layer.get("target_r_multiple"))
        layer_stop_min_pct = safe_float(layer.get("stop_window_min_pct"))
        layer_stop_max_pct = safe_float(layer.get("stop_window_max_pct"))
        profiles[strategy_id] = {
            "strategy_id": strategy_id,
            "code": layer.get("code"),
            "label": layer.get("label"),
            "signal": layer.get("signal_name"),
            "filters": list(layer.get("entry_filters") or []),
            "mode": "structure_r",
            "tp_r": layer_tp_r if layer_tp_r is not None else (structure_tp_r if structure_tp_r is not None else 1.0),
            "max_h": max_hold_hours if max_hold_hours is not None else 12.0,
            "risk_budget_pct": risk_budget_pct if risk_budget_pct is not None else 5.0,
            "min_stop_pct": layer_stop_min_pct if layer_stop_min_pct is not None else STRUCTURE_STOP_MIN_PCT,
            "max_stop_pct": layer_stop_max_pct if layer_stop_max_pct is not None else STRUCTURE_STOP_MAX_PCT,
            "description": layer.get("description"),
        }
    return profiles


def build_trade_equity_curve(samples, starting_equity_usd):
    equity = starting_equity_usd
    peak_equity = starting_equity_usd
    max_drawdown_pct = 0.0
    curve = []

    ordered = sorted(samples, key=lambda sample: ((sample.get("entry_dt") or ""), (sample.get("symbol") or "")))
    for index, sample in enumerate(ordered, start=1):
        trade_pnl_pct = safe_float(sample.get("equity_pnl_pct")) or 0.0
        equity_before = equity
        pnl_usd = equity_before * trade_pnl_pct / 100
        equity = equity_before + pnl_usd
        peak_equity = max(peak_equity, equity)
        drawdown_pct = ((equity / peak_equity) - 1) * 100 if peak_equity else 0.0
        max_drawdown_pct = min(max_drawdown_pct, drawdown_pct)
        curve.append(
            {
                "seq": index,
                "entry_dt": sample.get("entry_dt"),
                "symbol": sample.get("symbol"),
                "reason": sample.get("reason"),
                "equity_before_usd": round_or_none(equity_before, digits=4),
                "equity_after_usd": round_or_none(equity, digits=4),
                "trade_equity_pnl_pct": round_or_none(trade_pnl_pct, digits=4),
                "trade_pnl_usd": round_or_none(pnl_usd, digits=4),
                "drawdown_pct": round_or_none(drawdown_pct, digits=4),
            }
        )

    return {
        "starting_equity_usd": round_or_none(starting_equity_usd, digits=4),
        "ending_equity_usd": round_or_none(equity, digits=4),
        "total_return_pct": round_or_none(((equity / starting_equity_usd) - 1) * 100, digits=4) if starting_equity_usd else None,
        "max_drawdown_pct": round_or_none(max_drawdown_pct, digits=4),
        "curve": curve,
    }


def build_shadow_layer_study(signal_events):
    starting_equity_usd = safe_float(RISK_CONFIG.get("initial_equity_usd")) or 10000.0
    profiles = build_shadow_layer_profiles()
    layers = OrderedDict()

    for strategy_id, profile in profiles.items():
        events = apply_filters(signal_events.get(profile["signal"], []), profile["filters"])
        trades = []
        skipped_no_structure = 0
        source_mix = defaultdict(int)

        for event in events:
            outcome = simulate_structure_short_trade(
                event,
                profile["tp_r"],
                profile["max_h"],
                profile["risk_budget_pct"],
                profile["min_stop_pct"],
                profile["max_stop_pct"],
            )
            if outcome is None:
                skipped_no_structure += 1
                continue
            trade = {key: value for key, value in event.items() if key not in {"future_rows", "entry_dt"}}
            trade["entry_dt"] = event.get("entry_dt_utc")
            trade.update(outcome)
            trade["strategy_id"] = strategy_id
            trade["strategy_code"] = profile["code"]
            trade["strategy_label"] = profile["label"]
            trades.append(trade)
            source_mix[event.get("vol_source") or "unknown"] += 1

        summary = summarize_trade_samples(trades)
        equity_curve = build_trade_equity_curve(trades, starting_equity_usd)
        layers[strategy_id] = {
            "strategy_id": strategy_id,
            "code": profile["code"],
            "label": profile["label"],
            "description": profile["description"],
            "signal": profile["signal"],
            "filters": list(profile["filters"]),
            "tp_r": profile["tp_r"],
            "max_h": profile["max_h"],
            "risk_budget_pct": profile["risk_budget_pct"],
            "min_stop_pct": profile["min_stop_pct"],
            "max_stop_pct": profile["max_stop_pct"],
            "raw_signal_count": len(events),
            "structure_tradable_count": len(trades),
            "skipped_count": skipped_no_structure,
            "summary": summary,
            "equity_curve": equity_curve,
            "vol_source_mix": dict(sorted(source_mix.items())),
            "recent_trades": sorted(trades, key=lambda trade: ((trade.get("entry_dt") or ""), (trade.get("symbol") or "")), reverse=True)[:10],
        }

    comparison = sorted(
        [
            {
                "strategy_id": payload["strategy_id"],
                "code": payload["code"],
                "label": payload["label"],
                "signal": payload["signal"],
                "filters": list(payload["filters"]),
                "raw_signal_count": payload["raw_signal_count"],
                "structure_tradable_count": payload["structure_tradable_count"],
                "win_rate": payload["summary"].get("win_rate"),
                "mean_equity_pnl_pct": payload["summary"].get("mean_equity_pnl_pct"),
                "median_equity_pnl_pct": payload["summary"].get("median_equity_pnl_pct"),
                "mean_pnl_r": payload["summary"].get("mean_pnl_r"),
                "profit_factor": payload["summary"].get("profit_factor"),
                "ending_equity_usd": payload["equity_curve"].get("ending_equity_usd"),
                "total_return_pct": payload["equity_curve"].get("total_return_pct"),
                "max_drawdown_pct": payload["equity_curve"].get("max_drawdown_pct"),
            }
            for payload in layers.values()
        ],
        key=lambda item: (
            -(safe_float(item.get("ending_equity_usd")) or 0),
            -(safe_float(item.get("win_rate")) or 0),
            -(safe_float(item.get("mean_pnl_r")) or 0),
        ),
    )

    return {
        "starting_equity_usd": starting_equity_usd,
        "profiles": profiles,
        "comparison": comparison,
        "layers": layers,
    }


def build_focus_samples(events):
    event_fields = [
        "symbol",
        "entry_dt_utc",
        "top15_position",
        "change_24h_pct",
        "turnover_ratio_24h",
        "darkhorse_score",
        "persistence_score",
        "overlap_score",
        "rank_change_30m",
        "darkhorse_score_delta_30m",
        "persistence_score_delta_30m",
        "overlap_score_delta_30m",
        "trend_1h",
        "trend_4h",
        "breakout_1h",
        "breakout_4h",
        "continuation_risk",
        "activity_bucket",
        "path_class_v2",
        "front_high_price",
        "atr_1h_pct",
        "snapshot_range_1h_pct",
        "vol_base_pct",
        "vol_source",
        "stop_buffer_pct",
        "structure_stop_price",
        "structure_stop_pct",
        "short_pnl_4h_pct",
        "short_pnl_12h_pct",
        "short_pnl_24h_pct",
        "fav_excursion_4h_pct",
        "adv_excursion_4h_pct",
    ]
    ordered = sorted(events, key=lambda event: (event.get("short_pnl_24h_pct") or -999), reverse=True)
    top_samples = [{field: event.get(field) for field in event_fields} for event in ordered[:5]]
    bottom_samples = [{field: event.get(field) for field in event_fields} for event in ordered[-5:]]
    return {"top_5": top_samples, "bottom_5": bottom_samples}


def build_markdown(report):
    meta = report["meta"]
    signals = report["signals"]
    filter_study = report["focus_filter_study"]
    execution = report["execution_study"]
    shadow_layer_study = report["shadow_layer_study"]
    recommendation = report["strategy_candidate"]
    structure_meta = report["structure_meta"]
    perp_v3_study = report["perp_v3_study"]
    perp_structure_summary = report["perp_structure_summary"]
    perp_structure_meta = report["perp_structure_meta"]
    perp_confirm_meta = report["perp_confirm_meta"]
    perp_confirm_summary = report["perp_confirm_summary"]
    perp_confirm_study = report["perp_confirm_study"]

    lines = []
    lines.append("# TOP15 Short Fade Research V3")
    lines.append("")
    lines.append("## 1. Dataset")
    lines.append(f"- Valid rows: {meta['valid_rows']}")
    lines.append(f"- Unique symbols: {meta['unique_symbols']}")
    lines.append(f"- Unique snapshots: {meta['unique_snapshots']}")
    lines.append(f"- Time range: {meta['time_start_utc']} -> {meta['time_end_utc']}")
    lines.append(f"- History source: `{meta['history_source']}`")
    lines.append(f"- Filter rule: `{meta['filter_rule']}`")
    lines.append("")
    lines.append("## 2. Core question")
    lines.append("- Does it make sense to short immediately when a token enters overlap_candidate?")
    lines.append("- Or is it better to wait until overlap stays true but the 1h momentum rolls over?")
    lines.append("")
    lines.append("## 3. Signal Comparison")
    for signal_name, definition in SIGNAL_DEFINITIONS.items():
        signal_summary = signals.get(signal_name) or {}
        count = signal_summary.get("count", 0)
        h4 = signal_summary.get("4h") or {}
        h12 = signal_summary.get("12h") or {}
        h24 = signal_summary.get("24h") or {}
        lines.append(f"### 3.{len(lines)} `{signal_name}`")
        lines.append(f"- Definition: {definition}")
        lines.append(f"- Sample count: {count}")
        if h4:
            lines.append(
                f"- 4h short stats: win_rate={h4.get('short_win_rate')} | mean={h4.get('mean_short_pnl_pct')}% | median={h4.get('median_short_pnl_pct')}% | pf={h4.get('profit_factor')}"
            )
        if h12:
            lines.append(
                f"- 12h short stats: win_rate={h12.get('short_win_rate')} | mean={h12.get('mean_short_pnl_pct')}% | median={h12.get('median_short_pnl_pct')}% | pf={h12.get('profit_factor')}"
            )
        if h24:
            lines.append(
                f"- 24h short stats: win_rate={h24.get('short_win_rate')} | mean={h24.get('mean_short_pnl_pct')}% | median={h24.get('median_short_pnl_pct')}% | pf={h24.get('profit_factor')}"
            )
        lines.append("")

    lines.append(f"## 4. Focus signal: {FOCUS_SIGNAL_NAME}")
    lines.append(f"- Base idea: {FOCUS_SIGNAL_DEFINITION}")
    lines.append("- This is not a fresh breakout short. It is a post-confirmation fade short.")
    lines.append("")
    lines.append(f"## 5. Filter Study On {FOCUS_SIGNAL_NAME}")
    for combo_name, payload in filter_study.items():
        summary = payload["summary"]
        h4 = summary.get("4h") or {}
        h12 = summary.get("12h") or {}
        h24 = summary.get("24h") or {}
        lines.append(f"### `{combo_name}`")
        lines.append(f"- Sample count: {summary.get('count', 0)}")
        if h4:
            lines.append(
                f"- 4h: win_rate={h4.get('short_win_rate')} | mean={h4.get('mean_short_pnl_pct')}% | median={h4.get('median_short_pnl_pct')}% | pf={h4.get('profit_factor')}"
            )
        if h12:
            lines.append(
                f"- 12h: win_rate={h12.get('short_win_rate')} | mean={h12.get('mean_short_pnl_pct')}% | median={h12.get('median_short_pnl_pct')}% | pf={h12.get('profit_factor')}"
            )
        if h24:
            lines.append(
                f"- 24h: win_rate={h24.get('short_win_rate')} | mean={h24.get('mean_short_pnl_pct')}% | median={h24.get('median_short_pnl_pct')}% | pf={h24.get('profit_factor')}"
            )
        lines.append("")

    lines.append("## 6. Execution Study")
    for profile_name, payload in execution.items():
        lines.append(f"### `{profile_name}`")
        lines.append(f"- Signal: `{payload['signal']}`")
        lines.append(f"- Filters: `{'+'.join(payload['filters']) if payload['filters'] else 'none'}`")
        if payload["mode"] == "fixed_pct":
            lines.append(f"- TP / SL / max_h: {payload['tp_pct']}% / {payload['sl_pct']}% / {payload['max_h']}h")
            lines.append(
                f"- Stats: n={payload['n']} | win_rate={payload['win_rate']} | mean_pnl={payload['mean_pnl_pct']}% | median_pnl={payload['median_pnl_pct']}% | pf={payload['profit_factor']}"
            )
        else:
            lines.append(
                f"- Stop / TP / max_h: recent front-high + {STRUCTURE_STOP_BUFFER_MULT}x vol buffer | {payload['tp_r']}R | {payload['max_h']}h"
            )
            lines.append(
                f"- Risk sizing: per-trade risk={payload['risk_budget_pct']}% equity | stop window={payload['min_stop_pct']}%~{payload['max_stop_pct']}%"
            )
            lines.append(
                f"- Stats: n={payload['n']} / raw={payload['raw_signal_count']} | win_rate={payload['win_rate']} | mean_equity_pnl={payload['mean_pnl_pct']}% | mean_R={payload['mean_pnl_r']} | pf={payload['profit_factor']}"
            )
            lines.append(
                f"- Stop profile: mean_stop={payload.get('mean_stop_pct')}% | median_stop={payload.get('median_stop_pct')}% | median_notional={payload.get('median_position_notional_pct')}%"
            )
        lines.append(
            f"- Exit mix: tp_rate={payload['tp_rate']} | sl_rate={payload['sl_rate']} | timeout_rate={payload['timeout_rate']} | median_hours={payload['median_hours_in_trade']}"
        )
        if payload["mode"] == "structure_r":
            lines.append(f"- Vol source mix: `{json.dumps(payload.get('vol_source_mix') or {}, ensure_ascii=False)}`")
        lines.append("")

    lines.append("## 7. Shadow Layer Comparison")
    lines.append(
        f"- Starting equity per layer: {shadow_layer_study['starting_equity_usd']} USD | same structure stop / 1R / 12h template, independent bookkeeping."
    )
    for item in shadow_layer_study["comparison"]:
        lines.append(f"### `{item['strategy_id']}`")
        lines.append(
            f"- Layer: {item['label']} | signal=`{item['signal']}` | filters=`{'+'.join(item['filters']) if item['filters'] else 'none'}`"
        )
        lines.append(
            f"- raw={item['raw_signal_count']} | structure_tradable={item['structure_tradable_count']} | win_rate={item['win_rate']} | mean_equity_pnl={item['mean_equity_pnl_pct']}% | mean_R={item['mean_pnl_r']} | pf={item['profit_factor']}"
        )
        lines.append(
            f"- equity_end={item['ending_equity_usd']} | total_return={item['total_return_pct']}% | max_drawdown={item['max_drawdown_pct']}%"
        )
        lines.append("")

    lines.append("## 8. Structure Stop Context")
    lines.append(
        f"- Front-high lookback: {structure_meta['front_high_lookback_h']}h | volatility lookback: {structure_meta['vol_lookback_h']}h | buffer multiplier: {structure_meta['stop_buffer_mult']}"
    )
    lines.append(
        f"- True ATR coverage: {structure_meta['atr_kline_coverage_count']} / {structure_meta['atr_total_events']} events ({structure_meta['atr_kline_coverage_ratio']})"
    )
    lines.append(
        f"- Historical execution in this run mainly uses: `{json.dumps(structure_meta['vol_source_mix'], ensure_ascii=False)}`"
    )
    lines.append("")

    lines.append("## 9. Perp V3 Study")
    lines.append(f"- Scope: structure-tradable subset only, based on `{FOCUS_SIGNAL_NAME} + {' + '.join(DEFAULT_FOCUS_FILTERS)}` and structure stop `1.0R / 12h`.")
    lines.append(
        f"- Perp coverage: eligible={perp_structure_meta['perp_eligible_count']} / structure={perp_structure_meta['structure_sample_count']} ({perp_structure_meta['perp_eligible_ratio']}) | status_mix=`{json.dumps(perp_structure_meta['status_mix'], ensure_ascii=False)}`"
    )
    lines.append(
        f"- Base structure subset: n={perp_structure_summary['count']} | win_rate={perp_structure_summary['win_rate']} | mean_R={perp_structure_summary['mean_pnl_r']} | pf={perp_structure_summary['profit_factor']}"
    )
    lines.append(
        f"- Thresholds in this run: funding extreme <= {FUNDING_EXTREME_NEGATIVE_THRESHOLD} | deep premium discount <= {PREMIUM_DEEP_DISCOUNT_THRESHOLD}% | basis extreme <= {BASIS_EXTREME_DISCOUNT_THRESHOLD} | top-account confirm >= {TOP_TRADER_ACCOUNT_CONFIRM_THRESHOLD} | perp volume dominant >= {PERP_VOLUME_DOMINANT_THRESHOLD}x spot | OI expanding means change > 0."
    )
    for filter_name, payload in perp_v3_study.items():
        summary = payload["summary"]
        vs_base = payload.get("vs_base") or {}
        lines.append(f"### `{filter_name}`")
        lines.append(
            f"- n={summary['count']} | share={payload.get('sample_share')} | win_rate={summary['win_rate']} | mean_equity_pnl={summary['mean_equity_pnl_pct']}% | mean_R={summary['mean_pnl_r']} | pf={summary['profit_factor']}"
        )
        lines.append(
            f"- Exit mix: tp_rate={summary['tp_rate']} | sl_rate={summary['sl_rate']} | timeout_rate={summary['timeout_rate']}"
        )
        lines.append(
            f"- Vs base: d_win_rate={vs_base.get('win_rate_delta')} | d_mean_equity_pnl={vs_base.get('mean_equity_pnl_pct_delta')}% | d_mean_R={vs_base.get('mean_pnl_r_delta')} | d_sl_rate={vs_base.get('sl_rate_delta')} | d_timeout_rate={vs_base.get('timeout_rate_delta')}"
        )
        lines.append("")

    lines.append("## 10. OI-Expanding Confirm Study")
    lines.append("- Scope: `oi_change_1h_pct > 0` within the structure-tradable subset only.")
    lines.append(
        f"- Confirm coverage: eligible={perp_confirm_meta['confirm_eligible_count']} / oi_1h_expanding={perp_confirm_meta['oi_1h_expanding_count']} ({perp_confirm_meta['confirm_eligible_ratio']}) | status_mix=`{json.dumps(perp_confirm_meta['status_mix'], ensure_ascii=False)}`"
    )
    lines.append(
        f"- Base oi_1h_expanding subset: n={perp_confirm_summary['count']} | win_rate={perp_confirm_summary['win_rate']} | mean_R={perp_confirm_summary['mean_pnl_r']} | pf={perp_confirm_summary['profit_factor']}"
    )
    lines.append(
        f"- Thresholds in this run: taker dominant > {TAKER_BUY_DOMINANT_THRESHOLD} | taker strong >= {TAKER_BUY_STRONG_THRESHOLD} | taker cooling means latest<1 and delta<0 | top-account crowded >= {TOP_TRADER_ACCOUNT_CONFIRM_THRESHOLD} | top-position crowded >= {TOP_TRADER_POSITION_CONFIRM_THRESHOLD} | basis deep discount <= {BASIS_DEEP_DISCOUNT_THRESHOLD} | basis extreme <= {BASIS_EXTREME_DISCOUNT_THRESHOLD} | price nonpositive <= {PRICE_NONPOSITIVE_THRESHOLD}%"
    )
    for filter_name, payload in perp_confirm_study.items():
        summary = payload["summary"]
        vs_base = payload.get("vs_base") or {}
        lines.append(f"### `{filter_name}`")
        lines.append(
            f"- n={summary['count']} | share={payload.get('sample_share')} | win_rate={summary['win_rate']} | mean_equity_pnl={summary['mean_equity_pnl_pct']}% | mean_R={summary['mean_pnl_r']} | pf={summary['profit_factor']}"
        )
        lines.append(
            f"- Exit mix: tp_rate={summary['tp_rate']} | sl_rate={summary['sl_rate']} | timeout_rate={summary['timeout_rate']}"
        )
        lines.append(
            f"- Vs oi_1h_expanding base: d_win_rate={vs_base.get('win_rate_delta')} | d_mean_equity_pnl={vs_base.get('mean_equity_pnl_pct_delta')}% | d_mean_R={vs_base.get('mean_pnl_r_delta')} | d_sl_rate={vs_base.get('sl_rate_delta')} | d_timeout_rate={vs_base.get('timeout_rate_delta')}"
        )
        lines.append("")

    lines.append("## 11. Current Strategy Candidate")
    lines.append(f"- Focus signal: `{recommendation['signal']}`")
    lines.append(f"- Entry filters: `{'+'.join(recommendation['filters'])}`")
    lines.append(
        f"- Human-readable rule: current overlap_candidate=true or recent {FOCUS_RECENT_OVERLAP_WINDOW_H:g}h overlap_candidate=true, trend_1h rolls into {sorted(FOCUS_WEAK_TREND_VALUES)}, overlap_score_delta_30m <= {FOCUS_OVERLAP_DELTA_MAX:g}, breakout_1h is {FOCUS_BREAKOUT_REQUIRED}, and 24h change is between {FOCUS_CHANGE_MIN_PCT:g}% and {FOCUS_CHANGE_MAX_PCT:g}%."
    )
    lines.append(f"- Fixed reference: TP {recommendation['fixed_reference']['tp_pct']}% / SL {recommendation['fixed_reference']['sl_pct']}% / max {recommendation['fixed_reference']['max_h']}h")
    lines.append(
        f"  Stats: win_rate={recommendation['fixed_reference']['win_rate']} | mean_pnl={recommendation['fixed_reference']['mean_pnl_pct']}% | pf={recommendation['fixed_reference']['profit_factor']}"
    )
    lines.append(
        f"- Structure candidate: front-high + {STRUCTURE_STOP_BUFFER_MULT}x vol buffer | TP {recommendation['structure']['tp_r']}R | risk {recommendation['structure']['risk_budget_pct']}% equity | max {recommendation['structure']['max_h']}h"
    )
    lines.append(
        f"  Stats: win_rate={recommendation['structure']['win_rate']} | mean_equity_pnl={recommendation['structure']['mean_pnl_pct']}% | mean_R={recommendation['structure']['mean_pnl_r']} | pf={recommendation['structure']['profit_factor']}"
    )
    lines.append("")

    lines.append("## 12. Caveats")
    lines.append("- The strongest signal is statistically promising but small-sample.")
    lines.append("- The execution study is snapshot-based, not intrabar matching or order-book replay.")
    lines.append("- The shadow-layer equity curves are independent per-layer compounding curves, not a shared-portfolio overlap-aware backtest.")
    lines.append(f"- The structure stop now uses true 1h ATR for the full {FOCUS_SIGNAL_NAME} sample.")
    lines.append("- Perp V3 uses historical Binance OI statistics, funding history, and 5m futures/spot klines reconstructed around the event timestamp.")
    lines.append("- The taker / top-trader / basis confirm layer currently sits on only 3 oi_1h_expanding trades.")
    lines.append("- Binance public docs expose current order-book snapshots but not historical depth replay, so this run uses absorption / flow proxies instead of true historical book imbalance.")
    lines.append("- The V3 factor study is still small-sample and should be treated as directional evidence, not a production-grade proof.")
    lines.append("- This is a research candidate, not a production strategy.")
    lines.append("")

    lines.append("## 13. Next steps")
    lines.append("- Re-run the same study after another 2-4 weeks of data accumulation.")
    lines.append("- Add 5m / 15m execution-level candles for more realistic entry and stop handling.")
    lines.append("- Add live depth snapshots and force-order stream capture so the next version can test true order-book imbalance and liquidation flow, not just proxies.")
    lines.append("- Split by time to build out-of-sample validation.")
    lines.append("")

    return "\n".join(lines).strip() + "\n"


def build_strategy_candidate(execution_study):
    fixed_reference = dict(execution_study[REFERENCE_FIXED_PROFILE_NAME])
    structure = dict(execution_study[REFERENCE_STRUCTURE_PROFILE_NAME])
    return {
        "signal": FOCUS_SIGNAL_NAME,
        "filters": list(DEFAULT_FOCUS_FILTERS),
        "fixed_reference": fixed_reference,
        "structure": structure,
    }


def build_structure_meta(signal_events):
    events = signal_events.get(FOCUS_SIGNAL_NAME) or []
    total = len(events)
    atr_count = sum(1 for event in events if event.get("vol_source") == "kline_1h_atr14")
    source_mix = defaultdict(int)
    for event in events:
        source_mix[event.get("vol_source") or "unknown"] += 1
    return {
        "front_high_lookback_h": STRUCTURE_FRONT_HIGH_LOOKBACK_H,
        "vol_lookback_h": STRUCTURE_VOL_LOOKBACK_H,
        "stop_buffer_mult": STRUCTURE_STOP_BUFFER_MULT,
        "atr_total_events": total,
        "atr_kline_coverage_count": atr_count,
        "atr_kline_coverage_ratio": round_or_none(atr_count / total) if total else None,
        "vol_source_mix": dict(sorted(source_mix.items())),
    }


def cache_file_path(symbol_pair, start_ms, end_ms):
    return RESEARCH_CACHE_DIR / f"{symbol_pair.upper()}__{start_ms}__{end_ms}.json"


def normalize_kline_payload(payload):
    rows = []
    for item in payload:
        rows.append(
            {
                "open_time_ms": int(item[0]),
                "close_time_ms": int(item[6]),
                "close_price": safe_float(item[4]),
                "quote_volume": safe_float(item[7]),
                "trade_count": safe_int(item[8]),
            }
        )
    rows.sort(key=lambda row: row["open_time_ms"])
    return rows


def normalize_oi_hist_payload(payload):
    rows = []
    for item in payload:
        ts = safe_int(item.get("timestamp"))
        if ts is None:
            continue
        rows.append(
            {
                "timestamp_ms": ts,
                "oi_value_usd": safe_float(item.get("sumOpenInterestValue")),
                "oi_contracts": safe_float(item.get("sumOpenInterest")),
            }
        )
    rows.sort(key=lambda row: row["timestamp_ms"])
    return rows


def normalize_funding_payload(payload):
    rows = []
    for item in payload:
        ts = safe_int(item.get("fundingTime"))
        if ts is None:
            continue
        rows.append(
            {
                "funding_time_ms": ts,
                "funding_rate": safe_float(item.get("fundingRate")),
                "mark_price": safe_float(item.get("markPrice")),
            }
        )
    rows.sort(key=lambda row: row["funding_time_ms"])
    return rows


def normalize_taker_long_short_payload(payload):
    rows = []
    for item in payload:
        ts = safe_int(item.get("timestamp"))
        if ts is None:
            continue
        rows.append(
            {
                "timestamp_ms": ts,
                "buy_sell_ratio": safe_float(item.get("buySellRatio")),
                "buy_volume": safe_float(item.get("buyVol")),
                "sell_volume": safe_float(item.get("sellVol")),
            }
        )
    rows.sort(key=lambda row: row["timestamp_ms"])
    return rows


def normalize_long_short_ratio_payload(payload):
    rows = []
    for item in payload:
        ts = safe_int(item.get("timestamp"))
        if ts is None:
            continue
        rows.append(
            {
                "timestamp_ms": ts,
                "long_short_ratio": safe_float(item.get("longShortRatio")),
                "long_pct": safe_float(item.get("longAccount")),
                "short_pct": safe_float(item.get("shortAccount")),
            }
        )
    rows.sort(key=lambda row: row["timestamp_ms"])
    return rows


def normalize_basis_payload(payload):
    rows = []
    for item in payload:
        ts = safe_int(item.get("timestamp"))
        if ts is None:
            continue
        rows.append(
            {
                "timestamp_ms": ts,
                "basis_rate": safe_float(item.get("basisRate")),
                "basis_value": safe_float(item.get("basis")),
                "futures_price": safe_float(item.get("futuresPrice")),
                "index_price": safe_float(item.get("indexPrice")),
                "annualized_basis_rate": safe_float(item.get("annualizedBasisRate")),
            }
        )
    rows.sort(key=lambda row: row["timestamp_ms"])
    return rows


def fetch_research_kline_series(url_base, symbol_pair, interval, start_ms, end_ms):
    payload = paginate_json_list(
        url_base,
        {
            "symbol": symbol_pair.upper(),
            "interval": interval,
            "startTime": start_ms,
            "endTime": end_ms,
        },
        time_field=0,
        next_step_ms=FIVE_MIN_MS,
        limit=1000,
    )
    return normalize_kline_payload(payload)


def fetch_research_oi_hist_series(symbol_pair, start_ms, end_ms):
    payload = paginate_json_list(
        BINANCE_OI_HIST_URL,
        {
            "symbol": symbol_pair.upper(),
            "period": "5m",
            "startTime": start_ms,
            "endTime": end_ms,
        },
        time_field="timestamp",
        next_step_ms=FIVE_MIN_MS,
        limit=500,
    )
    return normalize_oi_hist_payload(payload)


def fetch_research_funding_series(symbol_pair, start_ms, end_ms):
    payload = paginate_json_list(
        BINANCE_FUNDING_URL,
        {
            "symbol": symbol_pair.upper(),
            "startTime": start_ms,
            "endTime": end_ms,
        },
        time_field="fundingTime",
        next_step_ms=1,
        limit=1000,
    )
    return normalize_funding_payload(payload)


def fetch_research_taker_long_short_series(symbol_pair, start_ms, end_ms):
    payload = paginate_json_list(
        BINANCE_TAKER_LONG_SHORT_URL,
        {
            "symbol": symbol_pair.upper(),
            "period": "5m",
            "startTime": start_ms,
            "endTime": end_ms,
        },
        time_field="timestamp",
        next_step_ms=FIVE_MIN_MS,
        limit=500,
    )
    return normalize_taker_long_short_payload(payload)


def fetch_research_top_long_short_account_series(symbol_pair, start_ms, end_ms):
    payload = paginate_json_list(
        BINANCE_TOP_LONG_SHORT_ACCOUNT_URL,
        {
            "symbol": symbol_pair.upper(),
            "period": "5m",
            "startTime": start_ms,
            "endTime": end_ms,
        },
        time_field="timestamp",
        next_step_ms=FIVE_MIN_MS,
        limit=500,
    )
    return normalize_long_short_ratio_payload(payload)


def fetch_research_top_long_short_position_series(symbol_pair, start_ms, end_ms):
    payload = paginate_json_list(
        BINANCE_TOP_LONG_SHORT_POSITION_URL,
        {
            "symbol": symbol_pair.upper(),
            "period": "5m",
            "startTime": start_ms,
            "endTime": end_ms,
        },
        time_field="timestamp",
        next_step_ms=FIVE_MIN_MS,
        limit=500,
    )
    return normalize_long_short_ratio_payload(payload)


def fetch_research_basis_series(symbol_pair, start_ms, end_ms):
    payload = paginate_json_list(
        BINANCE_BASIS_URL,
        {
            "pair": symbol_pair.upper(),
            "contractType": "PERPETUAL",
            "period": "5m",
            "startTime": start_ms,
            "endTime": end_ms,
        },
        time_field="timestamp",
        next_step_ms=FIVE_MIN_MS,
        limit=500,
    )
    return normalize_basis_payload(payload)


def fetch_optional_series(fetcher, symbol_pair, start_ms, end_ms):
    try:
        return fetcher(symbol_pair, start_ms, end_ms), None
    except Exception as exc:
        return [], repr(exc)


def hydrate_perp_context_payload(payload, symbol_pair, start_ms, end_ms):
    fetch_plan = OrderedDict(
        [
            ("taker_long_short_5m", fetch_research_taker_long_short_series),
            ("top_long_short_account_5m", fetch_research_top_long_short_account_series),
            ("top_long_short_position_5m", fetch_research_top_long_short_position_series),
            ("basis_5m", fetch_research_basis_series),
        ]
    )
    updated = False
    series_errors = payload.setdefault("series_errors", {})
    for key, fetcher in fetch_plan.items():
        if key in payload:
            continue
        payload[key], error = fetch_optional_series(fetcher, symbol_pair, start_ms, end_ms)
        if error:
            series_errors[key] = error
        updated = True
        time.sleep(0.25)
    if updated:
        payload["generated_at_utc"] = datetime.utcnow().isoformat() + "Z"
    return updated


def load_or_fetch_perp_context(symbol_pair, start_dt, end_dt):
    start_ms = int(start_dt.timestamp() * 1000)
    end_ms = int(end_dt.timestamp() * 1000)
    path = cache_file_path(symbol_pair, start_ms, end_ms)
    if path.exists():
        payload = json.loads(path.read_text(encoding="utf-8"))
        if payload.get("status") == "ok" and hydrate_perp_context_payload(payload, symbol_pair, start_ms, end_ms):
            path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        return payload

    try:
        futures_5m = fetch_research_kline_series(BINANCE_FUTURES_KLINES_URL, symbol_pair, "5m", start_ms, end_ms)
        payload = {
            "symbol_pair": symbol_pair.upper(),
            "status": "ok",
            "start_ms": start_ms,
            "end_ms": end_ms,
            "generated_at_utc": datetime.utcnow().isoformat() + "Z",
            "futures_5m": futures_5m,
            "spot_5m": fetch_research_kline_series(BINANCE_SPOT_KLINES_URL, symbol_pair, "5m", start_ms, end_ms),
            "oi_hist_5m": fetch_research_oi_hist_series(symbol_pair, start_ms, end_ms),
            "funding": fetch_research_funding_series(symbol_pair, start_ms, end_ms),
            "series_errors": {},
        }
        hydrate_perp_context_payload(payload, symbol_pair, start_ms, end_ms)
    except Exception as exc:
        payload = {
            "symbol_pair": symbol_pair.upper(),
            "status": "error",
            "error": repr(exc),
            "start_ms": start_ms,
            "end_ms": end_ms,
            "generated_at_utc": datetime.utcnow().isoformat() + "Z",
            "futures_5m": [],
            "spot_5m": [],
            "oi_hist_5m": [],
            "funding": [],
            "taker_long_short_5m": [],
            "top_long_short_account_5m": [],
            "top_long_short_position_5m": [],
            "basis_5m": [],
            "series_errors": {},
        }
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return payload


def latest_row_before(series, time_key, entry_ms):
    for row in reversed(series):
        if row.get(time_key) is not None and row[time_key] <= entry_ms:
            return row
    return None


def trailing_rows(series, time_key, start_ms, end_ms):
    out = []
    for row in series:
        value = row.get(time_key)
        if value is None:
            continue
        if value <= end_ms and value > start_ms:
            out.append(row)
    return out


def hist_change_from_steps(series, steps_back, value_key):
    valid = [row for row in series if row.get(value_key) is not None]
    if len(valid) <= steps_back:
        return None
    current = valid[-1].get(value_key)
    previous = valid[-(steps_back + 1)].get(value_key)
    if current is None or previous in (None, 0):
        return None
    return (current - previous) / previous * 100


def latest_mean_delta_from_window(series, time_key, value_key, entry_ms, window_ms):
    latest_row = latest_row_before(series, time_key, entry_ms)
    latest_value = latest_row.get(value_key) if latest_row else None
    window_values = [
        row.get(value_key)
        for row in series
        if row.get(time_key) is not None and entry_ms - window_ms < row[time_key] <= entry_ms and row.get(value_key) is not None
    ]
    mean_value = mean_or_none(window_values)
    return latest_value, mean_value, (
        latest_value - mean_value
    ) if (latest_value is not None and mean_value is not None) else None


def compute_event_perp_features(event, context):
    if (context or {}).get("status") != "ok":
        return {
            "perp_feature_status": (context or {}).get("status") or "missing_context",
            "perp_feature_error": (context or {}).get("error"),
            "perp_last_price_at_entry": None,
            "spot_last_price_at_entry": None,
            "perp_quote_volume_24h": None,
            "perp_trade_count_24h": None,
            "spot_quote_volume_24h_calc": None,
            "open_interest_value_usd_now": None,
            "open_interest_contracts_now": None,
            "oi_change_5m_pct": None,
            "oi_change_15m_pct": None,
            "oi_change_1h_pct": None,
            "oi_change_4h_pct": None,
            "funding_rate_latest": None,
            "funding_rate_mean_24h": None,
            "funding_rate_latest_delta_vs_mean_24h": None,
            "perp_premium_pct_vs_spot": None,
            "perp_to_spot_volume_ratio_24h": None,
            "oi_to_perp_volume_ratio_24h": None,
            "perp_price_change_5m_pct": None,
            "perp_price_change_15m_pct": None,
            "perp_price_change_1h_pct": None,
            "confirm_feature_status": "missing",
            "taker_buy_sell_ratio_latest": None,
            "taker_buy_sell_ratio_mean_1h": None,
            "taker_buy_sell_ratio_delta_vs_mean_1h": None,
            "taker_buy_share_latest": None,
            "top_trader_account_lsr_latest": None,
            "top_trader_account_lsr_mean_1h": None,
            "top_trader_account_lsr_delta_vs_mean_1h": None,
            "top_trader_account_lsr_change_15m_pct": None,
            "top_trader_account_lsr_change_1h_pct": None,
            "top_trader_position_lsr_latest": None,
            "top_trader_position_lsr_mean_1h": None,
            "top_trader_position_lsr_delta_vs_mean_1h": None,
            "top_trader_position_lsr_change_15m_pct": None,
            "top_trader_position_lsr_change_1h_pct": None,
            "basis_rate_latest": None,
            "basis_rate_mean_1h": None,
            "basis_rate_delta_vs_mean_1h": None,
            "basis_value_latest": None,
            "annualized_basis_rate_latest": None,
            "buy_absorption_proxy_5m": None,
            "liq_long_flush_5m": None,
            "liq_long_flush_15m": None,
        }

    entry_ms = int(event["entry_dt"].timestamp() * 1000)
    futures_rows = context.get("futures_5m") or []
    spot_rows = context.get("spot_5m") or []
    oi_rows_all = context.get("oi_hist_5m") or []
    funding_rows_all = context.get("funding") or []
    taker_rows_all = context.get("taker_long_short_5m") or []
    top_account_rows_all = context.get("top_long_short_account_5m") or []
    top_position_rows_all = context.get("top_long_short_position_5m") or []
    basis_rows_all = context.get("basis_5m") or []

    fut_last = latest_row_before(futures_rows, "close_time_ms", entry_ms)
    spot_last = latest_row_before(spot_rows, "close_time_ms", entry_ms)
    futures_rows_to_entry = [row for row in futures_rows if row.get("close_time_ms") is not None and row["close_time_ms"] <= entry_ms]
    oi_rows = [row for row in oi_rows_all if row.get("timestamp_ms") is not None and row["timestamp_ms"] <= entry_ms]
    funding_rows = [row for row in funding_rows_all if row.get("funding_time_ms") is not None and row["funding_time_ms"] <= entry_ms]
    taker_rows = [row for row in taker_rows_all if row.get("timestamp_ms") is not None and row["timestamp_ms"] <= entry_ms]
    top_account_rows = [row for row in top_account_rows_all if row.get("timestamp_ms") is not None and row["timestamp_ms"] <= entry_ms]
    top_position_rows = [row for row in top_position_rows_all if row.get("timestamp_ms") is not None and row["timestamp_ms"] <= entry_ms]
    basis_rows = [row for row in basis_rows_all if row.get("timestamp_ms") is not None and row["timestamp_ms"] <= entry_ms]
    perp_window = trailing_rows(futures_rows, "close_time_ms", entry_ms - PERP_VOLUME_LOOKBACK_MS, entry_ms)
    spot_window = trailing_rows(spot_rows, "close_time_ms", entry_ms - PERP_VOLUME_LOOKBACK_MS, entry_ms)

    perp_quote_volume_24h = sum(row.get("quote_volume") or 0 for row in perp_window) if perp_window else None
    perp_trade_count_24h = sum(row.get("trade_count") or 0 for row in perp_window) if perp_window else None
    spot_quote_volume_24h = sum(row.get("quote_volume") or 0 for row in spot_window) if spot_window else None

    oi_value_now = oi_rows[-1].get("oi_value_usd") if oi_rows else None
    oi_contracts_now = oi_rows[-1].get("oi_contracts") if oi_rows else None
    funding_rate_latest = funding_rows[-1].get("funding_rate") if funding_rows else None
    funding_window = [
        row.get("funding_rate")
        for row in funding_rows
        if row.get("funding_time_ms") is not None and row["funding_time_ms"] > entry_ms - ONE_DAY_MS
    ]
    funding_rate_mean_24h = mean_or_none([value for value in funding_window if value is not None])
    oi_change_5m_pct = hist_change_from_steps(oi_rows, 1, "oi_value_usd")
    oi_change_15m_pct = hist_change_from_steps(oi_rows, 3, "oi_value_usd")
    oi_change_1h_pct = hist_change_from_steps(oi_rows, 12, "oi_value_usd")
    oi_change_4h_pct = hist_change_from_steps(oi_rows, 48, "oi_value_usd")
    perp_price_change_5m_pct = hist_change_from_steps(futures_rows_to_entry, 1, "close_price")
    perp_price_change_15m_pct = hist_change_from_steps(futures_rows_to_entry, 3, "close_price")
    perp_price_change_1h_pct = hist_change_from_steps(futures_rows_to_entry, 12, "close_price")
    taker_buy_sell_ratio_latest, taker_buy_sell_ratio_mean_1h, taker_buy_sell_ratio_delta_vs_mean_1h = latest_mean_delta_from_window(
        taker_rows, "timestamp_ms", "buy_sell_ratio", entry_ms, ONE_HOUR_MS
    )
    top_trader_account_lsr_latest, top_trader_account_lsr_mean_1h, top_trader_account_lsr_delta_vs_mean_1h = latest_mean_delta_from_window(
        top_account_rows, "timestamp_ms", "long_short_ratio", entry_ms, ONE_HOUR_MS
    )
    top_trader_position_lsr_latest, top_trader_position_lsr_mean_1h, top_trader_position_lsr_delta_vs_mean_1h = latest_mean_delta_from_window(
        top_position_rows, "timestamp_ms", "long_short_ratio", entry_ms, ONE_HOUR_MS
    )
    basis_rate_latest, basis_rate_mean_1h, basis_rate_delta_vs_mean_1h = latest_mean_delta_from_window(
        basis_rows, "timestamp_ms", "basis_rate", entry_ms, ONE_HOUR_MS
    )
    basis_last = latest_row_before(basis_rows, "timestamp_ms", entry_ms)
    taker_last = latest_row_before(taker_rows, "timestamp_ms", entry_ms)
    taker_buy_share_latest = None
    if taker_last:
        taker_buy_volume = taker_last.get("buy_volume")
        taker_sell_volume = taker_last.get("sell_volume")
        total_taker_volume = (taker_buy_volume or 0) + (taker_sell_volume or 0)
        if total_taker_volume > 0:
            taker_buy_share_latest = taker_buy_volume / total_taker_volume
    confirm_feature_status = (
        "ok"
        if (
            taker_buy_sell_ratio_latest is not None
            and top_trader_account_lsr_latest is not None
            and top_trader_position_lsr_latest is not None
            and basis_rate_latest is not None
        )
        else "partial"
    )

    return {
        "perp_feature_status": "ok" if fut_last and spot_last and oi_rows else "partial",
        "perp_feature_error": None,
        "perp_last_price_at_entry": fut_last.get("close_price") if fut_last else None,
        "spot_last_price_at_entry": spot_last.get("close_price") if spot_last else None,
        "perp_quote_volume_24h": perp_quote_volume_24h,
        "perp_trade_count_24h": perp_trade_count_24h,
        "spot_quote_volume_24h_calc": spot_quote_volume_24h,
        "open_interest_value_usd_now": oi_value_now,
        "open_interest_contracts_now": oi_contracts_now,
        "oi_change_5m_pct": oi_change_5m_pct,
        "oi_change_15m_pct": oi_change_15m_pct,
        "oi_change_1h_pct": oi_change_1h_pct,
        "oi_change_4h_pct": oi_change_4h_pct,
        "funding_rate_latest": funding_rate_latest,
        "funding_rate_mean_24h": funding_rate_mean_24h,
        "funding_rate_latest_delta_vs_mean_24h": (
            funding_rate_latest - funding_rate_mean_24h
        ) if (funding_rate_latest is not None and funding_rate_mean_24h is not None) else None,
        "perp_premium_pct_vs_spot": (
            (fut_last["close_price"] - spot_last["close_price"]) / spot_last["close_price"] * 100
        ) if (fut_last and spot_last and spot_last.get("close_price") not in (None, 0)) else None,
        "perp_to_spot_volume_ratio_24h": (
            perp_quote_volume_24h / spot_quote_volume_24h
        ) if (perp_quote_volume_24h is not None and spot_quote_volume_24h not in (None, 0)) else None,
        "oi_to_perp_volume_ratio_24h": (
            oi_value_now / perp_quote_volume_24h
        ) if (oi_value_now is not None and perp_quote_volume_24h not in (None, 0)) else None,
        "perp_price_change_5m_pct": perp_price_change_5m_pct,
        "perp_price_change_15m_pct": perp_price_change_15m_pct,
        "perp_price_change_1h_pct": perp_price_change_1h_pct,
        "confirm_feature_status": confirm_feature_status,
        "taker_buy_sell_ratio_latest": taker_buy_sell_ratio_latest,
        "taker_buy_sell_ratio_mean_1h": taker_buy_sell_ratio_mean_1h,
        "taker_buy_sell_ratio_delta_vs_mean_1h": taker_buy_sell_ratio_delta_vs_mean_1h,
        "taker_buy_share_latest": taker_buy_share_latest,
        "top_trader_account_lsr_latest": top_trader_account_lsr_latest,
        "top_trader_account_lsr_mean_1h": top_trader_account_lsr_mean_1h,
        "top_trader_account_lsr_delta_vs_mean_1h": top_trader_account_lsr_delta_vs_mean_1h,
        "top_trader_account_lsr_change_15m_pct": hist_change_from_steps(top_account_rows, 3, "long_short_ratio"),
        "top_trader_account_lsr_change_1h_pct": hist_change_from_steps(top_account_rows, 12, "long_short_ratio"),
        "top_trader_position_lsr_latest": top_trader_position_lsr_latest,
        "top_trader_position_lsr_mean_1h": top_trader_position_lsr_mean_1h,
        "top_trader_position_lsr_delta_vs_mean_1h": top_trader_position_lsr_delta_vs_mean_1h,
        "top_trader_position_lsr_change_15m_pct": hist_change_from_steps(top_position_rows, 3, "long_short_ratio"),
        "top_trader_position_lsr_change_1h_pct": hist_change_from_steps(top_position_rows, 12, "long_short_ratio"),
        "basis_rate_latest": basis_rate_latest,
        "basis_rate_mean_1h": basis_rate_mean_1h,
        "basis_rate_delta_vs_mean_1h": basis_rate_delta_vs_mean_1h,
        "basis_value_latest": basis_last.get("basis_value") if basis_last else None,
        "annualized_basis_rate_latest": basis_last.get("annualized_basis_rate") if basis_last else None,
        "buy_absorption_proxy_5m": (
            taker_buy_sell_ratio_latest is not None
            and perp_price_change_5m_pct is not None
            and taker_buy_sell_ratio_latest > TAKER_BUY_DOMINANT_THRESHOLD
            and perp_price_change_5m_pct <= PRICE_NONPOSITIVE_THRESHOLD
        ),
        "liq_long_flush_5m": (
            oi_change_5m_pct is not None
            and perp_price_change_5m_pct is not None
            and oi_change_5m_pct < 0
            and perp_price_change_5m_pct <= PRICE_NONPOSITIVE_THRESHOLD
        ),
        "liq_long_flush_15m": (
            oi_change_15m_pct is not None
            and perp_price_change_15m_pct is not None
            and oi_change_15m_pct < 0
            and perp_price_change_15m_pct <= PRICE_NONPOSITIVE_THRESHOLD
        ),
    }


def summarize_trade_samples(samples):
    pnls = [sample.get("equity_pnl_pct") for sample in samples if sample.get("equity_pnl_pct") is not None]
    rs = [sample.get("pnl_r") for sample in samples if sample.get("pnl_r") is not None]
    gross_win = sum(value for value in pnls if value > 0)
    gross_loss = -sum(value for value in pnls if value < 0)
    return {
        "count": len(samples),
        "win_rate": round_or_none(sum(1 for value in pnls if value > 0) / len(pnls)) if pnls else None,
        "mean_equity_pnl_pct": round_or_none(mean_or_none(pnls)),
        "median_equity_pnl_pct": round_or_none(median_or_none(pnls)),
        "mean_pnl_r": round_or_none(mean_or_none(rs)),
        "median_pnl_r": round_or_none(median_or_none(rs)),
        "profit_factor": round_or_none(gross_win / gross_loss) if gross_loss > 0 else None,
        "tp_rate": round_or_none(sum(1 for sample in samples if sample.get("reason") == "tp") / len(samples)) if samples else None,
        "sl_rate": round_or_none(sum(1 for sample in samples if sample.get("reason") == "sl") / len(samples)) if samples else None,
        "timeout_rate": round_or_none(sum(1 for sample in samples if sample.get("reason") == "timeout") / len(samples)) if samples else None,
    }


def summarize_trade_summary_delta(summary, base_summary):
    return {
        "win_rate_delta": round_or_none((summary.get("win_rate") or 0) - (base_summary.get("win_rate") or 0))
        if summary.get("win_rate") is not None and base_summary.get("win_rate") is not None
        else None,
        "mean_equity_pnl_pct_delta": round_or_none(
            (summary.get("mean_equity_pnl_pct") or 0) - (base_summary.get("mean_equity_pnl_pct") or 0)
        )
        if summary.get("mean_equity_pnl_pct") is not None and base_summary.get("mean_equity_pnl_pct") is not None
        else None,
        "mean_pnl_r_delta": round_or_none((summary.get("mean_pnl_r") or 0) - (base_summary.get("mean_pnl_r") or 0))
        if summary.get("mean_pnl_r") is not None and base_summary.get("mean_pnl_r") is not None
        else None,
        "sl_rate_delta": round_or_none((summary.get("sl_rate") or 0) - (base_summary.get("sl_rate") or 0))
        if summary.get("sl_rate") is not None and base_summary.get("sl_rate") is not None
        else None,
        "timeout_rate_delta": round_or_none((summary.get("timeout_rate") or 0) - (base_summary.get("timeout_rate") or 0))
        if summary.get("timeout_rate") is not None and base_summary.get("timeout_rate") is not None
        else None,
    }


def build_structure_perp_samples(signal_events, structure_profile):
    base_events = apply_filters(signal_events[structure_profile["signal"]], structure_profile["filters"])
    tradable = []
    for event in base_events:
        outcome = simulate_structure_short_trade(
            event,
            structure_profile["tp_r"],
            structure_profile["max_h"],
            structure_profile["risk_budget_pct"],
            structure_profile["min_stop_pct"],
            structure_profile["max_stop_pct"],
        )
        if outcome is None:
            continue
        tradable.append((event, outcome))

    ranges = {}
    for event, _ in tradable:
        pair = (event.get("binance_pair") or "").upper()
        if not pair:
            continue
        start_dt = event["entry_dt"] - timedelta(hours=PERP_ENRICH_WARMUP_H)
        end_dt = event["entry_dt"] + timedelta(minutes=5)
        item = ranges.get(pair)
        if item is None:
            ranges[pair] = {"start_dt": start_dt, "end_dt": end_dt}
        else:
            item["start_dt"] = min(item["start_dt"], start_dt)
            item["end_dt"] = max(item["end_dt"], end_dt)

    contexts = {
        pair: load_or_fetch_perp_context(pair, payload["start_dt"], payload["end_dt"])
        for pair, payload in ranges.items()
    }

    samples = []
    for event, outcome in tradable:
        sample = {key: value for key, value in event.items() if key != "future_rows"}
        sample.update(outcome)
        pair = (event.get("binance_pair") or "").upper()
        if pair in contexts:
            sample.update(compute_event_perp_features(event, contexts[pair]))
        else:
            sample["perp_feature_status"] = "missing_pair"
            sample["perp_feature_error"] = None
        sample["entry_dt"] = sample["entry_dt_utc"]
        samples.append(sample)
    return samples


def build_perp_filter_study(samples):
    eligible = [sample for sample in samples if sample.get("perp_feature_status") == "ok"]
    base_summary = summarize_trade_samples(eligible)
    out = OrderedDict()
    for filter_name, predicate in PERP_FILTERS.items():
        subset = [sample for sample in eligible if predicate(sample)]
        if len(subset) < PERP_FILTER_MIN_COUNT:
            continue
        summary = summarize_trade_samples(subset)
        out[filter_name] = {
            "sample_share": round_or_none(len(subset) / len(eligible)) if eligible else None,
            "summary": summary,
            "vs_base": summarize_trade_summary_delta(summary, base_summary),
        }
    return out


def build_perp_confirm_meta(samples):
    oi_1h_expanding = [
        sample
        for sample in samples
        if sample.get("perp_feature_status") == "ok"
        and sample.get("oi_change_1h_pct") is not None
        and sample["oi_change_1h_pct"] > 0
    ]
    status_mix = defaultdict(int)
    for sample in oi_1h_expanding:
        status_mix[sample.get("confirm_feature_status") or "unknown"] += 1
    confirm_eligible = [sample for sample in oi_1h_expanding if sample.get("confirm_feature_status") == "ok"]
    return {
        "oi_1h_expanding_count": len(oi_1h_expanding),
        "confirm_eligible_count": len(confirm_eligible),
        "confirm_eligible_ratio": round_or_none(len(confirm_eligible) / len(oi_1h_expanding)) if oi_1h_expanding else None,
        "status_mix": dict(sorted(status_mix.items())),
    }


def build_perp_confirm_filter_study(samples):
    oi_1h_expanding = [
        sample
        for sample in samples
        if sample.get("perp_feature_status") == "ok"
        and sample.get("oi_change_1h_pct") is not None
        and sample["oi_change_1h_pct"] > 0
        and sample.get("confirm_feature_status") == "ok"
    ]
    base_summary = summarize_trade_samples(oi_1h_expanding)
    out = OrderedDict()
    for filter_name, predicate in PERP_CONFIRM_FILTERS.items():
        subset = [sample for sample in oi_1h_expanding if predicate(sample)]
        if len(subset) < PERP_CONFIRM_FILTER_MIN_COUNT:
            continue
        summary = summarize_trade_samples(subset)
        out[filter_name] = {
            "sample_share": round_or_none(len(subset) / len(oi_1h_expanding)) if oi_1h_expanding else None,
            "summary": summary,
            "vs_base": summarize_trade_summary_delta(summary, base_summary),
        }
    return out


def build_perp_structure_meta(samples):
    status_mix = defaultdict(int)
    for sample in samples:
        status_mix[sample.get("perp_feature_status") or "unknown"] += 1
    eligible = [sample for sample in samples if sample.get("perp_feature_status") == "ok"]
    return {
        "structure_sample_count": len(samples),
        "perp_eligible_count": len(eligible),
        "perp_eligible_ratio": round_or_none(len(eligible) / len(samples)) if samples else None,
        "status_mix": dict(sorted(status_mix.items())),
    }


def serialize_signal_events(signal_events):
    out = {}
    for signal_name, events in signal_events.items():
        out[signal_name] = []
        for event in events:
            payload = {k: v for k, v in event.items() if k != "future_rows"}
            payload["entry_dt"] = payload.pop("entry_dt_utc")
            out[signal_name].append(payload)
    return out


def main():
    parser = argparse.ArgumentParser(description="Run short-fade research on TOP15 overlap history")
    parser.add_argument("--history-jsonl", default=str(DEFAULT_HISTORY_JSONL), help="Path to history.jsonl")
    parser.add_argument("--output-json", default=str(DEFAULT_OUTPUT_JSON), help="Output JSON report path")
    parser.add_argument("--output-md", default=str(DEFAULT_OUTPUT_MD), help="Output markdown report path")
    args = parser.parse_args()

    history_jsonl_path = Path(args.history_jsonl)
    output_json_path = Path(args.output_json)
    output_md_path = Path(args.output_md)
    output_json_path.parent.mkdir(parents=True, exist_ok=True)
    output_md_path.parent.mkdir(parents=True, exist_ok=True)

    rows_by_symbol, meta = load_rows_by_symbol(history_jsonl_path)
    signal_events = build_signal_events(rows_by_symbol)
    signal_summaries = OrderedDict((signal_name, summarize_events(events)) for signal_name, events in signal_events.items())
    focus_filter_study = build_filter_study(signal_events[FOCUS_SIGNAL_NAME])
    execution_study = build_execution_study(signal_events)
    shadow_layer_study = build_shadow_layer_study(signal_events)
    strategy_candidate = build_strategy_candidate(execution_study)
    structure_meta = build_structure_meta(signal_events)
    perp_structure_samples = build_structure_perp_samples(signal_events, execution_study[REFERENCE_STRUCTURE_PROFILE_NAME])
    perp_structure_meta = build_perp_structure_meta(perp_structure_samples)
    perp_eligible_samples = [sample for sample in perp_structure_samples if sample.get("perp_feature_status") == "ok"]
    perp_structure_summary = summarize_trade_samples(perp_eligible_samples)
    perp_v3_study = build_perp_filter_study(perp_structure_samples)
    perp_confirm_meta = build_perp_confirm_meta(perp_structure_samples)
    perp_confirm_samples = [
        sample
        for sample in perp_structure_samples
        if sample.get("perp_feature_status") == "ok"
        and sample.get("oi_change_1h_pct") is not None
        and sample["oi_change_1h_pct"] > 0
        and sample.get("confirm_feature_status") == "ok"
    ]
    perp_confirm_summary = summarize_trade_samples(perp_confirm_samples)
    perp_confirm_study = build_perp_confirm_filter_study(perp_structure_samples)
    focus_samples = build_focus_samples(apply_filters(signal_events[FOCUS_SIGNAL_NAME], DEFAULT_FOCUS_FILTERS))

    report = {
        "meta": {
            **meta,
            "history_source": str(history_jsonl_path.relative_to(WORKDIR)),
            "filter_rule": FILTER_RULE,
            "signal_definitions": SIGNAL_DEFINITIONS,
        },
        "signals": signal_summaries,
        "focus_filter_study": focus_filter_study,
        "execution_study": execution_study,
        "shadow_layer_study": shadow_layer_study,
        "strategy_candidate": strategy_candidate,
        "structure_meta": structure_meta,
        "perp_structure_meta": perp_structure_meta,
        "perp_structure_summary": perp_structure_summary,
        "perp_v3_study": perp_v3_study,
        "perp_confirm_meta": perp_confirm_meta,
        "perp_confirm_summary": perp_confirm_summary,
        "perp_confirm_study": perp_confirm_study,
        "perp_structure_samples": perp_structure_samples,
        "focus_samples": focus_samples,
        "event_payloads": serialize_signal_events(signal_events),
    }

    markdown = build_markdown(report)
    output_json_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    output_md_path.write_text(markdown, encoding="utf-8")

    print(
        json.dumps(
            {
                "ok": True,
                "history_jsonl": str(history_jsonl_path.relative_to(WORKDIR)),
                "output_json": str(output_json_path.relative_to(WORKDIR)),
                "output_md": str(output_md_path.relative_to(WORKDIR)),
                "focus_signal": FOCUS_SIGNAL_NAME,
                "focus_signal_count": len(signal_events[FOCUS_SIGNAL_NAME]),
                "selective_signal_count": len(apply_filters(signal_events[FOCUS_SIGNAL_NAME], DEFAULT_FOCUS_FILTERS)),
                "shadow_layer_comparison": shadow_layer_study["comparison"],
                "fixed_reference_profile": execution_study[REFERENCE_FIXED_PROFILE_NAME],
                "structure_profile": execution_study[REFERENCE_STRUCTURE_PROFILE_NAME],
                "perp_structure_meta": perp_structure_meta,
                "perp_structure_summary": perp_structure_summary,
                "perp_v3_top_filters": perp_v3_study,
                "perp_confirm_meta": perp_confirm_meta,
                "perp_confirm_summary": perp_confirm_summary,
                "perp_confirm_top_filters": perp_confirm_study,
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(json.dumps({"ok": False, "error": repr(exc)}, ensure_ascii=False), file=sys.stderr)
        raise
