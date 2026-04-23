#!/usr/bin/env python3
import argparse
import contextlib
import fcntl
import json
import os
import sys
import uuid
from datetime import datetime, timezone
from decimal import Decimal, ROUND_DOWN, ROUND_UP
from pathlib import Path

import top15_short_strategy as short_strategy_module
from top15_short_strategy import RISK_CONFIG, build_shadow_strategy_signals

try:
    from binance_common.configuration import ConfigurationRestAPI
    from binance_sdk_derivatives_trading_usds_futures import (
        DERIVATIVES_TRADING_USDS_FUTURES_REST_API_TESTNET_URL,
        DerivativesTradingUsdsFutures,
    )
    BINANCE_SDK_IMPORT_ERROR = None
except Exception as exc:  # pragma: no cover - runtime dependency check
    ConfigurationRestAPI = None
    DerivativesTradingUsdsFutures = None
    DERIVATIVES_TRADING_USDS_FUTURES_REST_API_TESTNET_URL = "https://testnet.binancefuture.com"
    BINANCE_SDK_IMPORT_ERROR = repr(exc)

WORKDIR = Path(__file__).resolve().parents[1]
DATA_DIR = WORKDIR / "data" / "top15_tracker"
LATEST_DIR = DATA_DIR / "latest"
DEFAULT_CONFIG_PATH = WORKDIR / "config" / "binance_c_strategy.testnet.json"
EXAMPLE_CONFIG_PATH = WORKDIR / "config" / "binance_c_strategy.testnet.example.json"
LIVE_TRADER_DIR = DATA_DIR / "live_trader" / "c_strategy_testnet"
STATE_PATH = LIVE_TRADER_DIR / "state.json"
JOURNAL_PATH = LIVE_TRADER_DIR / "journal.jsonl"
LATEST_PATH = LIVE_TRADER_DIR / "latest.json"
LOCK_PATH = LIVE_TRADER_DIR / ".lock"

LIVE_TRADER_DIR.mkdir(parents=True, exist_ok=True)


def safe_float(value):
    try:
        num = float(value)
    except (TypeError, ValueError):
        return None
    return num if num == num else None


def now_utc_iso():
    return datetime.now(timezone.utc).isoformat()


def read_json(path: Path, default=None):
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


def write_json(path: Path, payload):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def append_jsonl(path: Path, payload):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(payload, ensure_ascii=False) + "\n")


def read_jsonl_tail(path: Path, limit=50):
    if not path.exists():
        return []
    try:
        lines = [line for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
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


def model_to_plain(value):
    if isinstance(value, list):
        return [model_to_plain(item) for item in value]
    if isinstance(value, dict):
        return {key: model_to_plain(item) for key, item in value.items()}
    if hasattr(value, "to_dict"):
        return model_to_plain(value.to_dict())
    return value


def require_binance_sdk():
    if BINANCE_SDK_IMPORT_ERROR:
        raise RuntimeError(
            "Binance SDK 未安装或导入失败。先执行 `python3 -m pip install -r requirements-live-trader.txt`。"
            f" import_error={BINANCE_SDK_IMPORT_ERROR}"
        )


def deep_merge(base, patch):
    out = dict(base)
    for key, value in (patch or {}).items():
        if isinstance(value, dict) and isinstance(out.get(key), dict):
            out[key] = deep_merge(out[key], value)
        else:
            out[key] = value
    return out


def default_config():
    return {
        "enabled": False,
        "account_label": "binance_c_strategy_testnet",
        "binance": {
            "api_key_env": "BINANCE_C_TESTNET_API_KEY",
            "api_secret_env": "BINANCE_C_TESTNET_API_SECRET",
            "base_url": DERIVATIVES_TRADING_USDS_FUTURES_REST_API_TESTNET_URL,
            "recv_window": 5000,
            "timeout_ms": 10000,
            "retries": 3,
            "backoff_ms": 1000,
            "working_type": "MARK_PRICE",
            "price_protect": False,
            "ensure_one_way_mode": True,
            "set_symbol_leverage": True,
        },
        "strategy": {
            "strategy_id": "C_overheat_fade_wide",
            "max_concurrent": int(RISK_CONFIG.get("max_concurrent") or 3),
            "exit_on_signal_loss": True,
            "recreate_protection_if_missing": True,
            "block_on_orphan_positions": True,
            "allow_symbols": [],
            "block_symbols": [],
        },
        "risk": {
            "use_exchange_margin_balance": True,
            "fallback_equity_usd": float(RISK_CONFIG.get("initial_equity_usd") or 10000.0),
            "risk_pct": float(RISK_CONFIG.get("risk_pct") or 5.0),
            "max_gross_pct": 500.0,
            "leverage": 5.0,
            "margin_buffer_pct": 95.0,
            "min_notional_usd": 20.0,
        },
        "execution": {
            "validate_entry_with_test_order": True,
            "cancel_all_symbol_algo_orders_on_exit": True,
            "entry_retry_shrink_pct": 97.0,
            "max_entry_retries": 6,
        },
        "reporting": {
            "starting_capital_usd": 4941.0,
            "recent_event_limit": 40,
        },
    }


def load_config(path: Path):
    if not path.exists():
        raise FileNotFoundError(
            f"配置文件不存在：{path}。先复制模板：cp {EXAMPLE_CONFIG_PATH} {path}"
        )
    raw = read_json(path, default={}) or {}
    return deep_merge(default_config(), raw)


def normalize_symbol_list(values):
    seen = []
    for item in values or []:
        symbol = str(item or "").strip().upper()
        if symbol and symbol not in seen:
            seen.append(symbol)
    return seen


def apply_runtime_overrides(config, args):
    if getattr(args, "allow_symbol", None):
        config["strategy"]["allow_symbols"] = normalize_symbol_list([args.allow_symbol])
    else:
        config["strategy"]["allow_symbols"] = normalize_symbol_list(config["strategy"].get("allow_symbols"))
    config["strategy"]["block_symbols"] = normalize_symbol_list(config["strategy"].get("block_symbols"))
    if getattr(args, "only_one_trade", False):
        config["strategy"]["max_concurrent"] = 1
    elif getattr(args, "max_concurrent", None) is not None:
        config["strategy"]["max_concurrent"] = max(0, int(args.max_concurrent))
    return config


def apply_signal_runtime_overrides(args):
    if getattr(args, "stop_window_min_pct", None) is not None:
        short_strategy_module.STRUCTURE_STOP_MIN_PCT = float(args.stop_window_min_pct)
    if getattr(args, "stop_window_max_pct", None) is not None:
        short_strategy_module.STRUCTURE_STOP_MAX_PCT = float(args.stop_window_max_pct)


def default_state():
    return {
        "version": "c_strategy_testnet_v1",
        "last_processed_snapshot_id": None,
        "last_run_at": None,
        "active_trades": {},
    }


def load_state():
    raw = read_json(STATE_PATH, default=None)
    state = default_state()
    if isinstance(raw, dict):
        state.update(raw)
    state["active_trades"] = {
        symbol: dict(item)
        for symbol, item in (state.get("active_trades") or {}).items()
        if isinstance(item, dict)
    }
    return state


def save_state(state):
    write_json(STATE_PATH, state)


def load_latest_snapshot():
    manifest = read_json(LATEST_DIR / "manifest.json", default={}) or {}
    rows = read_json(LATEST_DIR / "latest.json", default=[]) or []
    if not manifest.get("latest_snapshot_id"):
        raise RuntimeError("latest/manifest.json 缺少 latest_snapshot_id，先跑采集器。")
    if not isinstance(rows, list) or not rows:
        raise RuntimeError("latest/latest.json 为空，先跑采集器。")
    return manifest, rows


@contextlib.contextmanager
def file_lock(path: Path):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def decimal_floor(value, step):
    if step in (None, 0, "0", ""):
        return Decimal(str(value))
    step_dec = Decimal(str(step))
    value_dec = Decimal(str(value))
    units = (value_dec / step_dec).to_integral_value(rounding=ROUND_DOWN)
    return units * step_dec


def decimal_ceil(value, step):
    if step in (None, 0, "0", ""):
        return Decimal(str(value))
    step_dec = Decimal(str(step))
    value_dec = Decimal(str(value))
    units = (value_dec / step_dec).to_integral_value(rounding=ROUND_UP)
    return units * step_dec


def to_plain_float(value):
    value = safe_float(value)
    return float(value) if value is not None else None


def ensure_plain_list(value):
    if isinstance(value, list):
        return [item for item in value if isinstance(item, dict)]
    if isinstance(value, dict):
        return [value]
    return []


def build_filter_map(symbol_info):
    filters = {}
    for item in symbol_info.get("filters") or []:
        if isinstance(item, dict) and item.get("filterType"):
            filters[item["filterType"]] = item
    return filters


def normalize_symbol_info_map(exchange_info):
    out = {}
    for item in exchange_info.get("symbols") or []:
        if hasattr(item, "to_dict"):
            item = item.to_dict()
        if isinstance(item, dict) and item.get("symbol"):
            out[item["symbol"]] = item
    return out


def market_step_size(symbol_info):
    filters = build_filter_map(symbol_info)
    market_lot = filters.get("MARKET_LOT_SIZE") or {}
    lot = filters.get("LOT_SIZE") or {}
    return market_lot.get("stepSize") or lot.get("stepSize") or "0"


def min_market_qty(symbol_info):
    filters = build_filter_map(symbol_info)
    market_lot = filters.get("MARKET_LOT_SIZE") or {}
    lot = filters.get("LOT_SIZE") or {}
    return safe_float(market_lot.get("minQty")) or safe_float(lot.get("minQty")) or 0.0


def max_market_qty(symbol_info):
    filters = build_filter_map(symbol_info)
    market_lot = filters.get("MARKET_LOT_SIZE") or {}
    lot = filters.get("LOT_SIZE") or {}
    return safe_float(market_lot.get("maxQty")) or safe_float(lot.get("maxQty")) or 0.0


def price_tick_size(symbol_info):
    filters = build_filter_map(symbol_info)
    price_filter = filters.get("PRICE_FILTER") or {}
    return price_filter.get("tickSize") or "0"


def min_notional(symbol_info):
    filters = build_filter_map(symbol_info)
    notional_filter = filters.get("MIN_NOTIONAL") or filters.get("NOTIONAL") or {}
    return safe_float(notional_filter.get("notional")) or 0.0


def round_qty_down(quantity, symbol_info):
    step = market_step_size(symbol_info)
    qty = decimal_floor(quantity, step)
    return float(qty) if qty > 0 else 0.0


def shrink_qty_down(quantity, symbol_info, shrink_pct):
    quantity = safe_float(quantity) or 0.0
    shrink_pct = safe_float(shrink_pct) or 100.0
    if quantity <= 0:
        return 0.0
    next_qty = round_qty_down(quantity * shrink_pct / 100.0, symbol_info)
    if 0 < next_qty < quantity:
        return next_qty
    step = safe_float(market_step_size(symbol_info)) or 0.0
    if step > 0 and quantity > step:
        return round_qty_down(quantity - step, symbol_info)
    return 0.0


def round_price_up(price, symbol_info):
    tick = price_tick_size(symbol_info)
    return float(decimal_ceil(price, tick))


def active_short_positions_by_symbol(positions):
    out = {}
    for item in positions:
        if not isinstance(item, dict):
            continue
        position_amt = safe_float(item.get("positionAmt"))
        symbol = item.get("symbol")
        if not symbol or position_amt is None or position_amt >= 0:
            continue
        out[symbol] = item
    return out


def open_algo_orders_by_symbol(algo_orders):
    out = {}
    for item in algo_orders:
        if not isinstance(item, dict):
            continue
        symbol = item.get("symbol")
        if not symbol:
            continue
        out.setdefault(symbol, []).append(item)
    return out


def compute_account_metrics(config, account_info, short_positions):
    account_info = account_info if isinstance(account_info, dict) else {}
    total_margin_balance = safe_float(account_info.get("totalMarginBalance"))
    available_balance = safe_float(account_info.get("availableBalance"))
    fallback_equity = safe_float(config["risk"].get("fallback_equity_usd")) or 0.0
    equity_usd = total_margin_balance if config["risk"].get("use_exchange_margin_balance", True) else None
    if equity_usd is None:
        equity_usd = available_balance if available_balance is not None else fallback_equity
    available_balance_usd = available_balance if available_balance is not None else equity_usd
    open_gross_usd = sum(abs(safe_float(item.get("notional")) or 0.0) for item in short_positions.values())
    gross_cap_usd = equity_usd * (safe_float(config["risk"].get("max_gross_pct")) or 0.0) / 100.0
    return {
        "equity_usd": equity_usd,
        "available_balance_usd": available_balance_usd,
        "open_gross_usd": open_gross_usd,
        "gross_cap_usd": gross_cap_usd,
        "remaining_gross_usd": max(0.0, gross_cap_usd - open_gross_usd),
        "open_count": len(short_positions),
    }


def load_exchange_runtime(client, config, symbol_info_map=None):
    if symbol_info_map is None:
        exchange_info = client.exchange_info()
        symbol_info_map = normalize_symbol_info_map(exchange_info)
    account_info = client.account_info()
    short_positions = active_short_positions_by_symbol(ensure_plain_list(client.positions()))
    algo_orders_by_symbol = open_algo_orders_by_symbol(ensure_plain_list(client.open_algo_orders()))
    metrics = compute_account_metrics(config, account_info, short_positions)
    return {
        "account_info": account_info,
        "symbol_info_map": symbol_info_map,
        "short_positions": short_positions,
        "algo_orders_by_symbol": algo_orders_by_symbol,
        "metrics": metrics,
    }


def compute_entry_plan(config, metrics, signal, symbol_info):
    stop_pct = safe_float(signal.get("structure_stop_pct"))
    market_price = safe_float(signal.get("perp_last_price")) or safe_float(signal.get("current_price"))
    leverage = safe_float(config["risk"].get("leverage")) or 1.0
    risk_pct = safe_float(config["risk"].get("risk_pct")) or 0.0
    margin_buffer_pct = safe_float(config["risk"].get("margin_buffer_pct")) or 100.0
    risk_usd = metrics["equity_usd"] * risk_pct / 100.0
    risk_sized_notional = risk_usd / (stop_pct / 100.0) if stop_pct not in (None, 0) else 0.0
    margin_cap_notional_raw = metrics["available_balance_usd"] * leverage
    margin_cap_notional = margin_cap_notional_raw * margin_buffer_pct / 100.0
    size_usd = min(risk_sized_notional, metrics["remaining_gross_usd"], margin_cap_notional)
    raw_qty = (size_usd / market_price) if market_price not in (None, 0) else 0.0
    qty = round_qty_down(raw_qty, symbol_info)
    max_qty = max_market_qty(symbol_info)
    if max_qty and qty > max_qty:
        qty = round_qty_down(max_qty, symbol_info)
    notional_usd = qty * market_price
    min_qty = min_market_qty(symbol_info)
    symbol_min_notional = min_notional(symbol_info)
    min_notional_usd = max(safe_float(config["risk"].get("min_notional_usd")) or 0.0, symbol_min_notional)
    return {
        "ok": (
            metrics["open_count"] < int(config["strategy"].get("max_concurrent") or 0)
            and qty >= min_qty
            and notional_usd >= min_notional_usd
            and stop_pct not in (None, 0)
            and market_price not in (None, 0)
        ),
        "risk_usd": risk_usd,
        "risk_sized_notional_usd": risk_sized_notional,
        "margin_cap_notional_usd": margin_cap_notional,
        "margin_cap_notional_raw_usd": margin_cap_notional_raw,
        "size_usd": size_usd,
        "quantity": qty,
        "notional_usd": notional_usd,
        "market_price": market_price,
        "min_qty": min_qty,
        "max_qty": max_qty,
        "min_notional_usd": min_notional_usd,
        "margin_usd": (notional_usd / leverage) if leverage else notional_usd,
    }


def build_candidate_records(config, rows):
    allowed_symbols = {str(item).upper() for item in config["strategy"].get("allow_symbols") or []}
    blocked_symbols = {str(item).upper() for item in config["strategy"].get("block_symbols") or []}
    candidates = []
    signal_map = {}
    for row in rows:
        symbol = (row.get("binance_perp_symbol") or "").upper()
        status = row.get("binance_perp_status")
        if not symbol or status not in {"matched", "matched_partial_error"}:
            continue
        if allowed_symbols and symbol not in allowed_symbols:
            continue
        if symbol in blocked_symbols:
            continue
        signal = build_shadow_strategy_signals(row).get(config["strategy"]["strategy_id"])
        if not signal:
            continue
        signal = refresh_signal_for_runtime(signal)
        signal["perp_symbol"] = symbol
        signal["perp_last_price"] = safe_float(row.get("perp_last_price"))
        signal_map[symbol] = signal
        if signal.get("openable"):
            candidates.append(signal)
    candidates.sort(
        key=lambda item: (
            -(safe_float(item.get("quality_score")) or 0.0),
            -(safe_float(item.get("overlap_score")) or -999.0),
            safe_float(item.get("structure_stop_pct")) or 999.0,
        )
    )
    return candidates, signal_map


def candidate_preview(candidates, limit):
    out = []
    for item in candidates[: max(0, int(limit or 0))]:
        out.append(
            {
                "symbol": item.get("perp_symbol"),
                "quality_score": safe_float(item.get("quality_score")),
                "overlap_score": safe_float(item.get("overlap_score")),
                "structure_stop_pct": safe_float(item.get("structure_stop_pct")),
                "signal_summary": item.get("signal_summary"),
            }
        )
    return out


def is_margin_insufficient_error(exc):
    text = repr(exc)
    return "-2019" in text or "Margin is insufficient" in text


def is_max_quantity_error(exc):
    text = repr(exc)
    return "-4005" in text or "Quantity greater than max quantity" in text


def resolve_signal_stop_window(signal):
    signal = signal if isinstance(signal, dict) else {}
    min_pct = safe_float(signal.get("stop_window_min_pct"))
    max_pct = safe_float(signal.get("stop_window_max_pct"))
    if min_pct is None:
        min_pct = short_strategy_module.STRUCTURE_STOP_MIN_PCT
    if max_pct is None:
        max_pct = short_strategy_module.STRUCTURE_STOP_MAX_PCT
    return min_pct, max_pct


def refresh_signal_for_runtime(signal):
    signal = dict(signal or {})
    stop_pct = safe_float(signal.get("structure_stop_pct"))
    triggered = bool(signal.get("triggered"))
    prev_stop_tradable = bool(signal.get("stop_tradable"))
    stop_window_min_pct, stop_window_max_pct = resolve_signal_stop_window(signal)
    stop_tradable = stop_pct is not None and stop_window_min_pct <= stop_pct <= stop_window_max_pct
    blockers = [item for item in (signal.get("blockers") or []) if not str(item).startswith("结构止损")]
    if triggered and stop_pct is None:
        if "缺少结构止损上下文" not in blockers:
            blockers.append("缺少结构止损上下文")
    elif triggered and stop_pct is not None and not stop_tradable:
        blockers.append(f"结构止损{stop_pct:.2f}%不在{stop_window_min_pct:.1f}%~{stop_window_max_pct:.1f}%")
    signal["stop_window_min_pct"] = stop_window_min_pct
    signal["stop_window_max_pct"] = stop_window_max_pct
    signal["stop_tradable"] = stop_tradable
    signal["openable"] = triggered and stop_tradable
    if signal.get("quality_score") is not None and prev_stop_tradable != stop_tradable:
        delta = 1 if stop_tradable else -1
        signal["quality_score"] = max(0, int(signal.get("quality_score") or 0) + delta)
    signal["blockers"] = blockers
    return signal


def create_journal_event(event_type, payload):
    event = {"ts": now_utc_iso(), "event_type": event_type}
    event.update(payload)
    append_jsonl(JOURNAL_PATH, event)
    return event


def build_live_position_payload(symbol, trade, runtime_position, algo_orders):
    runtime_position = runtime_position if isinstance(runtime_position, dict) else {}
    entry = trade.get("entry") or {}
    structure = trade.get("structure") or {}
    entry_price = safe_float(entry.get("avg_price"))
    mark_price = safe_float(runtime_position.get("markPrice")) or entry_price
    unrealized_pnl_usd = safe_float(runtime_position.get("unRealizedProfit"))
    if unrealized_pnl_usd is None and entry_price not in (None, 0) and mark_price is not None:
        qty = abs(safe_float(runtime_position.get("positionAmt")) or safe_float(entry.get("executed_qty")) or 0.0)
        unrealized_pnl_usd = (entry_price - mark_price) * qty
    notional_usd = abs(safe_float(runtime_position.get("notional")) or 0.0)
    if notional_usd == 0 and mark_price not in (None, 0):
        notional_usd = abs(safe_float(runtime_position.get("positionAmt")) or safe_float(entry.get("executed_qty")) or 0.0) * mark_price
    unrealized_pnl_pct = ((entry_price - mark_price) / entry_price) * 100.0 if entry_price not in (None, 0) and mark_price is not None else None
    return {
        "symbol": symbol,
        "opened_at": trade.get("opened_at"),
        "snapshot_id": trade.get("snapshot_id"),
        "signal_summary": trade.get("signal_summary"),
        "quality_score": safe_float(trade.get("quality_score")),
        "entry_price": entry_price,
        "entry_qty": safe_float(entry.get("executed_qty")),
        "entry_notional_usd": safe_float(entry.get("notional_usd")),
        "mark_price": mark_price,
        "position_qty": abs(safe_float(runtime_position.get("positionAmt")) or safe_float(entry.get("executed_qty")) or 0.0),
        "position_notional_usd": notional_usd,
        "unrealized_pnl_usd": unrealized_pnl_usd,
        "unrealized_pnl_pct": unrealized_pnl_pct,
        "stop_price": safe_float(structure.get("stop_price")),
        "target_price": safe_float(structure.get("target_price")),
        "stop_pct": safe_float(structure.get("stop_pct")),
        "front_high_price": safe_float(structure.get("front_high_price")),
        "atr_1h_pct": safe_float(structure.get("atr_1h_pct")),
        "protection": trade.get("protection") or {},
        "algo_orders": algo_orders or [],
    }


def build_live_trader_payload(config, state, snapshot_id, runtime, summary):
    reporting = config.get("reporting") or {}
    starting_capital_usd = safe_float(reporting.get("starting_capital_usd")) or 4941.0
    metrics = (runtime or {}).get("metrics") or {}
    short_positions = (runtime or {}).get("short_positions") or {}
    algo_orders_by_symbol = (runtime or {}).get("algo_orders_by_symbol") or {}
    active_trades = (state.get("active_trades") or {}) if isinstance(state, dict) else {}

    positions = []
    for symbol, trade in active_trades.items():
        positions.append(
            build_live_position_payload(
                symbol,
                trade,
                short_positions.get(symbol),
                algo_orders_by_symbol.get(symbol) or [],
            )
        )
    positions.sort(key=lambda item: item.get("opened_at") or "", reverse=True)

    unrealized_pnl_usd = sum(safe_float(item.get("unrealized_pnl_usd")) or 0.0 for item in positions)
    equity_usd = safe_float(metrics.get("equity_usd")) or starting_capital_usd
    total_pnl_usd = equity_usd - starting_capital_usd
    realized_pnl_usd = total_pnl_usd - unrealized_pnl_usd
    recent_events = read_jsonl_tail(JOURNAL_PATH, reporting.get("recent_event_limit") or 40)
    recent_events.sort(key=lambda item: item.get("ts") or "", reverse=True)

    return {
        "ok": True,
        "version": (state or {}).get("version") or "c_strategy_testnet_v1",
        "account_label": config.get("account_label") or "binance_c_strategy_testnet",
        "strategy_id": ((config.get("strategy") or {}).get("strategy_id")) or "C_overheat_fade",
        "enabled": bool(config.get("enabled")),
        "snapshot_id": snapshot_id,
        "last_run_at": (state or {}).get("last_run_at"),
        "starting_capital_usd": starting_capital_usd,
        "account": {
            "equity_usd": equity_usd,
            "available_balance_usd": safe_float(metrics.get("available_balance_usd")),
            "open_gross_usd": safe_float(metrics.get("open_gross_usd")),
            "gross_cap_usd": safe_float(metrics.get("gross_cap_usd")),
        },
        "summary": {
            "starting_capital_usd": starting_capital_usd,
            "equity_usd": equity_usd,
            "total_pnl_usd": total_pnl_usd,
            "realized_pnl_usd": realized_pnl_usd,
            "unrealized_pnl_usd": unrealized_pnl_usd,
            "roi_pct": (total_pnl_usd / starting_capital_usd * 100.0) if starting_capital_usd else None,
            "open_count": len(positions),
            "recent_event_count": len(recent_events),
        },
        "positions": positions,
        "recent_events": recent_events,
        "runtime": {
            "candidate_count": summary.get("candidate_count"),
            "candidate_preview": summary.get("candidate_preview") or [],
            "warnings": summary.get("warnings") or [],
            "opened": summary.get("opened") or [],
            "closed": summary.get("closed") or [],
            "failed": summary.get("failed") or [],
        },
    }


def resolve_runtime_stop_window(signal_map):
    for signal in (signal_map or {}).values():
        return resolve_signal_stop_window(signal)
    return short_strategy_module.STRUCTURE_STOP_MIN_PCT, short_strategy_module.STRUCTURE_STOP_MAX_PCT


class FatalTradeOpenError(RuntimeError):
    pass


class BinanceUsdsFuturesSdkClient:
    def __init__(self, config):
        require_binance_sdk()
        binance_cfg = config["binance"]
        api_key = os.environ.get(binance_cfg.get("api_key_env") or "", "")
        api_secret = os.environ.get(binance_cfg.get("api_secret_env") or "", "")
        if not api_key or not api_secret:
            raise RuntimeError(
                f"缺少 API Key/Secret 环境变量：{binance_cfg.get('api_key_env')} / {binance_cfg.get('api_secret_env')}"
            )
        rest_config = ConfigurationRestAPI(
            api_key=api_key,
            api_secret=api_secret,
            base_path=binance_cfg.get("base_url") or DERIVATIVES_TRADING_USDS_FUTURES_REST_API_TESTNET_URL,
            timeout=int(binance_cfg.get("timeout_ms") or 10000),
            retries=int(binance_cfg.get("retries") or 3),
            backoff=int(binance_cfg.get("backoff_ms") or 1000),
        )
        self.client = DerivativesTradingUsdsFutures(config_rest_api=rest_config)
        self.rest = self.client.rest_api
        self.recv_window = int(binance_cfg.get("recv_window") or 5000)

    def exchange_info(self):
        return model_to_plain(self.rest.exchange_information().data())

    def account_info(self):
        return model_to_plain(self.rest.account_information_v3(recv_window=self.recv_window).data())

    def positions(self, symbol=None):
        return model_to_plain(self.rest.position_information_v3(symbol=symbol, recv_window=self.recv_window).data())

    def open_algo_orders(self, symbol=None):
        return model_to_plain(
            self.rest.current_all_algo_open_orders(
                algo_type="CONDITIONAL",
                symbol=symbol,
                recv_window=self.recv_window,
            ).data()
        )

    def ensure_one_way_mode(self):
        position_mode = model_to_plain(self.rest.get_current_position_mode(recv_window=self.recv_window).data())
        dual_side = position_mode.get("dualSidePosition")
        if dual_side in (False, "false", "FALSE", 0, "0"):
            return False
        self.rest.change_position_mode("false", recv_window=self.recv_window)
        return True

    def change_leverage(self, symbol, leverage):
        return model_to_plain(
            self.rest.change_initial_leverage(symbol, int(leverage), recv_window=self.recv_window).data()
        )

    def test_market_order(self, symbol, side, quantity):
        return model_to_plain(
            self.rest.test_order(
                symbol=symbol,
                side=side,
                type="MARKET",
                quantity=quantity,
                recv_window=self.recv_window,
            ).data()
        )

    def market_entry_short(self, symbol, quantity, client_order_id):
        response = self.rest.new_order(
            symbol=symbol,
            side="SELL",
            type="MARKET",
            quantity=quantity,
            new_client_order_id=client_order_id,
            new_order_resp_type="RESULT",
            recv_window=self.recv_window,
        )
        return model_to_plain(response.data())

    def market_close_short(self, symbol, quantity, client_order_id):
        response = self.rest.new_order(
            symbol=symbol,
            side="BUY",
            type="MARKET",
            quantity=quantity,
            reduce_only="true",
            new_client_order_id=client_order_id,
            new_order_resp_type="RESULT",
            recv_window=self.recv_window,
        )
        return model_to_plain(response.data())

    def place_stop_market_close(self, symbol, trigger_price, client_algo_id, working_type, price_protect):
        response = self.rest.new_algo_order(
            algo_type="CONDITIONAL",
            symbol=symbol,
            side="BUY",
            type="STOP_MARKET",
            trigger_price=trigger_price,
            working_type=working_type,
            close_position="true",
            price_protect="TRUE" if price_protect else "FALSE",
            client_algo_id=client_algo_id,
            recv_window=self.recv_window,
        )
        return model_to_plain(response.data())

    def place_take_profit_close(self, symbol, trigger_price, client_algo_id, working_type, price_protect):
        response = self.rest.new_algo_order(
            algo_type="CONDITIONAL",
            symbol=symbol,
            side="BUY",
            type="TAKE_PROFIT_MARKET",
            trigger_price=trigger_price,
            working_type=working_type,
            close_position="true",
            price_protect="TRUE" if price_protect else "FALSE",
            client_algo_id=client_algo_id,
            recv_window=self.recv_window,
        )
        return model_to_plain(response.data())

    def cancel_all_algo_orders(self, symbol):
        return model_to_plain(
            self.rest.cancel_all_algo_open_orders(symbol=symbol, recv_window=self.recv_window).data()
        )


def symbol_position_qty(short_positions, symbol):
    item = short_positions.get(symbol)
    if not item:
        return 0.0
    return abs(safe_float(item.get("positionAmt")) or 0.0)


def protection_client_id(symbol, suffix):
    return f"c-{suffix}-{symbol}-{uuid.uuid4().hex[:12]}"


def entry_client_id(symbol):
    return f"ce-{symbol}-{uuid.uuid4().hex[:12]}"


def close_client_id(symbol):
    return f"cc-{symbol}-{uuid.uuid4().hex[:12]}"


def abort_client_id(symbol):
    return f"ca-{symbol}-{uuid.uuid4().hex[:12]}"


def failclose_client_id(symbol):
    return f"cf-{symbol}-{uuid.uuid4().hex[:12]}"


def ensure_protection_orders(client, config, trade, symbol_info):
    stop_price = round_price_up(trade["structure"]["stop_price"], symbol_info)
    target_price = round_price_up(trade["structure"]["target_price"], symbol_info)
    stop_client_id = trade.get("protection", {}).get("stop", {}).get("client_algo_id") or protection_client_id(trade["symbol"], "stop")
    tp_client_id = trade.get("protection", {}).get("take_profit", {}).get("client_algo_id") or protection_client_id(trade["symbol"], "tp")
    working_type = config["binance"].get("working_type") or "MARK_PRICE"
    price_protect = bool(config["binance"].get("price_protect"))
    stop_resp = client.place_stop_market_close(
        trade["symbol"],
        stop_price,
        stop_client_id,
        working_type,
        price_protect,
    )
    tp_resp = client.place_take_profit_close(
        trade["symbol"],
        target_price,
        tp_client_id,
        working_type,
        price_protect,
    )
    trade["protection"] = {
        "stop": {
            "algo_id": stop_resp.get("algoId"),
            "client_algo_id": stop_resp.get("clientAlgoId") or stop_client_id,
            "trigger_price": stop_price,
            "order_type": stop_resp.get("orderType") or "STOP_MARKET",
        },
        "take_profit": {
            "algo_id": tp_resp.get("algoId"),
            "client_algo_id": tp_resp.get("clientAlgoId") or tp_client_id,
            "trigger_price": target_price,
            "order_type": tp_resp.get("orderType") or "TAKE_PROFIT_MARKET",
        },
    }


def close_trade_market(client, config, trade, short_positions, symbol_info, reason, snapshot_id):
    qty = round_qty_down(symbol_position_qty(short_positions, trade["symbol"]), symbol_info)
    if qty <= 0:
        if config["execution"].get("cancel_all_symbol_algo_orders_on_exit", True):
            client.cancel_all_algo_orders(trade["symbol"])
        create_journal_event(
            "trade_closed_without_market_exit",
            {
                "symbol": trade["symbol"],
                "reason": reason,
                "snapshot_id": snapshot_id,
            },
        )
        return {
            "symbol": trade["symbol"],
            "close_reason": reason,
            "snapshot_id": snapshot_id,
            "close_response": None,
        }
    if config["execution"].get("cancel_all_symbol_algo_orders_on_exit", True):
        client.cancel_all_algo_orders(trade["symbol"])
    close_resp = client.market_close_short(
        trade["symbol"],
        qty,
        close_client_id(trade["symbol"]),
    )
    create_journal_event(
        "trade_closed",
        {
            "symbol": trade["symbol"],
            "reason": reason,
            "snapshot_id": snapshot_id,
            "close_response": close_resp,
        },
    )
    return {
        "symbol": trade["symbol"],
        "close_reason": reason,
        "snapshot_id": snapshot_id,
        "close_response": close_resp,
    }


def active_protection_complete(open_algo_orders, trade):
    client_ids = {item.get("clientAlgoId") for item in open_algo_orders or []}
    stop_id = ((trade.get("protection") or {}).get("stop") or {}).get("client_algo_id")
    tp_id = ((trade.get("protection") or {}).get("take_profit") or {}).get("client_algo_id")
    return bool(stop_id and tp_id and stop_id in client_ids and tp_id in client_ids)


def manage_existing_trades(client, config, state, signal_map, short_positions, algo_orders_by_symbol, symbol_info_map, snapshot_id):
    closed = []
    orphan_symbols = sorted(set(short_positions) - set(state["active_trades"]))
    if orphan_symbols and config["strategy"].get("block_on_orphan_positions", True):
        create_journal_event(
            "orphan_positions_detected",
            {"symbols": orphan_symbols, "snapshot_id": snapshot_id},
        )
    for symbol, trade in list(state["active_trades"].items()):
        symbol_info = symbol_info_map.get(symbol)
        if not symbol_info:
            continue
        position = short_positions.get(symbol)
        algo_orders = algo_orders_by_symbol.get(symbol) or []
        if not position or abs(safe_float(position.get("positionAmt")) or 0.0) == 0:
            if algo_orders:
                client.cancel_all_algo_orders(symbol)
            closed.append(
                {
                    "symbol": symbol,
                    "close_reason": "exchange_flat_detected",
                    "snapshot_id": snapshot_id,
                    "close_response": None,
                }
            )
            create_journal_event(
                "trade_flattened_outside_local_state",
                {"symbol": symbol, "snapshot_id": snapshot_id},
            )
            state["active_trades"].pop(symbol, None)
            continue
        signal = signal_map.get(symbol)
        if config["strategy"].get("exit_on_signal_loss", True) and not (signal and signal.get("openable")):
            result = close_trade_market(
                client,
                config,
                trade,
                short_positions,
                symbol_info,
                "signal_lost",
                snapshot_id,
            )
            state["active_trades"].pop(symbol, None)
            closed.append(result)
            continue
        if config["strategy"].get("recreate_protection_if_missing", True) and not active_protection_complete(algo_orders, trade):
            if algo_orders:
                client.cancel_all_algo_orders(symbol)
            ensure_protection_orders(client, config, trade, symbol_info)
            create_journal_event(
                "protection_recreated",
                {
                    "symbol": symbol,
                    "snapshot_id": snapshot_id,
                    "protection": trade.get("protection"),
                },
            )
    return closed, orphan_symbols


def open_new_trades(
    client,
    config,
    state,
    candidates,
    short_positions,
    metrics,
    symbol_info_map,
    snapshot_id,
):
    opened = []
    failed = []
    active_symbols = set(state["active_trades"])
    leverage = safe_float(config["risk"].get("leverage")) or 1.0
    retry_shrink_pct = safe_float(config["execution"].get("entry_retry_shrink_pct")) or 97.0
    max_entry_retries = max(1, int(safe_float(config["execution"].get("max_entry_retries")) or 6))
    remaining_slots = max(0, int(config["strategy"].get("max_concurrent") or 0) - metrics["open_count"])
    remaining_gross = metrics["remaining_gross_usd"]
    for signal in candidates:
        if remaining_slots <= 0 or remaining_gross <= 0:
            break
        symbol = signal.get("perp_symbol")
        if not symbol or symbol in active_symbols or symbol in short_positions:
            continue
        symbol_info = symbol_info_map.get(symbol)
        if not symbol_info or symbol_info.get("status") != "TRADING":
            continue
        plan = compute_entry_plan(
            config,
            {
                **metrics,
                "open_count": metrics["open_count"] + len(opened),
                "remaining_gross_usd": remaining_gross,
            },
            signal,
            symbol_info,
        )
        if not plan["ok"]:
            continue
        try:
            if config["binance"].get("set_symbol_leverage", True):
                client.change_leverage(symbol, leverage)
            current_qty = plan["quantity"]
            current_notional_usd = plan["notional_usd"]
            entry_resp = None
            last_margin_error = None
            for attempt in range(max_entry_retries):
                try:
                    if config["execution"].get("validate_entry_with_test_order", True):
                        client.test_market_order(symbol, "SELL", current_qty)
                    entry_resp = client.market_entry_short(
                        symbol,
                        current_qty,
                        entry_client_id(symbol),
                    )
                    break
                except Exception as exc:
                    if not (is_margin_insufficient_error(exc) or is_max_quantity_error(exc)):
                        raise
                    last_margin_error = repr(exc)
                    if is_max_quantity_error(exc):
                        next_qty = round_qty_down(max_market_qty(symbol_info), symbol_info)
                        if next_qty >= current_qty:
                            next_qty = shrink_qty_down(current_qty, symbol_info, retry_shrink_pct)
                    else:
                        next_qty = shrink_qty_down(current_qty, symbol_info, retry_shrink_pct)
                    next_notional_usd = next_qty * plan["market_price"]
                    if (
                        attempt >= max_entry_retries - 1
                        or next_qty <= 0
                        or next_qty < plan["min_qty"]
                        or (plan.get("max_qty") and next_qty > plan["max_qty"])
                        or next_notional_usd < plan["min_notional_usd"]
                    ):
                        raise
                    create_journal_event(
                        "trade_entry_retry_shrunk",
                        {
                            "symbol": symbol,
                            "snapshot_id": snapshot_id,
                            "attempt": attempt + 1,
                            "error": last_margin_error,
                            "old_qty": current_qty,
                            "new_qty": next_qty,
                            "old_notional_usd": current_notional_usd,
                            "new_notional_usd": next_notional_usd,
                        },
                    )
                    current_qty = next_qty
                    current_notional_usd = next_notional_usd
            if not entry_resp:
                raise RuntimeError(last_margin_error or f"{symbol} 未能生成有效入场回报")
            executed_qty = safe_float(entry_resp.get("executedQty")) or safe_float(entry_resp.get("origQty")) or current_qty
            entry_price = safe_float(entry_resp.get("avgPrice")) or plan["market_price"]
            stop_price = round_price_up(signal["structure_stop_price"], symbol_info)
            risk_abs = stop_price - entry_price if entry_price is not None else None
            target_price = (entry_price - risk_abs) if entry_price is not None and risk_abs is not None else None
            if entry_price in (None, 0) or risk_abs is None or risk_abs <= 0 or target_price is None or target_price <= 0:
                abort_qty = round_qty_down(executed_qty, symbol_info) or plan["quantity"]
                client.market_close_short(
                    symbol,
                    abort_qty,
                    abort_client_id(symbol),
                )
                create_journal_event(
                    "entry_aborted_after_fill",
                    {
                        "symbol": symbol,
                        "snapshot_id": snapshot_id,
                        "entry_response": entry_resp,
                        "reason": "invalid_structure_after_fill",
                    },
                )
                failed.append(
                    {
                        "symbol": symbol,
                        "reason": "invalid_structure_after_fill",
                    }
                )
                continue
            trade = {
                "symbol": symbol,
                "strategy_id": config["strategy"]["strategy_id"],
                "snapshot_id": snapshot_id,
                "opened_at": now_utc_iso(),
                "signal_summary": signal.get("signal_summary"),
                "quality_score": signal.get("quality_score"),
                "entry": {
                    "order_id": entry_resp.get("orderId"),
                    "client_order_id": entry_resp.get("clientOrderId"),
                    "avg_price": entry_price,
                    "executed_qty": executed_qty,
                    "notional_usd": executed_qty * entry_price,
                    "response": entry_resp,
                },
                "structure": {
                    "stop_price": stop_price,
                    "target_price": target_price,
                    "stop_pct": ((stop_price / entry_price) - 1) * 100 if entry_price else None,
                    "front_high_price": safe_float(signal.get("front_high_price")),
                    "atr_1h_pct": safe_float(signal.get("atr_1h_pct")),
                },
                "protection": {},
            }
            try:
                ensure_protection_orders(client, config, trade, symbol_info)
            except Exception as protection_exc:
                close_resp = None
                close_error = None
                with contextlib.suppress(Exception):
                    client.cancel_all_algo_orders(symbol)
                try:
                    fail_close_qty = round_qty_down(executed_qty, symbol_info) or plan["quantity"]
                    close_resp = client.market_close_short(
                        symbol,
                        fail_close_qty,
                        failclose_client_id(symbol),
                    )
                except Exception as close_exc:
                    close_error = repr(close_exc)
                create_journal_event(
                    "protection_attach_failed_after_fill",
                    {
                        "symbol": symbol,
                        "snapshot_id": snapshot_id,
                        "entry_response": entry_resp,
                        "protection_error": repr(protection_exc),
                        "forced_close_response": close_resp,
                        "forced_close_error": close_error,
                    },
                )
                if close_error:
                    raise FatalTradeOpenError(
                        f"{symbol} 保护单挂载失败，且兜底市价平仓失败：{close_error}"
                    ) from protection_exc
                failed.append(
                    {
                        "symbol": symbol,
                        "reason": "protection_attach_failed_after_fill",
                    }
                )
                continue
        except FatalTradeOpenError as exc:
            create_journal_event(
                "trade_open_failed_fatal",
                {
                    "symbol": symbol,
                    "snapshot_id": snapshot_id,
                    "error": repr(exc),
                },
            )
            raise
        except Exception as exc:
            create_journal_event(
                "trade_open_failed",
                {
                    "symbol": symbol,
                    "snapshot_id": snapshot_id,
                    "error": repr(exc),
                },
            )
            failed.append({"symbol": symbol, "reason": repr(exc)})
            continue
        state["active_trades"][symbol] = trade
        active_symbols.add(symbol)
        remaining_slots -= 1
        remaining_gross = max(0.0, remaining_gross - (trade["entry"]["notional_usd"] or 0.0))
        opened.append(
            {
                "symbol": symbol,
                "entry_price": entry_price,
                "executed_qty": executed_qty,
                "stop_price": stop_price,
                "target_price": target_price,
                "notional_usd": trade["entry"]["notional_usd"],
                "protection": trade["protection"],
            }
        )
        create_journal_event(
            "trade_opened",
            {
                "symbol": symbol,
                "snapshot_id": snapshot_id,
                "entry": trade["entry"],
                "structure": trade["structure"],
                "protection": trade["protection"],
                "signal_summary": trade["signal_summary"],
            },
        )
    return opened, failed


def main():
    parser = argparse.ArgumentParser(description="Run C_overheat_fade live trader on Binance Futures testnet.")
    parser.add_argument("--config", default=str(DEFAULT_CONFIG_PATH), help="Path to trader config JSON.")
    parser.add_argument("--force", action="store_true", help="Ignore enabled=false and submit testnet orders.")
    parser.add_argument("--allow-symbol", help="Only allow one perp symbol for validation, e.g. BTCUSDT.")
    parser.add_argument("--only-one-trade", action="store_true", help="Validation mode: at most one concurrent trade.")
    parser.add_argument("--max-concurrent", type=int, help="Override strategy.max_concurrent for this run.")
    parser.add_argument("--stop-window-min-pct", type=float, help="Temporarily override structure stop min pct for validation only.")
    parser.add_argument("--stop-window-max-pct", type=float, help="Temporarily override structure stop max pct for validation only.")
    parser.add_argument("--reprocess-snapshot", action="store_true", help="Ignore last_processed_snapshot_id and process current snapshot again.")
    parser.add_argument("--candidate-preview-limit", type=int, default=5, help="How many top candidates to print in summary.")
    args = parser.parse_args()

    apply_signal_runtime_overrides(args)
    config = apply_runtime_overrides(load_config(Path(args.config).expanduser().resolve()), args)
    with file_lock(LOCK_PATH):
        state = load_state()
        manifest, rows = load_latest_snapshot()
        snapshot_id = manifest.get("latest_snapshot_id")
        candidates, signal_map = build_candidate_records(config, rows)
        runtime_stop_window_min_pct, runtime_stop_window_max_pct = resolve_runtime_stop_window(signal_map)

        summary = {
            "ok": True,
            "enabled": bool(config.get("enabled")),
            "snapshot_id": snapshot_id,
            "candidate_count": len(candidates),
            "candidate_preview": candidate_preview(candidates, args.candidate_preview_limit),
            "opened": [],
            "failed": [],
            "closed": [],
            "active_symbols": sorted((state.get("active_trades") or {}).keys()),
            "config_runtime": {
                "allow_symbols": list(config["strategy"].get("allow_symbols") or []),
                "max_concurrent": int(config["strategy"].get("max_concurrent") or 0),
                "structure_stop_window_min_pct": runtime_stop_window_min_pct,
                "structure_stop_window_max_pct": runtime_stop_window_max_pct,
                "reprocess_snapshot": bool(args.reprocess_snapshot),
            },
            "warnings": [],
        }

        if not (config.get("enabled") or args.force):
            summary["warnings"].append("enabled=false，仅输出候选，不提交测试网订单。")
            state["last_processed_snapshot_id"] = snapshot_id
            state["last_run_at"] = now_utc_iso()
            save_state(state)
            write_json(LATEST_PATH, build_live_trader_payload(config, state, snapshot_id, None, summary))
            print(json.dumps(summary, ensure_ascii=False, indent=2))
            return

        client = BinanceUsdsFuturesSdkClient(config)
        if config["binance"].get("ensure_one_way_mode", True):
            changed = client.ensure_one_way_mode()
            if changed:
                create_journal_event("position_mode_changed", {"mode": "ONE_WAY", "snapshot_id": snapshot_id})

        runtime = load_exchange_runtime(client, config)
        symbol_info_map = runtime["symbol_info_map"]

        closed, orphan_symbols = manage_existing_trades(
            client,
            config,
            state,
            signal_map,
            runtime["short_positions"],
            runtime["algo_orders_by_symbol"],
            symbol_info_map,
            snapshot_id,
        )
        summary["closed"] = closed
        runtime = load_exchange_runtime(client, config, symbol_info_map=symbol_info_map)
        metrics = runtime["metrics"]
        orphan_symbols = sorted(set(runtime["short_positions"]) - set(state["active_trades"]))
        if orphan_symbols and config["strategy"].get("block_on_orphan_positions", True):
            summary["warnings"].append(f"检测到交易所孤儿仓位：{','.join(orphan_symbols)}，本轮阻止新开仓。")
        else:
            should_process_snapshot = args.reprocess_snapshot or state.get("last_processed_snapshot_id") != snapshot_id
            if should_process_snapshot:
                summary["opened"], summary["failed"] = open_new_trades(
                    client,
                    config,
                    state,
                    candidates,
                    runtime["short_positions"],
                    metrics,
                    symbol_info_map,
                    snapshot_id,
                )
            else:
                summary["warnings"].append("snapshot_id 未变化，本轮只做对账与持仓管理。")

        state["last_processed_snapshot_id"] = snapshot_id
        state["last_run_at"] = now_utc_iso()
        save_state(state)

        runtime = load_exchange_runtime(client, config, symbol_info_map=symbol_info_map)
        metrics = runtime["metrics"]
        summary["active_symbols"] = sorted((state.get("active_trades") or {}).keys())
        summary["account"] = {
            "equity_usd": metrics["equity_usd"],
            "available_balance_usd": metrics["available_balance_usd"],
            "open_gross_usd": metrics["open_gross_usd"],
            "gross_cap_usd": metrics["gross_cap_usd"],
        }
        write_json(LATEST_PATH, build_live_trader_payload(config, state, snapshot_id, runtime, summary))
        print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(json.dumps({"ok": False, "error": repr(exc)}), file=sys.stderr)
        raise
