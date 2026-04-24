#!/usr/bin/env python3
import csv
import json
from collections import OrderedDict
from datetime import datetime
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import urlopen

from top15_short_strategy import (
    RECENT_OVERLAP_WINDOW_H,
    RISK_CONFIG,
    SHORT_STRATEGY_CONFIG,
    SHADOW_STRATEGY_LAYERS,
    STRUCTURE_CONFIG,
    STRUCTURE_STOP_MAX_PCT,
    STRUCTURE_STOP_MIN_PCT,
    build_shadow_strategy_signals,
    shadow_layer_label,
)

WORKDIR = Path(__file__).resolve().parents[1]
DATA_DIR = WORKDIR / "data" / "top15_tracker"
PAPER_TRADER_DIR = DATA_DIR / "paper_trader"
STATE_PATH = PAPER_TRADER_DIR / "state.json"
LATEST_PATH = PAPER_TRADER_DIR / "latest.json"
ORDERS_CSV_PATH = PAPER_TRADER_DIR / "orders.csv"
EQUITY_CURVE_CSV_PATH = PAPER_TRADER_DIR / "equity_curve.csv"
EVENTS_JSONL_PATH = PAPER_TRADER_DIR / "events.jsonl"
HISTORY_CSV_PATH = DATA_DIR / "history.csv"

BINANCE_SPOT_TICKER_URL = "https://api.binance.com/api/v3/ticker/24hr?symbol={symbol}"
BINANCE_FUTURES_TICKER_URL = "https://fapi.binance.com/fapi/v1/ticker/24hr?symbol={symbol}"

PAPER_TRADER_CONFIG = {
    "version": "server_paper_trader_v6_shadow_books_controls_live_launch",
    "initial_equity_usd": float(RISK_CONFIG.get("initial_equity_usd") or 10000.0),
    "risk_pct": float(RISK_CONFIG.get("risk_pct") or 5.0),
    "max_concurrent": int(RISK_CONFIG.get("max_concurrent") or 3),
    "max_gross_pct": float(RISK_CONFIG.get("max_gross_pct") or 200.0),
    "leverage": float(RISK_CONFIG.get("leverage") or 2.0),
    "max_hold_hours": float(STRUCTURE_CONFIG.get("max_hold_hours") or 12.0),
    "stop_window_min_pct": STRUCTURE_STOP_MIN_PCT,
    "stop_window_max_pct": STRUCTURE_STOP_MAX_PCT,
    "strategy_ids": list(SHADOW_STRATEGY_LAYERS.keys()),
}

RECENT_CLOSED_LIMIT = 24
RECENT_EVENT_LIMIT = 60
RECENT_CURVE_LIMIT = 144

ORDER_LOG_FIELDS = [
    "strategy_id",
    "strategy_code",
    "strategy_label",
    "order_id",
    "symbol",
    "name",
    "signal_name",
    "signal_tier",
    "open_snapshot_id",
    "close_snapshot_id",
    "entry_time",
    "close_time",
    "entry_price",
    "close_price",
    "size_usd",
    "risk_usd",
    "margin_usd",
    "leverage",
    "stop_price",
    "target_price",
    "stop_pct",
    "max_hold_hours",
    "open_reason",
    "close_reason",
    "close_reason_detail",
    "realized_pnl_pct",
    "realized_pnl_usd",
    "realized_r",
]

EQUITY_CURVE_FIELDS = [
    "strategy_id",
    "strategy_code",
    "strategy_label",
    "snapshot_id",
    "captured_at_utc",
    "captured_at_cst",
    "equity_usd",
    "realized_pnl_usd",
    "unrealized_pnl_usd",
    "open_count",
    "closed_count",
    "win_count",
    "loss_count",
    "open_gross_usd",
    "gross_cap_usd",
]


PAPER_TRADER_DIR.mkdir(parents=True, exist_ok=True)


def safe_float(value):
    try:
        num = float(value)
    except (TypeError, ValueError):
        return None
    return num if num == num else None


def get_current_price(row):
    return safe_float((row or {}).get("binance_last_price")) or safe_float((row or {}).get("price_usd"))


def parse_dt(value):
    if not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


def read_json(path: Path, default=None):
    if not path.exists():
        return default
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, payload):
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def append_csv_row(path: Path, fieldnames, row):
    path.parent.mkdir(parents=True, exist_ok=True)
    write_header = not path.exists()
    with path.open("a", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        if write_header:
            writer.writeheader()
        writer.writerow({key: row.get(key) for key in fieldnames})


def ensure_csv_file(path: Path, fieldnames):
    if path.exists():
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()


ensure_csv_file(ORDERS_CSV_PATH, ORDER_LOG_FIELDS)
ensure_csv_file(EQUITY_CURVE_CSV_PATH, EQUITY_CURVE_FIELDS)
EVENTS_JSONL_PATH.touch(exist_ok=True)


def build_strategy_book_configs():
    configs = OrderedDict()
    for strategy_id, layer in SHADOW_STRATEGY_LAYERS.items():
        configs[strategy_id] = {
            "strategy_id": strategy_id,
            "strategy_code": layer.get("code"),
            "strategy_label": shadow_layer_label(strategy_id),
            "description": layer.get("description"),
            "signal_name": layer.get("signal_name"),
            "entry_filters": list(layer.get("entry_filters") or []),
            "initial_equity_usd": safe_float(layer.get("initial_equity_usd")) or PAPER_TRADER_CONFIG["initial_equity_usd"],
            "risk_pct": safe_float(layer.get("risk_pct")) or PAPER_TRADER_CONFIG["risk_pct"],
            "max_concurrent": int(safe_float(layer.get("max_concurrent")) or PAPER_TRADER_CONFIG["max_concurrent"]),
            "max_gross_pct": safe_float(layer.get("max_gross_pct")) or PAPER_TRADER_CONFIG["max_gross_pct"],
            "leverage": safe_float(layer.get("leverage")) or PAPER_TRADER_CONFIG["leverage"],
            "max_hold_hours": safe_float(layer.get("max_hold_hours")) or PAPER_TRADER_CONFIG["max_hold_hours"],
            "stop_window_min_pct": safe_float(layer.get("stop_window_min_pct")) or PAPER_TRADER_CONFIG["stop_window_min_pct"],
            "stop_window_max_pct": safe_float(layer.get("stop_window_max_pct")) or PAPER_TRADER_CONFIG["stop_window_max_pct"],
            "target_r_multiple": safe_float(layer.get("target_r_multiple")) or 1.0,
        }
    return configs


STRATEGY_BOOK_CONFIGS = build_strategy_book_configs()


def default_book_state(strategy_id):
    config = STRATEGY_BOOK_CONFIGS[strategy_id]
    return {
        "strategy_id": strategy_id,
        "strategy_code": config["strategy_code"],
        "strategy_label": config["strategy_label"],
        "description": config["description"],
        "config": dict(config),
        "starting_equity_usd": config["initial_equity_usd"],
        "last_curve_snapshot_id": None,
        "realized_pnl_usd": 0.0,
        "total_closed_orders": 0,
        "win_count": 0,
        "loss_count": 0,
        "total_realized_r": 0.0,
        "entry_live": True,
        "entry_armed_snapshot_id": None,
        "entry_armed_at": None,
        "open_orders": [],
        "recent_closed_orders": [],
        "recent_events": [],
        "recent_equity_curve": [],
    }


def default_state():
    return {
        "version": PAPER_TRADER_CONFIG["version"],
        "config": dict(PAPER_TRADER_CONFIG),
        "last_processed_snapshot_id": None,
        "last_processed_at": None,
        "last_curve_snapshot_id": None,
        "recent_equity_curve": [],
        "watch_pool_rows": {},
        "strategy_books": OrderedDict((strategy_id, default_book_state(strategy_id)) for strategy_id in STRATEGY_BOOK_CONFIGS),
    }


def push_recent(collection, item, limit):
    return [item, *(collection or [])][:limit]


def normalize_book_state(raw_book, strategy_id):
    book = default_book_state(strategy_id)
    has_source = isinstance(raw_book, dict)
    if has_source:
        book.update(raw_book)
    config = dict(STRATEGY_BOOK_CONFIGS[strategy_id])
    book["strategy_id"] = strategy_id
    book["strategy_code"] = config["strategy_code"]
    book["strategy_label"] = config["strategy_label"]
    book["description"] = config["description"]
    book["config"] = config
    book["starting_equity_usd"] = safe_float(book.get("starting_equity_usd")) or config["initial_equity_usd"]
    if has_source:
        book["entry_live"] = bool(raw_book.get("entry_live")) if "entry_live" in raw_book else True
        book["entry_armed_snapshot_id"] = raw_book.get("entry_armed_snapshot_id") or book.get("entry_armed_snapshot_id")
        book["entry_armed_at"] = raw_book.get("entry_armed_at") or book.get("entry_armed_at")
    else:
        book["entry_live"] = True
        book["entry_armed_snapshot_id"] = None
        book["entry_armed_at"] = None
    book["open_orders"] = [dict(order) for order in book.get("open_orders") or []]
    book["recent_closed_orders"] = [dict(order) for order in book.get("recent_closed_orders") or []][:RECENT_CLOSED_LIMIT]
    book["recent_events"] = [dict(item) for item in book.get("recent_events") or []][:RECENT_EVENT_LIMIT]
    book["recent_equity_curve"] = [dict(item) for item in book.get("recent_equity_curve") or []][:RECENT_CURVE_LIMIT]
    return book


def extract_legacy_book(raw):
    fields = {
        "starting_equity_usd",
        "last_curve_snapshot_id",
        "realized_pnl_usd",
        "total_closed_orders",
        "win_count",
        "loss_count",
        "total_realized_r",
        "open_orders",
        "recent_closed_orders",
        "recent_events",
        "recent_equity_curve",
    }
    legacy = {key: raw.get(key) for key in fields if key in raw}
    return legacy if legacy else None


def load_state():
    raw = read_json(STATE_PATH, default=None)
    state = default_state()
    if not isinstance(raw, dict):
        return state

    state["last_processed_snapshot_id"] = raw.get("last_processed_snapshot_id")
    state["last_processed_at"] = raw.get("last_processed_at")
    state["last_curve_snapshot_id"] = raw.get("last_curve_snapshot_id")
    state["recent_equity_curve"] = [dict(item) for item in raw.get("recent_equity_curve") or []][:RECENT_CURVE_LIMIT]
    state["watch_pool_rows"] = {
        str(symbol): dict(row)
        for symbol, row in (raw.get("watch_pool_rows") or {}).items()
        if symbol and isinstance(row, dict)
    }

    raw_books = raw.get("strategy_books")
    legacy_book = None if isinstance(raw_books, dict) else extract_legacy_book(raw)
    for strategy_id in STRATEGY_BOOK_CONFIGS:
        source = None
        if isinstance(raw_books, dict):
            source = raw_books.get(strategy_id)
        elif strategy_id == "A_post_confirm_weak_turn":
            source = legacy_book
        book = normalize_book_state(source, strategy_id)
        if source is None and state.get("last_processed_snapshot_id"):
            book["entry_live"] = False
            book["entry_armed_snapshot_id"] = state.get("last_processed_snapshot_id")
            book["entry_armed_at"] = state.get("last_processed_at")
        state["strategy_books"][strategy_id] = book

    return state


def save_state(state):
    write_json(STATE_PATH, state)


def compute_book_metrics(book):
    open_orders = book.get("open_orders") or []
    unrealized_pnl_usd = sum(safe_float(order.get("unrealized_pnl_usd")) or 0 for order in open_orders)
    open_gross_usd = sum(safe_float(order.get("size_usd")) or 0 for order in open_orders)
    starting_equity = safe_float(book.get("starting_equity_usd")) or 0
    realized_pnl_usd = safe_float(book.get("realized_pnl_usd")) or 0
    equity_usd = starting_equity + realized_pnl_usd + unrealized_pnl_usd
    gross_cap_usd = equity_usd * (safe_float((book.get("config") or {}).get("max_gross_pct")) or 0) / 100
    return {
        "equity_usd": equity_usd,
        "realized_pnl_usd": realized_pnl_usd,
        "unrealized_pnl_usd": unrealized_pnl_usd,
        "open_gross_usd": open_gross_usd,
        "gross_cap_usd": gross_cap_usd,
        "remaining_gross_usd": max(0, gross_cap_usd - open_gross_usd),
        "open_count": len(open_orders),
        "closed_count": int(book.get("total_closed_orders") or 0),
        "win_count": int(book.get("win_count") or 0),
        "loss_count": int(book.get("loss_count") or 0),
        "total_realized_r": safe_float(book.get("total_realized_r")) or 0,
        "total_order_count": len(open_orders) + int(book.get("total_closed_orders") or 0),
    }


def load_curve_stats():
    stats = {}
    if not EQUITY_CURVE_CSV_PATH.exists():
        return stats

    with EQUITY_CURVE_CSV_PATH.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        for row in reader:
            strategy_id = row.get("strategy_id")
            equity_usd = safe_float(row.get("equity_usd"))
            if not strategy_id or equity_usd is None:
                continue

            item = stats.setdefault(
                strategy_id,
                {
                    "equity_peak_usd": None,
                    "max_drawdown_usd": 0.0,
                    "max_drawdown_pct": 0.0,
                    "last_equity_usd": None,
                    "equity_change_last_snapshot_usd": 0.0,
                    "equity_change_last_snapshot_pct": 0.0,
                    "curve_point_count": 0,
                },
            )

            peak = item["equity_peak_usd"]
            if peak is None or equity_usd > peak:
                peak = equity_usd
            item["equity_peak_usd"] = peak

            drawdown_usd = max(0.0, peak - equity_usd)
            drawdown_pct = (drawdown_usd / peak * 100.0) if peak else 0.0
            item["max_drawdown_usd"] = max(item["max_drawdown_usd"], drawdown_usd)
            item["max_drawdown_pct"] = max(item["max_drawdown_pct"], drawdown_pct)

            prev_equity = item["last_equity_usd"]
            if prev_equity not in (None, 0):
                item["equity_change_last_snapshot_usd"] = equity_usd - prev_equity
                item["equity_change_last_snapshot_pct"] = (equity_usd - prev_equity) / prev_equity * 100.0
            elif prev_equity == 0:
                item["equity_change_last_snapshot_usd"] = equity_usd
                item["equity_change_last_snapshot_pct"] = None
            else:
                item["equity_change_last_snapshot_usd"] = 0.0
                item["equity_change_last_snapshot_pct"] = 0.0

            item["last_equity_usd"] = equity_usd
            item["curve_point_count"] += 1

    return stats


def build_book_summary(book, curve_stats_by_strategy=None):
    metrics = compute_book_metrics(book)
    curve_stats = (curve_stats_by_strategy or {}).get(book.get("strategy_id")) or {}
    metrics["starting_equity_usd"] = safe_float(book.get("starting_equity_usd")) or 0
    metrics["win_rate"] = metrics["win_count"] / metrics["closed_count"] if metrics["closed_count"] else None
    metrics["equity_peak_usd"] = safe_float(curve_stats.get("equity_peak_usd"))
    metrics["max_drawdown_usd"] = safe_float(curve_stats.get("max_drawdown_usd")) or 0.0
    metrics["max_drawdown_pct"] = safe_float(curve_stats.get("max_drawdown_pct")) or 0.0
    metrics["equity_change_last_snapshot_usd"] = safe_float(curve_stats.get("equity_change_last_snapshot_usd")) or 0.0
    metrics["equity_change_last_snapshot_pct"] = safe_float(curve_stats.get("equity_change_last_snapshot_pct"))
    metrics["curve_point_count"] = int(curve_stats.get("curve_point_count") or 0)
    return metrics


def compute_aggregate_summary(strategy_books, curve_stats_by_strategy=None):
    summaries = [build_book_summary(book, curve_stats_by_strategy) for book in strategy_books.values()]
    closed_count = sum(summary["closed_count"] for summary in summaries)
    win_count = sum(summary["win_count"] for summary in summaries)
    curve_stats = (curve_stats_by_strategy or {}).get("aggregate") or {}
    return {
        "starting_equity_usd": sum(summary["starting_equity_usd"] for summary in summaries),
        "equity_usd": sum(summary["equity_usd"] for summary in summaries),
        "realized_pnl_usd": sum(summary["realized_pnl_usd"] for summary in summaries),
        "unrealized_pnl_usd": sum(summary["unrealized_pnl_usd"] for summary in summaries),
        "open_gross_usd": sum(summary["open_gross_usd"] for summary in summaries),
        "gross_cap_usd": sum(summary["gross_cap_usd"] for summary in summaries),
        "open_count": sum(summary["open_count"] for summary in summaries),
        "closed_count": closed_count,
        "win_count": win_count,
        "loss_count": sum(summary["loss_count"] for summary in summaries),
        "total_realized_r": sum(summary["total_realized_r"] for summary in summaries),
        "total_order_count": sum(summary["total_order_count"] for summary in summaries),
        "win_rate": (win_count / closed_count) if closed_count else None,
        "equity_peak_usd": safe_float(curve_stats.get("equity_peak_usd")),
        "max_drawdown_usd": safe_float(curve_stats.get("max_drawdown_usd")) or 0.0,
        "max_drawdown_pct": safe_float(curve_stats.get("max_drawdown_pct")) or 0.0,
        "equity_change_last_snapshot_usd": safe_float(curve_stats.get("equity_change_last_snapshot_usd")) or 0.0,
        "equity_change_last_snapshot_pct": safe_float(curve_stats.get("equity_change_last_snapshot_pct")),
        "curve_point_count": int(curve_stats.get("curve_point_count") or 0),
        "strategy_book_count": len(strategy_books),
    }


def compute_order_plan(book, metrics, signal):
    config = book.get("config") or {}
    available_slots = max(0, int(config.get("max_concurrent") or 0) - metrics["open_count"])
    stop_pct = safe_float(signal.get("structure_stop_pct"))
    risk_usd = metrics["equity_usd"] * (safe_float(config.get("risk_pct")) or 0) / 100
    risk_sized_notional_usd = risk_usd / (stop_pct / 100) if stop_pct not in (None, 0) else 0
    size_usd = max(0, min(risk_sized_notional_usd, metrics["remaining_gross_usd"]))
    leverage = safe_float(config.get("leverage")) or 0
    margin_usd = size_usd / leverage if leverage else size_usd
    return {
        "ok": available_slots > 0 and size_usd > 0 and stop_pct not in (None, 0),
        "available_slots": available_slots,
        "risk_usd": risk_usd,
        "risk_sized_notional_usd": risk_sized_notional_usd,
        "size_usd": size_usd,
        "margin_usd": margin_usd,
    }


def calc_short_pnl_pct(entry_price, exit_price):
    entry = safe_float(entry_price)
    exit = safe_float(exit_price)
    if entry in (None, 0) or exit is None:
        return None
    return ((entry - exit) / entry) * 100


def fetch_json(url):
    try:
        with urlopen(url, timeout=8) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except (HTTPError, URLError, TimeoutError, json.JSONDecodeError, ValueError):
        return None


def load_latest_history_rows(symbols):
    wanted = {str(symbol).upper() for symbol in symbols if symbol}
    if not wanted or not HISTORY_CSV_PATH.exists():
        return {}

    latest_rows = {}
    with HISTORY_CSV_PATH.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        for row in reader:
            symbol = str(row.get("symbol") or "").upper()
            if symbol in wanted:
                latest_rows[symbol] = dict(row)
    return latest_rows


def apply_spot_ticker_to_row(row, ticker):
    if not isinstance(ticker, dict) or ticker.get("symbol") != row.get("binance_pair"):
        return
    row["binance_status"] = "matched"
    last_price = safe_float(ticker.get("lastPrice"))
    change_pct = safe_float(ticker.get("priceChangePercent"))
    quote_volume = safe_float(ticker.get("quoteVolume"))
    trade_count = ticker.get("count")
    if last_price is not None:
        row["binance_last_price"] = last_price
    if change_pct is not None:
        row["binance_change_24h_pct"] = change_pct
    if quote_volume is not None:
        row["binance_quote_volume_usd"] = quote_volume
    if trade_count is not None:
        row["binance_trade_count_24h"] = trade_count


def apply_futures_ticker_to_row(row, ticker):
    if not isinstance(ticker, dict) or ticker.get("symbol") != row.get("binance_perp_symbol"):
        return
    row["binance_perp_status"] = "matched"
    last_price = safe_float(ticker.get("lastPrice"))
    change_pct = safe_float(ticker.get("priceChangePercent"))
    quote_volume = safe_float(ticker.get("quoteVolume"))
    trade_count = ticker.get("count")
    if last_price is not None:
        row["perp_last_price"] = last_price
    if change_pct is not None:
        row["perp_change_24h_pct"] = change_pct
    if quote_volume is not None:
        row["perp_quote_volume_24h"] = quote_volume
    if trade_count is not None:
        row["perp_trade_count_24h"] = trade_count


def refresh_watch_row_market(row):
    row = dict(row or {})
    spot_pair = row.get("binance_pair")
    perp_symbol = row.get("binance_perp_symbol")
    if spot_pair:
        apply_spot_ticker_to_row(row, fetch_json(BINANCE_SPOT_TICKER_URL.format(symbol=spot_pair)))
    if perp_symbol:
        apply_futures_ticker_to_row(row, fetch_json(BINANCE_FUTURES_TICKER_URL.format(symbol=perp_symbol)))
    return row


def collect_open_symbols(strategy_books):
    symbols = set()
    for book in (strategy_books or {}).values():
        for order in book.get("open_orders") or []:
            symbol = str(order.get("symbol") or "").upper()
            if symbol:
                symbols.add(symbol)
    return symbols


def build_watch_pool_rows(state, rows_by_symbol, snapshot_id, captured_at_utc, captured_at_cst):
    open_symbols = collect_open_symbols(state.get("strategy_books") or {})
    if not open_symbols:
        return {}

    cached_rows = {
        str(symbol).upper(): dict(row)
        for symbol, row in (state.get("watch_pool_rows") or {}).items()
        if symbol and isinstance(row, dict)
    }
    missing_symbols = sorted(symbol for symbol in open_symbols if symbol not in rows_by_symbol)
    if not missing_symbols:
        return {}

    history_rows = load_latest_history_rows(missing_symbols)
    watch_rows = {}
    for symbol in missing_symbols:
        seed = cached_rows.get(symbol) or history_rows.get(symbol)
        if not seed:
            continue
        row = refresh_watch_row_market(seed)
        row["symbol"] = symbol
        row["snapshot_id"] = snapshot_id
        row["captured_at_utc"] = captured_at_utc
        row["captured_at_cst"] = captured_at_cst
        row["paper_trader_watch_only"] = True
        watch_rows[symbol] = row
    return watch_rows


def refresh_watch_pool_cache(state, rows_by_symbol):
    next_watch_rows = {}
    open_symbols = collect_open_symbols(state.get("strategy_books") or {})
    for symbol in sorted(open_symbols):
        row = rows_by_symbol.get(symbol)
        if isinstance(row, dict):
            next_watch_rows[symbol] = dict(row)
    state["watch_pool_rows"] = next_watch_rows


def strategy_uses_holdable_exit(strategy_id):
    return str(strategy_id or "").endswith("_wide_hold")


def sort_overlap_score(signal):
    overlap_score = safe_float(signal.get("overlap_score"))
    if overlap_score is None:
        overlap_score = safe_float(((signal.get("row") or {}).get("overlap_score")))
    return overlap_score if overlap_score is not None else -999


def build_order_id(strategy_id, symbol, snapshot_id):
    stamp = snapshot_id or datetime.utcnow().strftime("%Y%m%dT%H%M%SZ")
    return f"auto-{strategy_id}-{symbol}-{stamp}"


def log_event(event):
    with EVENTS_JSONL_PATH.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(event, ensure_ascii=False) + "\n")


def make_event(event_type, strategy_id, symbol, name, tier, snapshot_id, captured_at_utc, detail):
    config = STRATEGY_BOOK_CONFIGS[strategy_id]
    event = {
        "id": f"{event_type}-{strategy_id}-{symbol}-{snapshot_id}",
        "type": event_type,
        "strategy_id": strategy_id,
        "strategy_code": config["strategy_code"],
        "strategy_label": config["strategy_label"],
        "symbol": symbol,
        "name": name,
        "tier": tier,
        "snapshot_id": snapshot_id,
        "captured_at_utc": captured_at_utc,
        "detail": detail,
        "created_at": datetime.utcnow().isoformat(),
    }
    log_event(event)
    return event


def close_order_record(order, exit_price, reason_code, reason_text, snapshot_id, captured_at_utc):
    realized_pnl_pct = calc_short_pnl_pct(order.get("entry_price"), exit_price)
    realized_pnl_usd = ((safe_float(order.get("size_usd")) or 0) * realized_pnl_pct / 100) if realized_pnl_pct is not None else None
    risk_usd = safe_float(order.get("risk_usd"))
    realized_r = (realized_pnl_usd / risk_usd) if risk_usd not in (None, 0) and realized_pnl_usd is not None else None
    return {
        **order,
        "status": "closed",
        "close_time": captured_at_utc,
        "close_snapshot_id": snapshot_id,
        "close_price": exit_price,
        "close_reason": reason_code,
        "close_reason_detail": reason_text,
        "realized_pnl_pct": realized_pnl_pct,
        "realized_pnl_usd": realized_pnl_usd,
        "realized_r": realized_r,
        "unrealized_pnl_pct": None,
        "unrealized_pnl_usd": None,
        "last_mark_price": exit_price,
    }


def evaluate_exit(order, row, layer_signal, mark_price, age_hours):
    target_r_multiple = safe_float(order.get("target_r_multiple")) or 1.0
    if row and mark_price is not None and safe_float(order.get("target_price")) is not None and mark_price <= order["target_price"]:
        return {"code": "tp", "detail": f"命中 {target_r_multiple:g}R 目标位 {order['target_price']}", "exit_price": order["target_price"]}
    if row and mark_price is not None and safe_float(order.get("stop_price")) is not None and mark_price >= order["stop_price"]:
        return {"code": "sl", "detail": f"命中结构止损 {order['stop_price']}", "exit_price": order["stop_price"]}
    if not row:
        return {
            "code": "left_universe",
            "detail": "币种已离开当前 TOP15 快照视野，按上一标记价结束自动单。",
            "exit_price": safe_float(order.get("last_mark_price")) or safe_float(order.get("entry_price")),
        }
    if mark_price is None:
        return None
    if layer_signal:
        if layer_signal.get("use_holdable_exit"):
            if not layer_signal.get("holdable", True):
                detail = "；".join(layer_signal.get("hold_blockers") or []) or "持仓条件失效，结束自动单。"
                return {
                    "code": layer_signal.get("hold_exit_code") or "hold_lost",
                    "detail": detail,
                    "exit_price": mark_price,
                }
        else:
            if not layer_signal.get("anchor_active"):
                if order.get("strategy_id") == "A_post_confirm_weak_turn":
                    detail = f"最近 {RECENT_OVERLAP_WINDOW_H:g}h 的确认锚点已失效，结束自动单。"
                else:
                    detail = "该层要求的交叉候选状态已失效，结束自动单。"
                return {"code": "anchor_lost", "detail": detail, "exit_price": mark_price}
            if not layer_signal.get("weakness_active"):
                return {"code": "weakness_rebound", "detail": "触发该层的转弱条件已失效，结束自动单。", "exit_price": mark_price}
            if layer_signal.get("requires_no_breakout_exit") and not layer_signal.get("breakout_guard"):
                return {"code": "breakout_resume", "detail": "1h 再次出现突破结构，结束自动单。", "exit_price": mark_price}
    if age_hours >= (safe_float(order.get("max_hold_hours")) or 0):
        return {
            "code": "timeout",
            "detail": f"达到最长持有 {order.get('max_hold_hours')}h，按当前标记价平仓。",
            "exit_price": mark_price,
        }
    return None


def combine_open_orders(strategy_books):
    out = []
    for book in strategy_books.values():
        out.extend(book.get("open_orders") or [])
    return sorted(out, key=lambda order: order.get("entry_time") or "", reverse=True)


def combine_recent_closed_orders(strategy_books):
    out = []
    for book in strategy_books.values():
        out.extend(book.get("recent_closed_orders") or [])
    return sorted(out, key=lambda order: order.get("close_time") or "", reverse=True)[:RECENT_CLOSED_LIMIT]


def combine_recent_events(strategy_books):
    out = []
    for book in strategy_books.values():
        out.extend(book.get("recent_events") or [])
    return sorted(out, key=lambda event: event.get("created_at") or "", reverse=True)[:RECENT_EVENT_LIMIT]


def build_strategy_books_payload(strategy_books, curve_stats_by_strategy=None):
    payload = OrderedDict()
    for strategy_id, book in strategy_books.items():
        payload[strategy_id] = {
            "strategy_id": strategy_id,
            "strategy_code": book.get("strategy_code"),
            "strategy_label": book.get("strategy_label"),
            "description": book.get("description"),
            "entry_live": bool(book.get("entry_live")),
            "entry_armed_snapshot_id": book.get("entry_armed_snapshot_id"),
            "entry_armed_at": book.get("entry_armed_at"),
            "config": dict(book.get("config") or {}),
            "summary": build_book_summary(book, curve_stats_by_strategy),
            "open_orders": list(book.get("open_orders") or []),
            "recent_closed_orders": list(book.get("recent_closed_orders") or []),
            "recent_events": list(book.get("recent_events") or []),
            "recent_equity_curve": list(book.get("recent_equity_curve") or []),
        }
    return payload


def write_latest_payload(state):
    strategy_books = state.get("strategy_books") or {}
    curve_stats_by_strategy = load_curve_stats()
    payload = {
        "ok": True,
        "version": state.get("version"),
        "config": state.get("config"),
        "last_processed_snapshot_id": state.get("last_processed_snapshot_id"),
        "last_processed_at": state.get("last_processed_at"),
        "summary": compute_aggregate_summary(strategy_books, curve_stats_by_strategy),
        "open_orders": combine_open_orders(strategy_books),
        "recent_closed_orders": combine_recent_closed_orders(strategy_books),
        "recent_events": combine_recent_events(strategy_books),
        "recent_equity_curve": state.get("recent_equity_curve") or [],
        "strategy_books": build_strategy_books_payload(strategy_books, curve_stats_by_strategy),
    }
    write_json(LATEST_PATH, payload)
    return payload


def append_order_log(order):
    append_csv_row(
        ORDERS_CSV_PATH,
        ORDER_LOG_FIELDS,
        {
            "strategy_id": order.get("strategy_id"),
            "strategy_code": order.get("strategy_code"),
            "strategy_label": order.get("strategy_label"),
            "order_id": order.get("id"),
            "symbol": order.get("symbol"),
            "name": order.get("name"),
            "signal_name": order.get("signal_name"),
            "signal_tier": order.get("signal_tier"),
            "open_snapshot_id": order.get("open_snapshot_id"),
            "close_snapshot_id": order.get("close_snapshot_id"),
            "entry_time": order.get("entry_time"),
            "close_time": order.get("close_time"),
            "entry_price": order.get("entry_price"),
            "close_price": order.get("close_price"),
            "size_usd": order.get("size_usd"),
            "risk_usd": order.get("risk_usd"),
            "margin_usd": order.get("margin_usd"),
            "leverage": order.get("leverage"),
            "stop_price": order.get("stop_price"),
            "target_price": order.get("target_price"),
            "stop_pct": order.get("stop_pct"),
            "max_hold_hours": order.get("max_hold_hours"),
            "open_reason": order.get("open_reason"),
            "close_reason": order.get("close_reason"),
            "close_reason_detail": order.get("close_reason_detail"),
            "realized_pnl_pct": order.get("realized_pnl_pct"),
            "realized_pnl_usd": order.get("realized_pnl_usd"),
            "realized_r": order.get("realized_r"),
        },
    )


def append_curve_row(strategy_id, strategy_code, strategy_label, snapshot_id, captured_at_utc, captured_at_cst, summary):
    row = {
        "strategy_id": strategy_id,
        "strategy_code": strategy_code,
        "strategy_label": strategy_label,
        "snapshot_id": snapshot_id,
        "captured_at_utc": captured_at_utc,
        "captured_at_cst": captured_at_cst,
        "equity_usd": summary["equity_usd"],
        "realized_pnl_usd": summary["realized_pnl_usd"],
        "unrealized_pnl_usd": summary["unrealized_pnl_usd"],
        "open_count": summary["open_count"],
        "closed_count": summary["closed_count"],
        "win_count": summary["win_count"],
        "loss_count": summary["loss_count"],
        "open_gross_usd": summary["open_gross_usd"],
        "gross_cap_usd": summary["gross_cap_usd"],
    }
    append_csv_row(EQUITY_CURVE_CSV_PATH, EQUITY_CURVE_FIELDS, row)
    return row


def process_book_snapshot(book, strategy_id, rows_by_symbol, watch_rows_by_symbol, signals_by_symbol, snapshot_id, captured_at_utc):
    closed_symbols = set()
    next_open_orders = []
    config = book.get("config") or {}

    for order in book.get("open_orders") or []:
        row = rows_by_symbol.get(order.get("symbol"))
        if row is None and strategy_uses_holdable_exit(strategy_id):
            row = watch_rows_by_symbol.get(order.get("symbol"))
        layer_signal = None
        if row and not row.get("paper_trader_watch_only"):
            layer_signal = (signals_by_symbol.get(order.get("symbol")) or {}).get(strategy_id)
        mark_price = get_current_price(row) if row else (safe_float(order.get("last_mark_price")) or safe_float(order.get("entry_price")))
        entry_dt = parse_dt(order.get("entry_time")) or parse_dt(captured_at_utc)
        current_dt = parse_dt(captured_at_utc)
        age_hours = (
            max(0.0, (current_dt - entry_dt).total_seconds() / 3600.0)
            if entry_dt and current_dt
            else safe_float(order.get("age_hours")) or 0.0
        )
        unrealized_pnl_pct = calc_short_pnl_pct(order.get("entry_price"), mark_price) if mark_price is not None else None
        unrealized_pnl_usd = (
            (safe_float(order.get("size_usd")) or 0) * unrealized_pnl_pct / 100
            if unrealized_pnl_pct is not None
            else None
        )
        next_order = {
            **order,
            "age_hours": age_hours,
            "last_mark_price": mark_price,
            "last_seen_snapshot_id": snapshot_id,
            "last_seen_at": captured_at_utc,
            "unrealized_pnl_pct": unrealized_pnl_pct,
            "unrealized_pnl_usd": unrealized_pnl_usd,
        }

        decision = evaluate_exit(next_order, row, layer_signal, mark_price, age_hours)
        if not decision:
            next_open_orders.append(next_order)
            continue

        closed_order = close_order_record(
            next_order,
            decision["exit_price"],
            decision["code"],
            decision["detail"],
            snapshot_id,
            captured_at_utc,
        )
        append_order_log(closed_order)
        book["realized_pnl_usd"] = (safe_float(book.get("realized_pnl_usd")) or 0) + (safe_float(closed_order.get("realized_pnl_usd")) or 0)
        book["total_closed_orders"] = int(book.get("total_closed_orders") or 0) + 1
        if (safe_float(closed_order.get("realized_pnl_usd")) or 0) >= 0:
            book["win_count"] = int(book.get("win_count") or 0) + 1
        else:
            book["loss_count"] = int(book.get("loss_count") or 0) + 1
        book["total_realized_r"] = (safe_float(book.get("total_realized_r")) or 0) + (safe_float(closed_order.get("realized_r")) or 0)
        book["recent_closed_orders"] = push_recent(book.get("recent_closed_orders"), closed_order, RECENT_CLOSED_LIMIT)
        event = make_event(
            "close",
            strategy_id,
            closed_order.get("symbol"),
            closed_order.get("name"),
            closed_order.get("signal_tier"),
            snapshot_id,
            captured_at_utc,
            closed_order.get("close_reason_detail"),
        )
        book["recent_events"] = push_recent(book.get("recent_events"), event, RECENT_EVENT_LIMIT)
        closed_symbols.add(closed_order.get("symbol"))

    book["open_orders"] = next_open_orders

    if not book.get("entry_live"):
        armed_snapshot_id = book.get("entry_armed_snapshot_id")
        if not armed_snapshot_id:
            book["entry_armed_snapshot_id"] = snapshot_id
            book["entry_armed_at"] = captured_at_utc
            return
        if armed_snapshot_id == snapshot_id:
            return
        book["entry_live"] = True

    candidates = []
    for symbol, signal_map in signals_by_symbol.items():
        layer_signal = signal_map.get(strategy_id)
        if not layer_signal or not layer_signal.get("openable"):
            continue
        if not layer_signal.get("current_price"):
            continue
        candidates.append(layer_signal)

    candidates.sort(
        key=lambda signal: (
            -(safe_float(signal.get("quality_score")) or 0),
            -sort_overlap_score(signal),
            safe_float(signal.get("structure_stop_pct")) or 999,
        )
    )

    for signal in candidates:
        row = signal.get("row") or {}
        if row.get("paper_trader_watch_only"):
            continue
        symbol = row.get("symbol")
        if not symbol or symbol in closed_symbols:
            continue
        if any(order.get("symbol") == symbol for order in book.get("open_orders") or []):
            continue

        metrics = compute_book_metrics(book)
        plan = compute_order_plan(book, metrics, signal)
        if not plan["ok"]:
            continue

        stop_pct = safe_float(signal.get("structure_stop_pct"))
        target_r_multiple = safe_float(signal.get("target_r_multiple")) or safe_float(config.get("target_r_multiple")) or 1.0
        order = {
            "id": build_order_id(strategy_id, symbol, snapshot_id),
            "strategy_id": strategy_id,
            "strategy_code": config.get("strategy_code"),
            "strategy_label": config.get("strategy_label"),
            "symbol": symbol,
            "name": row.get("name"),
            "status": "open",
            "signal_name": config.get("signal_name"),
            "signal_tier": signal.get("tier") if signal.get("tier") not in (None, "shadow") else config.get("strategy_code"),
            "entry_time": captured_at_utc,
            "open_snapshot_id": snapshot_id,
            "entry_price": signal.get("current_price"),
            "last_mark_price": signal.get("current_price"),
            "size_usd": plan["size_usd"],
            "risk_usd": plan["risk_usd"],
            "margin_usd": plan["margin_usd"],
            "leverage": config.get("leverage"),
            "stop_price": signal.get("structure_stop_price"),
            "target_price": signal.get("structure_target_price") or signal.get("structure_target_price_r1"),
            "target_r_multiple": target_r_multiple,
            "stop_pct": signal.get("structure_stop_pct"),
            "front_high_price": signal.get("front_high_price"),
            "atr_1h_pct": signal.get("atr_1h_pct"),
            "max_hold_hours": config.get("max_hold_hours"),
            "age_hours": 0.0,
            "signal_summary": signal.get("signal_summary"),
            "open_reason": (
                f"{config.get('strategy_label')} ｜ {signal.get('signal_summary')} ｜ "
                f"结构止损 {stop_pct:.4f}% ｜ 止盈 {target_r_multiple:g}R ｜ 风险预算 {config.get('risk_pct')}% ｜ "
                f"名义仓位 {plan['size_usd']:.2f} USD"
            ),
            "last_seen_snapshot_id": snapshot_id,
            "last_seen_at": captured_at_utc,
            "unrealized_pnl_pct": 0.0,
            "unrealized_pnl_usd": 0.0,
        }
        book["open_orders"] = [order, *(book.get("open_orders") or [])]
        event = make_event(
            "open",
            strategy_id,
            order.get("symbol"),
            order.get("name"),
            order.get("signal_tier"),
            snapshot_id,
            captured_at_utc,
            order.get("open_reason"),
        )
        book["recent_events"] = push_recent(book.get("recent_events"), event, RECENT_EVENT_LIMIT)


def process_snapshot(rows, snapshot_id, captured_at_utc, captured_at_cst):
    if not snapshot_id:
        return {"ok": False, "error": "missing_snapshot_id"}

    state = load_state()
    if state.get("last_processed_snapshot_id") == snapshot_id:
        payload = write_latest_payload(state)
        payload["noop"] = True
        return payload

    rows_by_symbol = {str(row.get("symbol")).upper(): row for row in rows if row.get("symbol")}
    watch_rows_by_symbol = build_watch_pool_rows(state, rows_by_symbol, snapshot_id, captured_at_utc, captured_at_cst)
    signals_by_symbol = {symbol: build_shadow_strategy_signals(row) for symbol, row in rows_by_symbol.items()}

    for strategy_id, book in state.get("strategy_books", {}).items():
        process_book_snapshot(book, strategy_id, rows_by_symbol, watch_rows_by_symbol, signals_by_symbol, snapshot_id, captured_at_utc)

    refresh_watch_pool_cache(state, rows_by_symbol)

    state["last_processed_snapshot_id"] = snapshot_id
    state["last_processed_at"] = captured_at_utc

    for strategy_id, book in state.get("strategy_books", {}).items():
        if book.get("last_curve_snapshot_id") == snapshot_id:
            continue
        summary = build_book_summary(book)
        curve_row = append_curve_row(
            strategy_id,
            book.get("strategy_code"),
            book.get("strategy_label"),
            snapshot_id,
            captured_at_utc,
            captured_at_cst,
            summary,
        )
        book["recent_equity_curve"] = [curve_row, *(book.get("recent_equity_curve") or [])][:RECENT_CURVE_LIMIT]
        book["last_curve_snapshot_id"] = snapshot_id

    if state.get("last_curve_snapshot_id") != snapshot_id:
        aggregate_summary = compute_aggregate_summary(state.get("strategy_books") or {})
        aggregate_curve_row = append_curve_row(
            "aggregate",
            "ALL",
            "多策略合计",
            snapshot_id,
            captured_at_utc,
            captured_at_cst,
            aggregate_summary,
        )
        state["recent_equity_curve"] = [aggregate_curve_row, *(state.get("recent_equity_curve") or [])][:RECENT_CURVE_LIMIT]
        state["last_curve_snapshot_id"] = snapshot_id

    save_state(state)
    return write_latest_payload(state)


def process_latest_snapshot():
    manifest = read_json(DATA_DIR / "latest" / "manifest.json", default={}) or {}
    rows = read_json(DATA_DIR / "latest" / "latest.json", default=[]) or []
    return process_snapshot(
        rows,
        manifest.get("latest_snapshot_id"),
        manifest.get("captured_at_utc"),
        manifest.get("captured_at_cst"),
    )


def main():
    payload = process_latest_snapshot()
    print(json.dumps(payload, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
