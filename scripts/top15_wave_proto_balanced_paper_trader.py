#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import fcntl
import json
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


WORKDIR = Path(__file__).resolve().parents[1]
DATA_DIR = WORKDIR / "data" / "top15_tracker" / "wave_paper_trader"
STATE_PATH = DATA_DIR / "state.json"
LATEST_PATH = DATA_DIR / "latest.json"
JOURNAL_PATH = DATA_DIR / "journal.jsonl"
CURVE_CSV_PATH = DATA_DIR / "equity_curve.csv"
ORDERS_CSV_PATH = DATA_DIR / "orders.csv"
LOCK_PATH = DATA_DIR / ".lock"
ARCHIVE_DIR = DATA_DIR / "archive"

LAB_DIR = WORKDIR / "projects" / "local-cpp-stop-lab"
if str(LAB_DIR) not in sys.path:
    sys.path.insert(0, str(LAB_DIR))

import run_wave_short_perp_context_loader as research_ctx
import run_wave_short_1h_oi_failure_swing_matrix as research_matrix
import run_wave_short_1h_oi_softscore_study as research_soft
import run_wave_short_1h_breakdown_continuation_study as research_bd
import run_wave_short_1h_retop_shelf_breakdown_study as research_shelf
import run_wave_short_1h_continuation_prototype_v1 as research_proto
import run_wave_short_1h_A_profit_expansion_matrix as research_exits


API_BASE_URL = "http://154.37.219.63/lana-api/api"
BINANCE_MARK_PRICE_URL = "https://fapi.binance.com/fapi/v1/premiumIndex?symbol={symbol}"
RUNNER_VERSION = "wave_proto_balanced_paper_trader_v1"

ENTRY_INTERVAL_MINUTES = 5
MANAGE_INTERVAL_MINUTES = 1
KLINE_1H_LIMIT = 240
OI_1H_LIMIT = 240
ENTRY_FRESHNESS_MINUTES = 80
MAX_WORKERS = 16
LEVERAGE = 5.0
MAX_GROSS_PCT = 500.0
MAX_CONCURRENT_PER_BOOK = 20
RECENT_EVENT_LIMIT = 120
RECENT_CLOSED_LIMIT = 120
RECENT_CURVE_LIMIT = 144
DATA_MISSING_HARD_MINUTES = 10
REQUEST_RETRIES = 3
REQUEST_RETRY_SLEEP_SECONDS = 1.0

BASE_ENTRY_PROFILE = next(x for x in research_matrix.ENTRY_PROFILES if x.profile_id == "entry_core")
BASE_STOP_PROFILE = next(x for x in research_matrix.STOP_PROFILES if x.profile_id == "stop_balanced")
BASE_EXIT_PROFILE = next(x for x in research_matrix.EXIT_PROFILES if x.profile_id == "exit_12h_tail")
BASE_VARIANT = research_bd.BASE_SIGNAL_VARIANT
CONT_EXIT_VARIANT = next(x for x in research_exits.EXIT_VARIANTS if x.variant_id == "profit_mode_4pct_lock20_55ema")
PROTO_BALANCED = next(x for x in research_proto.CONFIGS if x.config_id == "proto_balanced")

DATA_DIR.mkdir(parents=True, exist_ok=True)


@dataclass(frozen=True)
class StrategySpec:
    strategy_id: str
    strategy_code: str
    strategy_label: str
    risk_pct: float


STRATEGY_SPECS = [
    StrategySpec(
        strategy_id="wave_proto_balanced_risk_5",
        strategy_code="PB5",
        strategy_label="Proto Balanced / Risk 5%",
        risk_pct=5.0,
    ),
    StrategySpec(
        strategy_id="wave_proto_balanced_risk_7_5",
        strategy_code="PB7.5",
        strategy_label="Proto Balanced / Risk 7.5%",
        risk_pct=7.5,
    ),
    StrategySpec(
        strategy_id="wave_proto_balanced_risk_10",
        strategy_code="PB10",
        strategy_label="Proto Balanced / Risk 10%",
        risk_pct=10.0,
    ),
]


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def iso_utc(dt: datetime | None) -> str | None:
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).isoformat()


def ts_slug(dt: datetime | None = None) -> str:
    dt = dt or utc_now()
    return dt.astimezone(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def safe_float(value: Any) -> float | None:
    try:
        if value in (None, ""):
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def parse_dt(value: Any) -> datetime | None:
    if not value:
        return None
    if isinstance(value, datetime):
        return value
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except Exception:
        return None


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


def append_jsonl(path: Path, item: dict):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(item, ensure_ascii=False) + "\n")


def append_csv(path: Path, fieldnames: list[str], row: dict):
    path.parent.mkdir(parents=True, exist_ok=True)
    write_header = not path.exists()
    with path.open("a", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        if write_header:
            writer.writeheader()
        writer.writerow({k: row.get(k) for k in fieldnames})


def short_return_pct(entry_price, exit_price) -> float | None:
    entry_price = safe_float(entry_price)
    exit_price = safe_float(exit_price)
    if entry_price in (None, 0) or exit_price is None:
        return None
    return ((entry_price - exit_price) / entry_price) * 100.0


def request_json(url: str, timeout: int = 20, retries: int = REQUEST_RETRIES):
    req = Request(url, headers={"User-Agent": "top15-wave-proto-balanced-paper-trader/1.0"})
    last_exc = None
    for attempt in range(max(1, retries)):
        try:
            with urlopen(req, timeout=timeout) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except (HTTPError, URLError, TimeoutError, OSError, json.JSONDecodeError) as exc:
            last_exc = exc
            if attempt >= max(1, retries) - 1:
                break
            time.sleep(REQUEST_RETRY_SLEEP_SECONDS * (attempt + 1))
    if last_exc is not None:
        raise last_exc
    raise RuntimeError(f"request_json failed without exception: {url}")


def fetch_pool_items() -> list[dict]:
    payload = request_json(f"{API_BASE_URL}/pool")
    return payload.get("items") or []


def fetch_symbol_klines(symbol: str, limit: int = KLINE_1H_LIMIT):
    payload = request_json(f"{API_BASE_URL}/market/{symbol}/kline?interval=1h&limit={int(limit)}")
    items = payload.get("items") or []
    delta = research_ctx.interval_delta("1h")
    rows = []
    for item in items:
        if not isinstance(item, dict):
            continue
        open_dt = research_ctx.parse_dt(item.get("open_time"))
        if not open_dt:
            continue
        rows.append(
            research_ctx.Candle(
                symbol=symbol,
                interval="1h",
                open_dt=open_dt,
                close_dt=open_dt + delta,
                open_price=safe_float(item.get("open")) or 0.0,
                high_price=safe_float(item.get("high")) or 0.0,
                low_price=safe_float(item.get("low")) or 0.0,
                close_price=safe_float(item.get("close")) or 0.0,
                volume=safe_float(item.get("volume")),
                quote_volume=safe_float(item.get("quote_volume")),
                trades=safe_float(item.get("trades")),
            )
        )
    rows.sort(key=lambda x: x.close_dt)
    return rows


def fetch_symbol_oi(symbol: str, limit: int = OI_1H_LIMIT):
    payload = request_json(f"{API_BASE_URL}/market/{symbol}/oi?interval=1h&limit={int(limit)}")
    items = payload.get("items") or []
    rows = []
    for item in items:
        if not isinstance(item, dict):
            continue
        ts = research_ctx.parse_dt(item.get("ts"))
        if not ts:
            continue
        rows.append(
            research_ctx.OIRow(
                symbol=symbol,
                interval="1h",
                ts=ts,
                oi_qty=safe_float(item.get("sum_open_interest")),
                oi_value_usd=safe_float(item.get("sum_open_interest_value")),
            )
        )
    rows.sort(key=lambda x: x.ts)
    return rows


def fetch_mark_price(symbol: str) -> float | None:
    try:
        payload = request_json(BINANCE_MARK_PRICE_URL.format(symbol=symbol))
    except (HTTPError, URLError, TimeoutError, OSError):
        return None
    return safe_float(payload.get("markPrice"))


@contextmanager
def file_lock(path: Path):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w") as handle:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def strategy_book_template(spec: StrategySpec):
    return {
        "strategy_id": spec.strategy_id,
        "strategy_code": spec.strategy_code,
        "strategy_label": spec.strategy_label,
        "description": (
            "统一 continuation 原型 `proto_balanced` 的实时虚拟盘。"
            "底层逻辑为 `A 层 base failure swing + continuation(proto_balanced)`，"
            "当前版本只区分单笔风险档：5% / 7.5% / 10%。"
        ),
        "config": {
            "strategy_id": spec.strategy_id,
            "strategy_code": spec.strategy_code,
            "strategy_label": spec.strategy_label,
            "signal_name": "proto_balanced_combined",
            "entry_filters": [
                "base_core_cap_runup_oi_first",
                "continuation_proto_balanced",
                "profit_mode_4pct_lock20_55ema",
            ],
            "initial_equity_usd": 10000.0,
            "risk_pct": spec.risk_pct,
            "max_concurrent": MAX_CONCURRENT_PER_BOOK,
            "max_gross_pct": MAX_GROSS_PCT,
            "leverage": LEVERAGE,
            "entry_interval_minutes": ENTRY_INTERVAL_MINUTES,
            "manage_interval_minutes": MANAGE_INTERVAL_MINUTES,
        },
        "starting_equity_usd": 10000.0,
        "realized_pnl_usd": 0.0,
        "total_closed_orders": 0,
        "win_count": 0,
        "loss_count": 0,
        "total_realized_r": 0.0,
        "open_orders": [],
        "recent_closed_orders": [],
        "recent_events": [],
        "recent_equity_curve": [],
        "last_entry_run_at": None,
        "last_manage_run_at": None,
        "entry_dedup": {},
    }


def default_state():
    books = {spec.strategy_id: strategy_book_template(spec) for spec in STRATEGY_SPECS}
    return {
        "version": RUNNER_VERSION,
        "config": {
            "runner_version": RUNNER_VERSION,
            "entry_interval_minutes": ENTRY_INTERVAL_MINUTES,
            "manage_interval_minutes": MANAGE_INTERVAL_MINUTES,
            "leverage": LEVERAGE,
            "book_count": len(STRATEGY_SPECS),
            "strategy_ids": [spec.strategy_id for spec in STRATEGY_SPECS],
        },
        "last_processed_snapshot_id": None,
        "last_processed_at": None,
        "books": books,
    }


def archive_legacy_runtime_files(version_tag: str | None):
    archive_tag = version_tag or "unknown_version"
    archive_root = ARCHIVE_DIR / f"{ts_slug()}_{archive_tag}"
    archive_root.mkdir(parents=True, exist_ok=True)
    for path in [STATE_PATH, LATEST_PATH, JOURNAL_PATH, CURVE_CSV_PATH, ORDERS_CSV_PATH]:
        if not path.exists():
            continue
        target = archive_root / path.name
        path.rename(target)


def load_state():
    raw = read_json(STATE_PATH, default=None)
    if not isinstance(raw, dict):
        return default_state()
    if raw.get("version") != RUNNER_VERSION:
        archive_legacy_runtime_files(str(raw.get("version") or "legacy"))
        return default_state()
    state = default_state()
    raw_books = raw.get("books") or {}
    books = {}
    for spec in STRATEGY_SPECS:
        base_book = strategy_book_template(spec)
        book = {**base_book, **(raw_books.get(spec.strategy_id) or {})}
        book["config"] = {**base_book["config"], **(book.get("config") or {})}
        for key in ("risk_pct", "max_concurrent", "max_gross_pct", "leverage", "entry_interval_minutes", "manage_interval_minutes"):
            if book["config"].get(key) in (None, ""):
                book["config"][key] = base_book["config"].get(key)
        if safe_float(book["config"].get("max_gross_pct")) == 200.0:
            book["config"]["max_gross_pct"] = base_book["config"].get("max_gross_pct")
        book["open_orders"] = [dict(x) for x in (book.get("open_orders") or [])]
        book["recent_closed_orders"] = [dict(x) for x in (book.get("recent_closed_orders") or [])][:RECENT_CLOSED_LIMIT]
        book["recent_events"] = [dict(x) for x in (book.get("recent_events") or [])][:RECENT_EVENT_LIMIT]
        book["recent_equity_curve"] = [dict(x) for x in (book.get("recent_equity_curve") or [])][:RECENT_CURVE_LIMIT]
        book["entry_dedup"] = dict(book.get("entry_dedup") or {})
        books[spec.strategy_id] = book
    state.update({k: v for k, v in raw.items() if k not in {"books", "config", "version"}})
    state["books"] = books
    return state


def save_state(state):
    write_json(STATE_PATH, state)


def push_recent(items: list[dict], item: dict, limit: int):
    return [item, *(items or [])][:limit]


def compute_book_metrics(book: dict):
    open_orders = book.get("open_orders") or []
    unrealized_pnl_usd = sum(safe_float(order.get("unrealized_pnl_usd")) or 0.0 for order in open_orders)
    open_gross_usd = sum(safe_float(order.get("size_usd")) or 0.0 for order in open_orders)
    starting_equity = safe_float(book.get("starting_equity_usd")) or 0.0
    realized_pnl_usd = safe_float(book.get("realized_pnl_usd")) or 0.0
    equity_usd = starting_equity + realized_pnl_usd + unrealized_pnl_usd
    max_gross_pct = safe_float(((book.get("config") or {}).get("max_gross_pct"))) or MAX_GROSS_PCT
    closed_count = int(book.get("total_closed_orders") or 0)
    win_count = int(book.get("win_count") or 0)
    loss_count = int(book.get("loss_count") or 0)
    return {
        "starting_equity_usd": starting_equity,
        "equity_usd": equity_usd,
        "realized_pnl_usd": realized_pnl_usd,
        "unrealized_pnl_usd": unrealized_pnl_usd,
        "open_gross_usd": open_gross_usd,
        "gross_cap_usd": equity_usd * (max_gross_pct / 100.0),
        "open_count": len(open_orders),
        "closed_count": closed_count,
        "win_count": win_count,
        "loss_count": loss_count,
        "total_realized_r": safe_float(book.get("total_realized_r")) or 0.0,
        "total_order_count": len(open_orders) + closed_count,
        "win_rate": (win_count / closed_count) if closed_count else None,
    }


def compute_curve_stats(path: Path, strategy_id: str):
    stats = {
        "equity_peak_usd": None,
        "max_drawdown_usd": 0.0,
        "max_drawdown_pct": 0.0,
        "equity_change_last_snapshot_usd": 0.0,
        "equity_change_last_snapshot_pct": 0.0,
        "curve_point_count": 0,
        "recent_equity_curve": [],
    }
    if not path.exists():
        return stats
    rows = []
    with path.open("r", encoding="utf-8", newline="") as handle:
        for row in csv.DictReader(handle):
            if isinstance(row, dict) and (row.get("strategy_id") or "") == strategy_id:
                rows.append(row)
    if not rows:
        return stats
    prev_equity = None
    peak = None
    for row in rows:
        equity = safe_float(row.get("equity_usd"))
        if equity is None:
            continue
        if peak is None or equity > peak:
            peak = equity
        drawdown_usd = max(0.0, peak - equity)
        drawdown_pct = (drawdown_usd / peak * 100.0) if peak else 0.0
        stats["max_drawdown_usd"] = max(stats["max_drawdown_usd"], drawdown_usd)
        stats["max_drawdown_pct"] = max(stats["max_drawdown_pct"], drawdown_pct)
        if prev_equity not in (None, 0):
            stats["equity_change_last_snapshot_usd"] = equity - prev_equity
            stats["equity_change_last_snapshot_pct"] = ((equity - prev_equity) / prev_equity) * 100.0
        prev_equity = equity
        stats["curve_point_count"] += 1
    stats["equity_peak_usd"] = peak
    stats["recent_equity_curve"] = rows[-RECENT_CURVE_LIMIT:]
    return stats


def build_runtime_book_payload(book: dict):
    metrics = compute_book_metrics(book)
    curve_stats = compute_curve_stats(CURVE_CSV_PATH, book["strategy_id"])
    summary = {
        **metrics,
        "equity_peak_usd": curve_stats["equity_peak_usd"],
        "max_drawdown_usd": curve_stats["max_drawdown_usd"],
        "max_drawdown_pct": curve_stats["max_drawdown_pct"],
        "equity_change_last_snapshot_usd": curve_stats["equity_change_last_snapshot_usd"],
        "equity_change_last_snapshot_pct": curve_stats["equity_change_last_snapshot_pct"],
        "curve_point_count": curve_stats["curve_point_count"],
    }
    return {
        "strategy_id": book["strategy_id"],
        "strategy_code": book["strategy_code"],
        "strategy_label": book["strategy_label"],
        "description": book.get("description"),
        "entry_live": True,
        "entry_armed_snapshot_id": None,
        "entry_armed_at": None,
        "config": book.get("config") or {},
        "summary": summary,
        "open_orders": list(book.get("open_orders") or []),
        "recent_closed_orders": list(book.get("recent_closed_orders") or []),
        "recent_events": list(book.get("recent_events") or []),
        "recent_equity_curve": curve_stats["recent_equity_curve"],
    }


def aggregate_book_summaries(book_payloads: list[dict]):
    summaries = [p.get("summary") or {} for p in book_payloads]
    starting = sum(safe_float(s.get("starting_equity_usd")) or 0.0 for s in summaries)
    equity = sum(safe_float(s.get("equity_usd")) or 0.0 for s in summaries)
    realized = sum(safe_float(s.get("realized_pnl_usd")) or 0.0 for s in summaries)
    unrealized = sum(safe_float(s.get("unrealized_pnl_usd")) or 0.0 for s in summaries)
    open_gross = sum(safe_float(s.get("open_gross_usd")) or 0.0 for s in summaries)
    gross_cap = sum(safe_float(s.get("gross_cap_usd")) or 0.0 for s in summaries)
    open_count = sum(int(s.get("open_count") or 0) for s in summaries)
    closed_count = sum(int(s.get("closed_count") or 0) for s in summaries)
    win_count = sum(int(s.get("win_count") or 0) for s in summaries)
    loss_count = sum(int(s.get("loss_count") or 0) for s in summaries)
    total_realized_r = sum(safe_float(s.get("total_realized_r")) or 0.0 for s in summaries)
    order_count = sum(int(s.get("total_order_count") or 0) for s in summaries)
    curve_stats = compute_curve_stats(CURVE_CSV_PATH, "aggregate")
    return {
        "starting_equity_usd": starting,
        "equity_usd": equity,
        "realized_pnl_usd": realized,
        "unrealized_pnl_usd": unrealized,
        "open_gross_usd": open_gross,
        "gross_cap_usd": gross_cap,
        "open_count": open_count,
        "closed_count": closed_count,
        "win_count": win_count,
        "loss_count": loss_count,
        "total_realized_r": total_realized_r,
        "total_order_count": order_count,
        "win_rate": (win_count / closed_count) if closed_count else None,
        "equity_peak_usd": curve_stats["equity_peak_usd"],
        "max_drawdown_usd": curve_stats["max_drawdown_usd"],
        "max_drawdown_pct": curve_stats["max_drawdown_pct"],
        "equity_change_last_snapshot_usd": curve_stats["equity_change_last_snapshot_usd"],
        "equity_change_last_snapshot_pct": curve_stats["equity_change_last_snapshot_pct"],
        "curve_point_count": curve_stats["curve_point_count"],
    }


def append_curve_point(strategy_id: str, strategy_code: str, strategy_label: str, snapshot_id: str, summary: dict):
    append_csv(
        CURVE_CSV_PATH,
        [
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
        ],
        {
            "strategy_id": strategy_id,
            "strategy_code": strategy_code,
            "strategy_label": strategy_label,
            "snapshot_id": snapshot_id,
            "captured_at_utc": iso_utc(utc_now()),
            "captured_at_cst": iso_utc(utc_now().astimezone()),
            "equity_usd": summary.get("equity_usd"),
            "realized_pnl_usd": summary.get("realized_pnl_usd"),
            "unrealized_pnl_usd": summary.get("unrealized_pnl_usd"),
            "open_count": summary.get("open_count"),
            "closed_count": summary.get("closed_count"),
            "win_count": summary.get("win_count"),
            "loss_count": summary.get("loss_count"),
            "open_gross_usd": summary.get("open_gross_usd"),
            "gross_cap_usd": summary.get("gross_cap_usd"),
        },
    )


def append_order_log(order: dict):
    append_csv(
        ORDERS_CSV_PATH,
        [
            "strategy_id",
            "strategy_code",
            "strategy_label",
            "order_id",
            "symbol",
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
            "open_reason",
            "close_reason",
            "close_reason_detail",
            "realized_pnl_pct",
            "realized_pnl_usd",
            "realized_r",
            "entry_kind",
            "family_id",
        ],
        {
            "strategy_id": order.get("strategy_id"),
            "strategy_code": order.get("strategy_code"),
            "strategy_label": order.get("strategy_label"),
            "order_id": order.get("id"),
            "symbol": order.get("symbol"),
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
            "target_price": order.get("tp2_price"),
            "stop_pct": order.get("stop_pct"),
            "open_reason": order.get("open_reason"),
            "close_reason": order.get("close_reason"),
            "close_reason_detail": order.get("close_reason_detail"),
            "realized_pnl_pct": order.get("realized_pnl_pct"),
            "realized_pnl_usd": order.get("realized_pnl_usd"),
            "realized_r": order.get("realized_r"),
            "entry_kind": order.get("entry_kind"),
            "family_id": order.get("family_id"),
        },
    )


def make_event(event_type: str, symbol: str | None, snapshot_id: str, detail: dict):
    return {
        "id": f"{event_type}-{symbol or 'runner'}-{snapshot_id}-{ts_slug()}",
        "ts": iso_utc(utc_now()),
        "event_type": event_type,
        "symbol": symbol,
        "snapshot_id": snapshot_id,
        **detail,
    }


def resolve_position_size(equity_usd: float, stop_pct: float, risk_pct: float, max_gross_pct: float):
    if stop_pct in (None, 0):
        return None, None, None
    risk_usd = equity_usd * (risk_pct / 100.0)
    gross_cap_usd = equity_usd * (max_gross_pct / 100.0)
    size_usd = min(risk_usd / (stop_pct / 100.0), gross_cap_usd)
    margin_usd = size_usd / LEVERAGE if LEVERAGE else None
    return risk_usd, size_usd, margin_usd


def update_order_mark_stats(order: dict, mark_price: float):
    entry = safe_float(order.get("entry_price"))
    qty_remaining = safe_float(order.get("qty_remaining"))
    if entry in (None, 0) or qty_remaining is None:
        return
    order["last_mark_price"] = mark_price
    unrealized_pct = short_return_pct(entry, mark_price)
    order["unrealized_pnl_pct"] = unrealized_pct
    notional_remaining = qty_remaining * entry
    order["unrealized_pnl_usd"] = (notional_remaining * (unrealized_pct or 0.0) / 100.0) if unrealized_pct is not None else None
    best_path = safe_float(order.get("best_path_return_pct"))
    if unrealized_pct is not None:
        order["best_path_return_pct"] = unrealized_pct if best_path is None else max(best_path, unrealized_pct)


def order_age_hours(order: dict, now_dt: datetime | None = None):
    now_dt = now_dt or utc_now()
    entry_time = parse_dt(order.get("entry_time"))
    if not entry_time:
        return 0.0
    return max(0.0, (now_dt - entry_time).total_seconds() / 3600.0)


def maybe_take_partial(order: dict, mark_price: float):
    if order.get("tp1_taken"):
        return None
    tp1_price = safe_float(order.get("tp1_price"))
    if tp1_price is None or mark_price > tp1_price:
        return None
    qty_remaining = safe_float(order.get("qty_remaining"))
    qty_initial = safe_float(order.get("qty_initial"))
    tp1_ratio = safe_float(order.get("tp1_ratio"))
    entry = safe_float(order.get("entry_price"))
    if qty_remaining in (None, 0) or qty_initial in (None, 0) or tp1_ratio in (None, 0) or entry in (None, 0):
        return None
    qty_close = min(qty_remaining, qty_initial * tp1_ratio)
    pnl_pct = short_return_pct(entry, mark_price) or 0.0
    pnl_usd = qty_close * entry * pnl_pct / 100.0
    risk_usd = safe_float(order.get("risk_usd")) or 0.0
    realized_r = pnl_usd / risk_usd if risk_usd else 0.0
    order["tp1_taken"] = True
    order["qty_remaining"] = max(0.0, qty_remaining - qty_close)
    order["realized_pnl_usd"] = (safe_float(order.get("realized_pnl_usd")) or 0.0) + pnl_usd
    order["realized_r"] = (safe_float(order.get("realized_r")) or 0.0) + realized_r
    breakeven = safe_float(order.get("entry_price"))
    stop_price = safe_float(order.get("stop_price"))
    if breakeven is not None and stop_price is not None:
        order["stop_price_live"] = min(stop_price, breakeven)
    return {
        "qty_closed": qty_close,
        "pnl_usd": pnl_usd,
        "price": mark_price,
    }


def maybe_activate_profit_mode(order: dict):
    trigger = safe_float(order.get("profit_mode_trigger_pct"))
    if trigger is None or order.get("profit_mode_active"):
        return False
    best_path = safe_float(order.get("best_path_return_pct"))
    if best_path is None or best_path < trigger:
        return False
    lock_pct = safe_float(order.get("profit_mode_lock_pct"))
    entry = safe_float(order.get("entry_price"))
    if entry is None:
        return False
    order["profit_mode_active"] = True
    order["profit_mode_activated_at"] = iso_utc(utc_now())
    if lock_pct is not None:
        order["profit_lock_stop_price"] = entry * (1.0 - lock_pct / 100.0)
    return True


def strength_resume_signal(candles, ema_fast, ema_target, idx: int):
    if idx < 1:
        return False
    cur = candles[idx]
    prev = candles[idx - 1]
    cur_ema = ema_target[idx]
    prev_ema = ema_target[idx - 1]
    if cur_ema is None or prev_ema is None:
        return False
    return (
        cur.close_price > cur_ema
        and cur_ema >= prev_ema
        and cur.close_price > prev.close_price
        and ema_fast[idx] is not None
        and ema_fast[idx - 1] is not None
        and ema_fast[idx] >= ema_fast[idx - 1]
    )


def evaluate_resume_exit(order: dict, candles):
    closes = [c.close_price for c in candles]
    ema8 = research_ctx.compute_ema_series(candles, 8)
    idx = len(candles) - 1
    if idx < 2:
        return None
    hold_hours = order_age_hours(order)
    min_hold_hours = safe_float(order.get("min_hold_hours")) or 0.0
    if hold_hours < min_hold_hours:
        return None

    if order.get("profit_mode_active"):
        ma_period = int(order.get("profit_mode_resume_ma_period") or order.get("resume_ma_period") or 8)
        confirm_bars = int(order.get("profit_mode_resume_confirm_bars") or 2)
    else:
        ma_period = int(order.get("resume_ma_period") or 8)
        confirm_bars = int(order.get("resume_confirm_bars") or 2)

    if ma_period == 8:
        ema_target = ema8
    elif ma_period == 21:
        ema_target = research_ctx.compute_ema_series(candles, 21)
    elif ma_period == 55:
        ema_target = research_ctx.compute_ema_series(candles, 55)
    else:
        return None

    start = idx - confirm_bars + 1
    if start < 1:
        return None
    ok = all(strength_resume_signal(candles, ema8, ema_target, i) for i in range(start, idx + 1))
    if not ok:
        return None
    return "profit_mode_resume" if order.get("profit_mode_active") else "strength_resume"


def close_order(order: dict, exit_price: float, reason_code: str, snapshot_id: str):
    entry = safe_float(order.get("entry_price")) or 0.0
    qty_remaining = safe_float(order.get("qty_remaining")) or 0.0
    pnl_pct = short_return_pct(entry, exit_price) or 0.0
    pnl_usd = qty_remaining * entry * pnl_pct / 100.0
    realized_pnl_usd = (safe_float(order.get("realized_pnl_usd")) or 0.0) + pnl_usd
    risk_usd = safe_float(order.get("risk_usd")) or 0.0
    realized_r = (safe_float(order.get("realized_r")) or 0.0) + (pnl_usd / risk_usd if risk_usd else 0.0)
    size_usd = safe_float(order.get("size_usd")) or 0.0
    total_realized_pct = (realized_pnl_usd / size_usd * 100.0) if size_usd else None
    return {
        **order,
        "status": "closed",
        "close_snapshot_id": snapshot_id,
        "close_time": iso_utc(utc_now()),
        "close_price": exit_price,
        "close_reason": reason_code,
        "close_reason_detail": reason_code,
        "realized_pnl_pct": total_realized_pct,
        "realized_pnl_usd": realized_pnl_usd,
        "realized_r": realized_r,
        "qty_remaining": 0.0,
        "unrealized_pnl_usd": 0.0,
        "unrealized_pnl_pct": 0.0,
        "age_hours": order_age_hours(order),
    }


def fetch_state_for_symbol(item: dict):
    symbol = str(item.get("symbol") or "").upper().strip()
    if not symbol:
        return None, "missing_symbol"
    candles = fetch_symbol_klines(symbol)
    oi_rows = fetch_symbol_oi(symbol)
    if len(candles) < 200:
        return None, f"{symbol} 1h_kline_insufficient"
    if len(oi_rows) < 48:
        return None, f"{symbol} 1h_oi_insufficient"
    oi_aligned = research_ctx.align_oi_values(candles, oi_rows)
    if sum(1 for v in oi_aligned if v is not None) < 48:
        return None, f"{symbol} oi_align_insufficient"
    state = {
        "symbol": symbol,
        "meta": item,
        "1h": candles,
        "1h_close_times": [c.close_dt for c in candles],
        "ema8_1h": research_ctx.compute_ema_series(candles, 8),
        "ema21_1h": research_ctx.compute_ema_series(candles, 21),
        "ema55_1h": research_ctx.compute_ema_series(candles, 55),
        "oi_1h_rows": oi_rows,
        "oi_value_1h_aligned": oi_aligned,
    }
    state["snapshots"] = research_matrix.compute_state_snapshots(state)
    return state, None


def build_live_states(pool_items: list[dict], pool_limit: int | None = None):
    active = [x for x in pool_items if str(x.get("status") or "").lower() == "active"]
    if pool_limit:
        active = active[: max(0, int(pool_limit))]
    states = []
    warnings = []
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        futures = {executor.submit(fetch_state_for_symbol, item): item for item in active}
        for future in as_completed(futures):
            try:
                state, err = future.result()
            except Exception as exc:
                state, err = None, repr(exc)
            if state:
                states.append(state)
            elif err:
                warnings.append(str(err))
    states.sort(key=lambda x: x["symbol"])
    return states, warnings, active


def summarize_base_signal(item: dict):
    sig = item["signal"]
    return (
        f"A层 failure swing：runup24h {safe_float(sig.get('runup_24h_pct')) or 0.0:.2f}% ｜ "
        f"retrace {safe_float(sig.get('retrace_from_peak_pct')) or 0.0:.2f}% ｜ "
        f"oi12h {safe_float(sig.get('oi_12h_pct')) or 0.0:.2f}% ｜ stop {safe_float(sig.get('stop_pct')) or 0.0:.2f}%"
    )


def summarize_cont_signal(item: dict):
    sig = item["signal"]
    return (
        f"Continuation {item.get('family_id') or '--'}：impulse/pullback "
        f"{max(safe_float(sig.get('impulse_drop_pct')) or -999999.0, safe_float(sig.get('pullback_pct')) or -999999.0, safe_float(sig.get('rebound_pct')) or -999999.0):.2f}% ｜ "
        f"oi/vol {safe_float(sig.get('oi_to_vol_ratio')) or 0.0:.2f} ｜ stop {safe_float(sig.get('stop_pct')) or 0.0:.2f}%"
    )


def collect_recent_candidates(states, now_dt: datetime):
    raw_base, clusters, selected_base = research_soft.build_candidate_list(
        states,
        BASE_ENTRY_PROFILE,
        BASE_STOP_PROFILE,
        BASE_VARIANT,
    )
    base_trade_infos = research_bd.build_base_trade_infos(selected_base)
    cont_universe = research_proto.build_candidate_universe(base_trade_infos)
    selected_cont = research_proto.filter_candidates(cont_universe, PROTO_BALANCED)

    fresh_after = now_dt - timedelta(minutes=ENTRY_FRESHNESS_MINUTES)
    base_events = []
    for item in selected_base:
        entry_dt = item["signal"]["entry_dt"]
        if entry_dt >= fresh_after:
            base_events.append(
                {
                    "kind": "base",
                    "family_id": "base_failure_swing",
                    "state": item["state"],
                    "index": item["index"],
                    "signal": item["signal"],
                    "summary": summarize_base_signal(item),
                    "signal_key": f"base:{item['state']['symbol']}:{entry_dt.isoformat()}",
                    "entry_dt": entry_dt,
                }
            )

    cont_events = []
    for item in selected_cont:
        entry_dt = item["signal"]["entry_dt"]
        if entry_dt >= fresh_after:
            cont_events.append(
                {
                    "kind": "continuation",
                    "family_id": item.get("family_id") or "continuation",
                    "state": item["state"],
                    "index": item["index"],
                    "signal": item["signal"],
                    "summary": summarize_cont_signal(item),
                    "signal_key": f"cont:{item['family_id']}:{item['state']['symbol']}:{entry_dt.isoformat()}",
                    "entry_dt": entry_dt,
                }
            )

    events = sorted(
        [*base_events, *cont_events],
        key=lambda x: (x["entry_dt"], 0 if x["kind"] == "base" else 1, x["state"]["symbol"]),
    )
    diagnostics = {
        "base_selected_count": len(selected_base),
        "base_recent_count": len(base_events),
        "continuation_selected_count": len(selected_cont),
        "continuation_recent_count": len(cont_events),
        "raw_base_signal_count": len(raw_base),
        "base_cluster_count": len(clusters),
    }
    return events, diagnostics


def order_from_candidate(book: dict, candidate: dict, snapshot_id: str, now_dt: datetime):
    signal = candidate["signal"]
    entry_price = fetch_mark_price(candidate["state"]["symbol"]) or safe_float(signal.get("entry_price"))
    stop_pct = safe_float(signal.get("stop_pct"))
    config = book.get("config") or {}
    risk_pct = safe_float(config.get("risk_pct")) or 0.0
    max_gross_pct = safe_float(config.get("max_gross_pct")) or MAX_GROSS_PCT
    metrics = compute_book_metrics(book)
    risk_usd, size_usd, margin_usd = resolve_position_size(metrics["equity_usd"], stop_pct, risk_pct, max_gross_pct)
    if entry_price in (None, 0) or size_usd in (None, 0):
        return None
    qty = size_usd / entry_price if entry_price else None
    if qty in (None, 0):
        return None

    if candidate["kind"] == "base":
        exit_profile = BASE_EXIT_PROFILE
        profit_variant = None
    else:
        exit_profile = CONT_EXIT_VARIANT
        profit_variant = CONT_EXIT_VARIANT

    risk_abs = (safe_float(signal.get("stop_price")) or 0.0) - entry_price
    tp1_price = entry_price - risk_abs * exit_profile.tp1_r
    tp2_price = entry_price - risk_abs * exit_profile.tp2_r

    return {
        "id": f"{book['strategy_code']}-{candidate['state']['symbol']}-{snapshot_id}",
        "strategy_id": book["strategy_id"],
        "strategy_code": book["strategy_code"],
        "strategy_label": book["strategy_label"],
        "symbol": candidate["state"]["symbol"],
        "name": candidate["state"]["symbol"],
        "status": "open",
        "entry_kind": candidate["kind"],
        "family_id": candidate["family_id"],
        "open_snapshot_id": snapshot_id,
        "entry_time": iso_utc(now_dt),
        "entry_signal_time": iso_utc(candidate["entry_dt"]),
        "entry_price": entry_price,
        "size_usd": size_usd,
        "risk_usd": risk_usd,
        "margin_usd": margin_usd,
        "leverage": LEVERAGE,
        "qty_initial": qty,
        "qty_remaining": qty,
        "stop_price": safe_float(signal.get("stop_price")),
        "stop_price_live": safe_float(signal.get("stop_price")),
        "tp1_price": tp1_price,
        "tp2_price": tp2_price,
        "tp1_ratio": exit_profile.tp1_ratio,
        "stop_pct": stop_pct,
        "target_r_multiple": exit_profile.tp2_r,
        "open_reason": candidate["summary"],
        "signal_summary": candidate["summary"],
        "close_reason": None,
        "close_reason_detail": None,
        "realized_pnl_usd": 0.0,
        "realized_r": 0.0,
        "tp1_taken": False,
        "profit_mode_active": False,
        "profit_mode_activated_at": None,
        "profit_lock_stop_price": None,
        "profit_mode_trigger_pct": safe_float(getattr(profit_variant, "profit_mode_trigger_pct", None)) if profit_variant else None,
        "profit_mode_lock_pct": safe_float(getattr(profit_variant, "profit_mode_lock_pct", None)) if profit_variant else None,
        "profit_mode_resume_ma_period": int(getattr(profit_variant, "profit_mode_resume_ma_period", 0) or 0) if profit_variant else None,
        "profit_mode_resume_confirm_bars": int(getattr(profit_variant, "profit_mode_resume_confirm_bars", 0) or 0) if profit_variant else None,
        "min_hold_hours": exit_profile.min_hold_hours,
        "max_hold_hours": exit_profile.max_hold_hours,
        "resume_ma_period": exit_profile.resume_ma_period,
        "resume_confirm_bars": exit_profile.resume_confirm_bars,
        "best_path_return_pct": 0.0,
        "unrealized_pnl_usd": 0.0,
        "unrealized_pnl_pct": 0.0,
        "last_mark_price": entry_price,
        "last_seen_at": iso_utc(now_dt),
        "last_price_missing_count": 0,
        "signal_key": candidate["signal_key"],
        "signal": {
            **signal,
            "entry_dt": iso_utc(candidate["entry_dt"]),
        },
    }


def write_latest_payload(
    state: dict,
    warnings: list[str] | None = None,
    runtime_extra: dict | None = None,
    ok: bool = True,
):
    warnings = warnings or []
    runtime_extra = runtime_extra or {}
    book_payloads = [build_runtime_book_payload(book) for book in state["books"].values()]
    summary = aggregate_book_summaries(book_payloads)
    payload = {
        "ok": ok,
        "version": RUNNER_VERSION,
        "config": state.get("config") or {},
        "last_processed_snapshot_id": state.get("last_processed_snapshot_id"),
        "last_processed_at": state.get("last_processed_at"),
        "summary": {
            **summary,
            "strategy_book_count": len(book_payloads),
        },
        "open_orders": [],
        "recent_closed_orders": [],
        "recent_events": [],
        "recent_equity_curve": compute_curve_stats(CURVE_CSV_PATH, "aggregate")["recent_equity_curve"],
        "strategy_books": {book["strategy_id"]: book for book in book_payloads},
        "runtime": {
            "warnings": warnings,
            **runtime_extra,
        },
    }
    write_json(LATEST_PATH, payload)
    return payload


def process_entry_run(state: dict, pool_limit: int | None = None):
    now_dt = utc_now()
    snapshot_id = ts_slug(now_dt)
    warnings = []
    try:
        pool_items = fetch_pool_items()
    except Exception as exc:
        warnings.append(f"pool_fetch_failed: {exc!r}")
        payload = write_latest_payload(state, warnings=warnings, ok=False)
        return payload

    states, fetch_warnings, active_items = build_live_states(pool_items, pool_limit=pool_limit)
    warnings.extend(fetch_warnings[:80])
    events, diagnostics = collect_recent_candidates(states, now_dt)

    opened = []
    preview_rows = []
    for event in events:
        preview_rows.append(
            {
                "symbol": event["state"]["symbol"],
                "kind": event["kind"],
                "family_id": event["family_id"],
                "decision": "candidate_ready",
                "summary": event["summary"],
                "stop_pct": safe_float(event["signal"].get("stop_pct")),
                "blockers": [],
                "opened_books": [],
            }
        )

    preview_by_key = {event["signal_key"]: row for event, row in zip(events, preview_rows)}

    for spec in STRATEGY_SPECS:
        book = state["books"][spec.strategy_id]
        open_symbols = {str(x.get("symbol") or "").upper() for x in (book.get("open_orders") or [])}
        for event in events:
            row = preview_by_key[event["signal_key"]]
            if len(book.get("open_orders") or []) >= MAX_CONCURRENT_PER_BOOK:
                if not row["blockers"]:
                    row["blockers"].append("已达到单账本最大并发")
                continue
            if event["state"]["symbol"] in open_symbols:
                continue
            if book["entry_dedup"].get(event["signal_key"]):
                continue
            order = order_from_candidate(book, event, snapshot_id, now_dt)
            if not order:
                if not row["blockers"]:
                    row["blockers"].append("仓位计算失败")
                continue
            book["open_orders"] = [order, *(book.get("open_orders") or [])]
            book["entry_dedup"][event["signal_key"]] = snapshot_id
            event_row = make_event(
                "trade_opened",
                order["symbol"],
                snapshot_id,
                {
                    "strategy_id": spec.strategy_id,
                    "entry_kind": order["entry_kind"],
                    "family_id": order["family_id"],
                    "signal_summary": order["signal_summary"],
                    "entry_price": order["entry_price"],
                },
            )
            book["recent_events"] = push_recent(book["recent_events"], event_row, RECENT_EVENT_LIMIT)
            append_jsonl(JOURNAL_PATH, event_row)
            opened.append(
                {
                    "strategy_id": spec.strategy_id,
                    "symbol": order["symbol"],
                    "entry_kind": order["entry_kind"],
                    "entry_price": order["entry_price"],
                    "stop_price": order["stop_price"],
                }
            )
            row["opened_books"].append(spec.strategy_id)
            row["decision"] = "opened"
            open_symbols.add(order["symbol"])
        book["last_entry_run_at"] = iso_utc(now_dt)

    state["last_processed_snapshot_id"] = snapshot_id
    state["last_processed_at"] = iso_utc(now_dt)

    for book in state["books"].values():
        append_curve_point(book["strategy_id"], book["strategy_code"], book["strategy_label"], snapshot_id, compute_book_metrics(book))
    aggregate_summary = aggregate_book_summaries([build_runtime_book_payload(book) for book in state["books"].values()])
    append_curve_point("aggregate", "AGG", "Wave Proto Balanced Aggregate", snapshot_id, aggregate_summary)

    save_state(state)
    preview_rows.sort(key=lambda x: (0 if x.get("opened_books") else 1, str(x.get("symbol") or "")))
    payload = write_latest_payload(
        state,
        warnings=warnings,
        runtime_extra={
            "opened": opened,
            "closed": [],
            "failed": [],
            "mode": "entry_5m",
            "candidate_count": len(events),
            "candidate_preview": preview_rows[:10],
            **diagnostics,
        },
    )
    return payload


def process_manage_run(state: dict):
    now_dt = utc_now()
    snapshot_id = ts_slug(now_dt)
    warnings = []
    mark_cache: dict[str, float | None] = {}
    kline_cache: dict[str, list[Any]] = {}
    closed_orders = []

    for book in state["books"].values():
        next_open_orders = []
        for order in book.get("open_orders") or []:
            symbol = str(order.get("symbol") or "").upper()
            if symbol not in mark_cache:
                mark_cache[symbol] = fetch_mark_price(symbol)
            mark_price = mark_cache[symbol]
            if mark_price is None:
                order["last_price_missing_count"] = int(order.get("last_price_missing_count") or 0) + 1
                if order["last_price_missing_count"] >= DATA_MISSING_HARD_MINUTES:
                    warnings.append(f"{symbol} 连续 {order['last_price_missing_count']} 分钟无最新价格。")
                next_open_orders.append(order)
                continue

            order["last_price_missing_count"] = 0
            order["last_seen_at"] = iso_utc(now_dt)
            update_order_mark_stats(order, mark_price)

            partial = maybe_take_partial(order, mark_price)
            if partial:
                event = make_event(
                    "tp1_partial",
                    symbol,
                    snapshot_id,
                    {
                        "strategy_id": order.get("strategy_id"),
                        "price": partial["price"],
                        "qty_closed": partial["qty_closed"],
                        "pnl_usd": partial["pnl_usd"],
                        "signal_summary": order.get("signal_summary"),
                    },
                )
                book["recent_events"] = push_recent(book["recent_events"], event, RECENT_EVENT_LIMIT)
                append_jsonl(JOURNAL_PATH, event)

            if maybe_activate_profit_mode(order):
                event = make_event(
                    "profit_mode_activated",
                    symbol,
                    snapshot_id,
                    {
                        "strategy_id": order.get("strategy_id"),
                        "signal_summary": order.get("signal_summary"),
                    },
                )
                book["recent_events"] = push_recent(book["recent_events"], event, RECENT_EVENT_LIMIT)
                append_jsonl(JOURNAL_PATH, event)

            stop_price = safe_float(order.get("profit_lock_stop_price")) if order.get("profit_mode_active") else None
            if stop_price is None:
                stop_price = safe_float(order.get("stop_price_live")) or safe_float(order.get("stop_price"))
            closed = None
            if stop_price is not None and mark_price >= stop_price:
                reason = "profit_lock_stop" if order.get("profit_mode_active") else ("stop_after_tp1" if order.get("tp1_taken") else "stop_loss")
                closed = close_order(order, stop_price, reason, snapshot_id)
            else:
                tp2_price = safe_float(order.get("tp2_price"))
                if tp2_price is not None and mark_price <= tp2_price:
                    closed = close_order(order, tp2_price, "take_profit_tail", snapshot_id)
                elif order_age_hours(order, now_dt) >= (safe_float(order.get("max_hold_hours")) or 0.0):
                    reason = "timeout_after_tp1" if order.get("tp1_taken") else "timeout"
                    closed = close_order(order, mark_price, reason, snapshot_id)

            if closed is None:
                if symbol not in kline_cache:
                    try:
                        kline_cache[symbol] = fetch_symbol_klines(symbol)
                    except Exception as exc:
                        warnings.append(f"{symbol} manage_kline_fetch_failed: {exc!r}")
                        next_open_orders.append(order)
                        continue
                resume_reason = evaluate_resume_exit(order, kline_cache[symbol])
                if resume_reason:
                    if order.get("tp1_taken") and resume_reason == "strength_resume":
                        resume_reason = "strength_resume_after_tp1"
                    if order.get("tp1_taken") and resume_reason == "profit_mode_resume":
                        resume_reason = "profit_mode_resume_after_tp1"
                    closed = close_order(order, mark_price, resume_reason, snapshot_id)

            if closed is None:
                order["age_hours"] = order_age_hours(order, now_dt)
                next_open_orders.append(order)
                continue

            book["realized_pnl_usd"] = (safe_float(book.get("realized_pnl_usd")) or 0.0) + (safe_float(closed.get("realized_pnl_usd")) or 0.0)
            book["total_closed_orders"] = int(book.get("total_closed_orders") or 0) + 1
            book["total_realized_r"] = (safe_float(book.get("total_realized_r")) or 0.0) + (safe_float(closed.get("realized_r")) or 0.0)
            if (safe_float(closed.get("realized_pnl_usd")) or 0.0) >= 0:
                book["win_count"] = int(book.get("win_count") or 0) + 1
            else:
                book["loss_count"] = int(book.get("loss_count") or 0) + 1
            book["recent_closed_orders"] = push_recent(book["recent_closed_orders"], closed, RECENT_CLOSED_LIMIT)
            event = make_event(
                "trade_closed",
                symbol,
                snapshot_id,
                {
                    "strategy_id": closed.get("strategy_id"),
                    "reason": closed.get("close_reason"),
                    "signal_summary": order.get("signal_summary"),
                    "close_price": closed.get("close_price"),
                },
            )
            book["recent_events"] = push_recent(book["recent_events"], event, RECENT_EVENT_LIMIT)
            append_jsonl(JOURNAL_PATH, event)
            append_order_log(closed)
            closed_orders.append(
                {
                    "strategy_id": closed.get("strategy_id"),
                    "symbol": symbol,
                    "reason": closed.get("close_reason"),
                    "close_price": closed.get("close_price"),
                }
            )

        book["open_orders"] = next_open_orders
        book["last_manage_run_at"] = iso_utc(now_dt)

    state["last_processed_snapshot_id"] = snapshot_id
    state["last_processed_at"] = iso_utc(now_dt)
    for book in state["books"].values():
        append_curve_point(book["strategy_id"], book["strategy_code"], book["strategy_label"], snapshot_id, compute_book_metrics(book))
    aggregate_summary = aggregate_book_summaries([build_runtime_book_payload(book) for book in state["books"].values()])
    append_curve_point("aggregate", "AGG", "Wave Proto Balanced Aggregate", snapshot_id, aggregate_summary)
    save_state(state)
    return write_latest_payload(
        state,
        warnings=warnings,
        runtime_extra={
            "opened": [],
            "closed": closed_orders,
            "failed": [],
            "mode": "manage_1m",
            "candidate_count": 0,
            "candidate_preview": [],
        },
    )


def main():
    parser = argparse.ArgumentParser(description="Proto balanced wave paper trader using Lana API + Binance mark price")
    parser.add_argument("--mode", choices=["entry_5m", "manage_1m"], required=True)
    parser.add_argument("--pool-limit", type=int, default=None)
    args = parser.parse_args()

    with file_lock(LOCK_PATH):
        state = load_state()
        if args.mode == "entry_5m":
            payload = process_entry_run(state, pool_limit=args.pool_limit)
        else:
            payload = process_manage_run(state)
        print(json.dumps(payload, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
