#!/usr/bin/env python3
import csv
import json
import math
import re
import sys
import urllib.request
from urllib.parse import urlencode
from datetime import datetime, timezone, timedelta
from pathlib import Path

from top15_short_strategy import RECENT_OVERLAP_WINDOW_H, compute_short_setup_fields

try:
    from top15_paper_trader import (
        EQUITY_CURVE_CSV_PATH as PAPER_TRADER_EQUITY_CURVE_CSV_PATH,
        LATEST_PATH as PAPER_TRADER_LATEST_PATH,
        ORDERS_CSV_PATH as PAPER_TRADER_ORDERS_CSV_PATH,
        STATE_PATH as PAPER_TRADER_STATE_PATH,
        process_snapshot as process_paper_trader_snapshot,
    )
    PAPER_TRADER_IMPORT_ERROR = None
except Exception as exc:
    process_paper_trader_snapshot = None
    PAPER_TRADER_LATEST_PATH = None
    PAPER_TRADER_STATE_PATH = None
    PAPER_TRADER_ORDERS_CSV_PATH = None
    PAPER_TRADER_EQUITY_CURVE_CSV_PATH = None
    PAPER_TRADER_IMPORT_ERROR = repr(exc)

HEADERS = {"user-agent": "OpenClaw/1.0", "accept": "application/json"}
WORKDIR = Path(__file__).resolve().parents[1]
DATA_DIR = WORKDIR / "data" / "top15_tracker"
SNAPSHOT_DIR = DATA_DIR / "snapshots"
LATEST_DIR = DATA_DIR / "latest"
META_DIR = DATA_DIR / "meta"
DISPLAY_DIR = DATA_DIR / "display"
RAW_DIR = SNAPSHOT_DIR / "raw"
CLEAN_DIR = SNAPSHOT_DIR / "clean"
DISPLAY_SNAPSHOT_DIR = SNAPSHOT_DIR / "display"
KLINES_DIR = DATA_DIR / "klines"
KLINES_META_DIR = META_DIR / "klines"
PERP_SNAPSHOTS_DIR = DATA_DIR / "perp_snapshots"
PERP_META_DIR = META_DIR / "perp"
META_CACHE_PATH = META_DIR / "coinpaprika_coin_cache.json"
HISTORY_JSONL = DATA_DIR / "history.jsonl"
HISTORY_CSV = DATA_DIR / "history.csv"
HISTORY_DISPLAY_CSV = DATA_DIR / "history_display.csv"
CN_TZ = timezone(timedelta(hours=8))
KLINE_INTERVALS = {
    "1h": 60 * 60 * 1000,
    "4h": 4 * 60 * 60 * 1000,
    "1d": 24 * 60 * 60 * 1000,
}
KLINE_LOOKBACK_DAYS = 7
KLINE_LIMIT = 1000
BINANCE_SPOT_QUOTES = ["USDT", "FDUSD", "USDC", "BUSD", "TUSD"]
BINANCE_PERP_QUOTES = ["USDT", "USDC"]
PERP_OI_PERIOD = "5m"
PERP_OI_LIMIT = 60
FUNDING_RATE_LIMIT = 10
PERP_SNAPSHOT_FIELDNAMES = [
    "snapshot_id","captured_at_utc","captured_at_cst","symbol","binance_perp_symbol","binance_perp_status",
    "perp_last_price","perp_change_24h_pct","perp_quote_volume_24h","perp_trade_count_24h",
    "open_interest_contracts_now","open_interest_value_usd_now","oi_hist_value_latest_usd",
    "oi_change_15m_pct","oi_change_1h_pct","oi_change_4h_pct",
    "funding_rate_latest","funding_rate_mean_24h","funding_time_latest_utc","funding_time_latest_cst",
    "oi_hist_latest_utc","oi_hist_latest_cst","binance_perp_error","source","fetched_at_utc"
]
KNOWN_STABLECOIN_SYMBOLS = {
    "USDT", "USDC", "BUSD", "TUSD", "FDUSD", "DAI", "USDE", "USD1", "PYUSD", "USDD",
    "FRAX", "GHO", "RLUSD", "LUSD", "USDP", "SUSD", "EURC"
}
KNOWN_STABLECOIN_NAMES = {
    "tether", "usd coin", "binance usd", "trueusd", "first digital usd", "dai", "ethena usde",
    "world liberty financial usd", "paypal usd", "usdd", "frax", "gho", "ripple usd", "liquity usd",
    "pax dollar", "susd", "euro coin"
}

for p in [
    DATA_DIR, SNAPSHOT_DIR, LATEST_DIR, META_DIR, DISPLAY_DIR, RAW_DIR, CLEAN_DIR,
    DISPLAY_SNAPSHOT_DIR, KLINES_DIR, KLINES_META_DIR, PERP_SNAPSHOTS_DIR, PERP_META_DIR
]:
    p.mkdir(parents=True, exist_ok=True)


def get_json(url, timeout=30):
    req = urllib.request.Request(url, headers=HEADERS)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.load(r)


def now_utc():
    return datetime.now(timezone.utc)


def ts_slug(dt: datetime) -> str:
    return dt.strftime("%Y%m%dT%H%M%SZ")


def load_meta_cache():
    if META_CACHE_PATH.exists():
        try:
            return json.loads(META_CACHE_PATH.read_text(encoding="utf-8"))
        except Exception:
            return {}
    return {}


def save_meta_cache(cache):
    META_CACHE_PATH.write_text(json.dumps(cache, ensure_ascii=False, indent=2), encoding="utf-8")


def clean_text(s: str) -> str:
    if not s:
        return ""
    return re.sub(r"\s+", " ", s).strip()


def summarize_description(desc: str, limit=220) -> str:
    desc = clean_text(desc)
    if not desc:
        return ""
    desc = desc.replace("Source: CoinPaprika.com", "").strip()
    if len(desc) <= limit:
        return desc
    cut = desc[:limit]
    if " " in cut:
        cut = cut.rsplit(" ", 1)[0]
    return cut + "…"


def resolve_binance_perp_symbol(symbol: str, futures_by_symbol: dict):
    symbol = str(symbol or "").upper()
    if not symbol:
        return None, None

    for quote in BINANCE_PERP_QUOTES:
        exact = f"{symbol}{quote}"
        if exact in futures_by_symbol:
            return exact, futures_by_symbol[exact]

    # Binance perpeturals sometimes use a numeric contract multiplier prefix,
    # for example spot LUNC -> futures 1000LUNCUSDT.
    for quote in BINANCE_PERP_QUOTES:
        pattern = re.compile(rf"^\d+{re.escape(symbol)}{re.escape(quote)}$")
        matches = [pair for pair in futures_by_symbol.keys() if pattern.match(pair)]
        if len(matches) == 1:
            pair = matches[0]
            return pair, futures_by_symbol[pair]

    return None, None


def safe_float(v):
    try:
        if v is None or v == "":
            return None
        return float(v)
    except Exception:
        return None


def safe_int(v):
    try:
        if v is None or v == "":
            return None
        return int(v)
    except Exception:
        return None


def mean_float(values):
    nums = []
    for value in values:
        num = safe_float(value)
        if num is not None:
            nums.append(num)
    if not nums:
        return None
    return sum(nums) / len(nums)


def pct_change(a, b):
    a = safe_float(a)
    b = safe_float(b)
    if a in (None, 0) or b is None:
        return None
    return (b - a) / a * 100


def max_drawdown_pct(closes):
    vals = [safe_float(x) for x in closes if safe_float(x) is not None]
    if len(vals) < 2:
        return None
    peak = vals[0]
    max_dd = 0.0
    for v in vals:
        if v > peak:
            peak = v
        dd = (v - peak) / peak * 100 if peak else 0.0
        if dd < max_dd:
            max_dd = dd
    return max_dd


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
    last_close = safe_float(last.get("close_price"))
    last_quote = safe_float(last.get("quote_volume"))
    highs = [safe_float(r.get("high_price")) for r in prev if safe_float(r.get("high_price")) is not None]
    quotes = [safe_float(r.get("quote_volume")) for r in prev if safe_float(r.get("quote_volume")) is not None]
    if last_close is None or not highs:
        return "Unknown"
    if last_close > max(highs):
        avg_quote = sum(quotes) / len(quotes) if quotes else None
        if avg_quote and last_quote and last_quote > avg_quote * 1.3:
            return "VolumeBreakout"
        return "PriceBreakout"
    return "NoBreakout"


def classify_sector(tags, name="", symbol=""):
    names = [t.get("name", "") for t in (tags or [])]
    lowered = [n.lower() for n in names]
    text = " | ".join(lowered + [name.lower(), symbol.lower()])
    if any("meme" in x for x in lowered):
        return "Meme"
    if any("layer 1" in x or "l1" in x for x in lowered):
        return "Layer1"
    if any("defi" in x for x in lowered):
        return "DeFi"
    if any("ai" in x or "artificial intelligence" in x for x in lowered) or symbol.upper() == "TAO":
        return "AI"
    if "stablecoin" in text or symbol.upper() in KNOWN_STABLECOIN_SYMBOLS:
        return "Stablecoin"
    if "wrapped" in text or symbol.upper().startswith("WBTC") or symbol.upper() == "CBBTC":
        return "WrappedAsset"
    if any("exchange" in x for x in lowered):
        return "Exchange"
    if any("oracle" in x for x in lowered):
        return "Oracle"
    if any("payment" in x for x in lowered):
        return "Payments"
    return names[0] if names else "Unclassified"


def normalize_narrative_tags(sector_primary, sector_tags, symbol):
    normalized = set()
    joined = " | ".join((sector_tags or [])).lower()
    if sector_primary == "Meme" or "meme" in joined:
        normalized.add("Meme")
    if sector_primary == "AI" or symbol.upper() == "TAO":
        normalized.add("AI")
    if sector_primary == "Layer1" or "layer 1" in joined or "l1" in joined:
        normalized.add("Layer1")
    if sector_primary == "DeFi" or "defi" in joined:
        normalized.add("DeFi")
    if sector_primary == "Stablecoin" or "stablecoin" in joined:
        normalized.add("Stablecoin")
    if sector_primary == "WrappedAsset":
        normalized.add("WrappedAsset")
    if sector_primary == "Oracle" or "oracle" in joined:
        normalized.add("Oracle")
    if sector_primary == "Payments" or "payment" in joined:
        normalized.add("Payments")
    if not normalized and sector_primary and sector_primary != "Unclassified":
        normalized.add(sector_primary)
    return sorted(normalized)


def liquidity_bucket(volume_usd):
    if volume_usd >= 5_000_000_000:
        return "VeryHigh"
    if volume_usd >= 1_000_000_000:
        return "High"
    if volume_usd >= 300_000_000:
        return "MediumHigh"
    return "Qualified"


def activity_bucket(trade_count, quote_volume):
    if trade_count is None and quote_volume is None:
        return "Unknown"
    score = 0
    if trade_count is not None:
        if trade_count >= 1_000_000:
            score += 2
        elif trade_count >= 100_000:
            score += 1
    if quote_volume is not None:
        if quote_volume >= 500_000_000:
            score += 2
        elif quote_volume >= 50_000_000:
            score += 1
    return {0: "Low", 1: "Moderate", 2: "High", 3: "VeryHigh", 4: "VeryHigh"}.get(score, "Moderate")


def market_cap_band(market_cap_usd):
    if market_cap_usd is None:
        return "Unknown"
    if market_cap_usd >= 100_000_000_000:
        return "Mega"
    if market_cap_usd >= 10_000_000_000:
        return "Large"
    if market_cap_usd >= 1_000_000_000:
        return "Mid"
    return "Small"


def momentum_bucket(change_24h_pct):
    if change_24h_pct is None:
        return "Unknown"
    if change_24h_pct >= 20:
        return "Explosive"
    if change_24h_pct >= 10:
        return "VeryStrong"
    if change_24h_pct >= 5:
        return "Strong"
    if change_24h_pct >= 0:
        return "Positive"
    return "Negative"


def turnover_bucket(turnover_ratio):
    if turnover_ratio is None:
        return "Unknown"
    if turnover_ratio >= 1.0:
        return "Extreme"
    if turnover_ratio >= 0.4:
        return "VeryHigh"
    if turnover_ratio >= 0.15:
        return "High"
    if turnover_ratio >= 0.05:
        return "Moderate"
    return "Low"


def verify_grade(binance_status, price_diff_pct):
    if binance_status != "matched":
        return "Unverified"
    if price_diff_pct is None:
        return "Verified"
    if abs(price_diff_pct) <= 0.5:
        return "VerifiedStrong"
    if abs(price_diff_pct) <= 1.0:
        return "Verified"
    return "VerifiedLoose"


def build_risk_flags(row):
    flags = []
    sector = row.get("sector_primary")
    if sector == "Meme":
        flags.append("MemeVolatility")
    if sector == "Stablecoin":
        flags.append("Stablecoin")
    if sector == "WrappedAsset":
        flags.append("WrappedAsset")
    if row.get("binance_status") != "matched":
        flags.append("VenueCoverageLimited")
    if row.get("turnover_ratio_24h") is not None and row["turnover_ratio_24h"] >= 0.5:
        flags.append("HighTurnover")
    if row.get("change_24h_pct") is not None and row["change_24h_pct"] >= 20:
        flags.append("ShortTermOverheat")
    return flags


def ensure_coin_meta(cp_id: str, cache: dict):
    if cp_id in cache:
        return cache[cp_id]
    url = f"https://api.coinpaprika.com/v1/coins/{cp_id}"
    data = get_json(url, timeout=30)
    tags = data.get("tags") or []
    links = data.get("links") or {}
    meta = {
        "id": data.get("id"),
        "name": data.get("name"),
        "symbol": data.get("symbol"),
        "asset_type": data.get("type"),
        "sector_tags": [t.get("name") for t in tags if t.get("name")],
        "sector_primary": classify_sector(tags, data.get("name") or "", data.get("symbol") or ""),
        "narrative_summary": summarize_description(data.get("description") or ""),
        "website": (links.get("website") or [None])[0],
        "source_code": (links.get("source_code") or [None])[0],
        "explorer": (links.get("explorer") or [None])[0],
        "meta_fetched_at": now_utc().isoformat(),
    }
    cache[cp_id] = meta
    return meta


def write_csv(path: Path, rows, fieldnames):
    with path.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        for row in rows:
            w.writerow({k: row.get(k) for k in fieldnames})


def ensure_csv_schema(path: Path, fieldnames):
    if not path.exists():
        return
    with path.open("r", encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        existing_fieldnames = reader.fieldnames or []
        if existing_fieldnames == fieldnames:
            return
        existing_rows = list(reader)
    write_csv(path, existing_rows, fieldnames)


def append_history_csv(path: Path, rows, fieldnames):
    ensure_csv_schema(path, fieldnames)
    exists = path.exists()
    with path.open("a", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        if not exists:
            w.writeheader()
        for row in rows:
            w.writerow({k: row.get(k) for k in fieldnames})


def parse_iso_dt(value):
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value))
    except Exception:
        return None


def estimate_snapshot_interval_hours(history_rows):
    snapshot_dt_map = {}
    for r in history_rows:
        snapshot_id = r.get("snapshot_id")
        dt = parse_iso_dt(r.get("captured_at_utc"))
        if not snapshot_id or dt is None:
            continue
        prev = snapshot_dt_map.get(snapshot_id)
        if prev is None or dt < prev:
            snapshot_dt_map[snapshot_id] = dt

    dts = sorted(snapshot_dt_map.values())
    if len(dts) < 2:
        return 1.0

    diffs = []
    for i in range(1, len(dts)):
        hours = (dts[i] - dts[i - 1]).total_seconds() / 3600
        if hours > 0:
            diffs.append(hours)
    if not diffs:
        return 1.0
    diffs.sort()
    return max(5.0 / 60.0, diffs[len(diffs) // 2])


def load_recent_top15_history(lookback_hours=24):
    cutoff = now_utc() - timedelta(hours=lookback_hours)
    if not HISTORY_JSONL.exists():
        return []

    rows = []
    with HISTORY_JSONL.open('r', encoding='utf-8') as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except Exception:
                continue

            rule = row.get('filter_rule')
            if rule and rule != '24h_volume_usd_gt_15m_excluding_stablecoins_binance_spot_only':
                continue
            dt = parse_iso_dt(row.get('captured_at_utc'))
            if dt is None or dt < cutoff:
                continue
            rows.append(row)
    return rows


def compute_top15_presence_features(current_symbol, history_rows, run_dt, window_hours=24):
    snapshot_interval_hours = estimate_snapshot_interval_hours(history_rows)
    current_symbol = (current_symbol or '').upper()
    cutoff = run_dt - timedelta(hours=window_hours)

    symbol_rows = []
    unique_snapshot_ids = set()
    symbol_snapshot_ids = set()
    for row in history_rows:
        dt = parse_iso_dt(row.get('captured_at_utc'))
        if dt is None or dt < cutoff:
            continue
        snapshot_id = row.get('snapshot_id') or dt.isoformat()
        unique_snapshot_ids.add(snapshot_id)
        if (row.get('symbol') or '').upper() == current_symbol:
            symbol_rows.append({
                'snapshot_id': snapshot_id,
                'captured_at_utc': dt,
                'top15_position': row.get('top15_position'),
            })
            symbol_snapshot_ids.add(snapshot_id)

    current_snapshot_id = ts_slug(run_dt)
    unique_snapshot_ids.add(current_snapshot_id)
    symbol_snapshot_ids.add(current_snapshot_id)
    symbol_rows.append({
        'snapshot_id': current_snapshot_id,
        'captured_at_utc': run_dt,
        'top15_position': None,
    })

    symbol_rows.sort(key=lambda x: x['captured_at_utc'])

    persistence_hours = 0.0
    last_dt = run_dt
    for row in reversed(symbol_rows[:-1]):
        gap_hours = (last_dt - row['captured_at_utc']).total_seconds() / 3600
        if gap_hours <= snapshot_interval_hours * 1.8:
            persistence_hours += gap_hours
            last_dt = row['captured_at_utc']
        else:
            break

    total_snapshots = max(len(unique_snapshot_ids), 1)
    presence_ratio = len(symbol_snapshot_ids) / total_snapshots

    return {
        'top15_persistence_hours': round(persistence_hours, 3),
        'top15_presence_ratio_24h': round(presence_ratio, 4),
        'top15_presence_snapshots_24h': len(symbol_snapshot_ids),
        'top15_snapshot_count_24h': total_snapshots,
        'top15_observation_window_hours': window_hours,
        'top15_snapshot_interval_hours_est': round(snapshot_interval_hours, 4),
    }


def get_symbol_lookback_row(current_symbol, history_rows, run_dt, lookback_minutes, tolerance_minutes=7):
    current_symbol = (current_symbol or '').upper()
    target_dt = run_dt - timedelta(minutes=lookback_minutes)
    tolerance = timedelta(minutes=tolerance_minutes)
    best_row = None
    best_diff = None

    for row in history_rows:
        if (row.get('symbol') or '').upper() != current_symbol:
            continue
        dt = parse_iso_dt(row.get('captured_at_utc'))
        if dt is None:
            continue
        diff = abs(dt - target_dt)
        if diff > tolerance:
            continue
        if best_diff is None or diff < best_diff:
            best_row = row
            best_diff = diff

    return best_row


def compute_path_research_features(current_row, history_rows, run_dt):
    symbol = (current_row.get('symbol') or '').upper()
    if not symbol:
        return {}

    out = {}
    recent_overlap_window_hours = RECENT_OVERLAP_WINDOW_H
    lookbacks = [15, 30, 60]

    current_rank = safe_int(current_row.get('top15_position'))
    current_darkhorse = safe_float(current_row.get('darkhorse_score'))
    current_persistence = safe_float(current_row.get('persistence_score'))
    current_overlap = safe_float(current_row.get('overlap_score'))

    for mins in lookbacks:
        prev = get_symbol_lookback_row(symbol, history_rows, run_dt, mins)
        was_key = f'was_in_top15_{mins}m_ago'
        rank_key = f'rank_change_{mins}m'

        if prev is None:
            out[was_key] = False
            out[rank_key] = None
            if mins == 30:
                out['darkhorse_score_delta_30m'] = None
                out['persistence_score_delta_30m'] = None
                out['overlap_score_delta_30m'] = None
            continue

        prev_rank = safe_int(prev.get('top15_position'))
        out[was_key] = prev_rank is not None
        out[rank_key] = (prev_rank - current_rank) if (prev_rank is not None and current_rank is not None) else None

        if mins == 30:
            prev_darkhorse = safe_float(prev.get('darkhorse_score'))
            prev_persistence = safe_float(prev.get('persistence_score'))
            prev_overlap = safe_float(prev.get('overlap_score'))
            out['darkhorse_score_delta_30m'] = (current_darkhorse - prev_darkhorse) if (current_darkhorse is not None and prev_darkhorse is not None) else None
            out['persistence_score_delta_30m'] = (current_persistence - prev_persistence) if (current_persistence is not None and prev_persistence is not None) else None
            out['overlap_score_delta_30m'] = (current_overlap - prev_overlap) if (current_overlap is not None and prev_overlap is not None) else None

    symbol_rows = []
    for row in history_rows:
        if (row.get('symbol') or '').upper() != symbol:
            continue
        dt = parse_iso_dt(row.get('captured_at_utc'))
        if dt is None:
            continue
        symbol_rows.append({
            'captured_at_utc': dt,
            'top15_position': safe_int(row.get('top15_position')),
            'overlap_candidate': bool(row.get('overlap_candidate')),
        })

    symbol_rows.append({
        'captured_at_utc': run_dt,
        'top15_position': current_rank,
        'overlap_candidate': bool(current_row.get('overlap_candidate')),
    })
    symbol_rows.sort(key=lambda x: x['captured_at_utc'])

    snapshot_interval_hours = estimate_snapshot_interval_hours(history_rows)
    continuity_gap_hours = snapshot_interval_hours * 1.8

    episode_rows = [symbol_rows[-1]]
    last_dt = symbol_rows[-1]['captured_at_utc']
    for row in reversed(symbol_rows[:-1]):
        gap_hours = (last_dt - row['captured_at_utc']).total_seconds() / 3600
        if gap_hours <= continuity_gap_hours:
            episode_rows.append(row)
            last_dt = row['captured_at_utc']
        else:
            break
    episode_rows.reverse()

    last_overlap_dt = None
    for row in reversed(symbol_rows):
        if bool(row.get('overlap_candidate')):
            last_overlap_dt = row['captured_at_utc']
            break
    recent_overlap_cutoff = run_dt - timedelta(hours=recent_overlap_window_hours)
    out['recent_overlap_candidate_2h'] = any(
        bool(row.get('overlap_candidate')) and row['captured_at_utc'] >= recent_overlap_cutoff
        for row in symbol_rows
    )
    out['recent_overlap_window_hours'] = recent_overlap_window_hours
    out['last_overlap_candidate_utc'] = last_overlap_dt.isoformat() if last_overlap_dt else None
    out['last_overlap_candidate_cst'] = last_overlap_dt.astimezone(CN_TZ).isoformat() if last_overlap_dt else None
    out['hours_since_last_overlap_candidate'] = (
        round((run_dt - last_overlap_dt).total_seconds() / 3600, 3)
        if last_overlap_dt
        else None
    )

    episode_start_dt = episode_rows[0]['captured_at_utc'] if episode_rows else run_dt
    out['current_episode_start_utc'] = episode_start_dt.isoformat()
    out['current_episode_start_cst'] = episode_start_dt.astimezone(CN_TZ).isoformat()
    out['current_episode_duration_hours'] = round((run_dt - episode_start_dt).total_seconds() / 3600, 3)

    def first_hours_to(condition_fn):
        for row in episode_rows:
            if condition_fn(row):
                return round((row['captured_at_utc'] - episode_start_dt).total_seconds() / 3600, 3)
        return None

    out['hours_to_top10'] = first_hours_to(lambda r: r.get('top15_position') is not None and r.get('top15_position') <= 10)
    out['hours_to_top5'] = first_hours_to(lambda r: r.get('top15_position') is not None and r.get('top15_position') <= 5)
    out['hours_to_top3'] = first_hours_to(lambda r: r.get('top15_position') is not None and r.get('top15_position') <= 3)
    out['entry_to_confirmation_hours'] = first_hours_to(lambda r: bool(r.get('overlap_candidate')))

    def diff_hours(later_key, earlier_key, require_nonnegative=False):
        later = out.get(later_key)
        earlier = out.get(earlier_key)
        if later is None or earlier is None:
            return None
        diff = round(later - earlier, 3)
        if require_nonnegative and diff < 0:
            return None
        return diff

    out['confirmation_lag_vs_top10_h'] = diff_hours('entry_to_confirmation_hours', 'hours_to_top10', require_nonnegative=True)
    out['confirmation_lag_vs_top5_h'] = diff_hours('entry_to_confirmation_hours', 'hours_to_top5', require_nonnegative=True)
    out['confirmation_lag_vs_top3_h'] = diff_hours('entry_to_confirmation_hours', 'hours_to_top3', require_nonnegative=True)
    out['top10_to_top5_hours'] = diff_hours('hours_to_top5', 'hours_to_top10', require_nonnegative=True)
    out['top5_to_top3_hours'] = diff_hours('hours_to_top3', 'hours_to_top5', require_nonnegative=True)
    out['top3_to_confirmation_hours'] = diff_hours('entry_to_confirmation_hours', 'hours_to_top3', require_nonnegative=True)

    episode_ranks = [r.get('top15_position') for r in episode_rows if r.get('top15_position') is not None]
    out['episode_snapshot_count'] = len(episode_rows)
    out['episode_best_rank'] = min(episode_ranks) if episode_ranks else None
    out['episode_worst_rank'] = max(episode_ranks) if episode_ranks else None
    if out['episode_best_rank'] is not None and out['episode_worst_rank'] is not None:
        out['episode_rank_improve_range'] = out['episode_worst_rank'] - out['episode_best_rank']
    else:
        out['episode_rank_improve_range'] = None

    confirmation_idx = None
    for idx, row in enumerate(episode_rows, start=1):
        if bool(row.get('overlap_candidate')):
            confirmation_idx = idx
            break
    out['episode_confirmation_snapshot_index'] = confirmation_idx
    if confirmation_idx is not None and out['episode_snapshot_count']:
        out['episode_confirmation_progress_ratio'] = round(confirmation_idx / out['episode_snapshot_count'], 3)
    else:
        out['episode_confirmation_progress_ratio'] = None

    if confirmation_idx is None:
        pre_confirmation_rows = list(episode_rows)
    else:
        pre_confirmation_rows = episode_rows[:confirmation_idx]

    pre_confirmation_ranks = [r.get('top15_position') for r in pre_confirmation_rows if r.get('top15_position') is not None]
    out['episode_best_rank_before_confirmation'] = min(pre_confirmation_ranks) if pre_confirmation_ranks else None
    out['episode_worst_rank_before_confirmation'] = max(pre_confirmation_ranks) if pre_confirmation_ranks else None
    if out['episode_best_rank_before_confirmation'] is not None and out['episode_worst_rank_before_confirmation'] is not None:
        out['pre_confirmation_rank_range'] = out['episode_worst_rank_before_confirmation'] - out['episode_best_rank_before_confirmation']
    else:
        out['pre_confirmation_rank_range'] = None

    if len(pre_confirmation_ranks) >= 2:
        mean_rank = sum(pre_confirmation_ranks) / len(pre_confirmation_ranks)
        variance = sum((r - mean_rank) ** 2 for r in pre_confirmation_ranks) / len(pre_confirmation_ranks)
        out['pre_confirmation_rank_std'] = round(math.sqrt(variance), 3)
    else:
        out['pre_confirmation_rank_std'] = None

    out['pre_confirmation_top10_presence_ratio'] = round(sum(1 for r in pre_confirmation_ranks if r <= 10) / len(pre_confirmation_ranks), 3) if pre_confirmation_ranks else None
    out['pre_confirmation_top5_presence_ratio'] = round(sum(1 for r in pre_confirmation_ranks if r <= 5) / len(pre_confirmation_ranks), 3) if pre_confirmation_ranks else None
    out['pre_confirmation_top3_presence_ratio'] = round(sum(1 for r in pre_confirmation_ranks if r <= 3) / len(pre_confirmation_ranks), 3) if pre_confirmation_ranks else None

    lag_top5 = out.get('confirmation_lag_vs_top5_h')
    rank_range = out.get('pre_confirmation_rank_range')
    rank_std = out.get('pre_confirmation_rank_std')
    top5_hours = out.get('hours_to_top5')
    confirmation_hours = out.get('entry_to_confirmation_hours')
    entered_top5_before_confirm = (
        top5_hours is not None
        and confirmation_hours is not None
        and top5_hours <= confirmation_hours
    )
    if entered_top5_before_confirm and top5_hours <= 0.5 and lag_top5 is not None and lag_top5 <= 1.0:
        out['path_class_v2'] = 'FastRank_FastConfirm'
    elif entered_top5_before_confirm and top5_hours <= 0.5 and lag_top5 is not None and lag_top5 > 1.0:
        out['path_class_v2'] = 'FastRank_SlowConfirm'
    elif entered_top5_before_confirm and top5_hours > 0.5 and lag_top5 is not None and lag_top5 <= 1.0:
        out['path_class_v2'] = 'SlowRank_FastConfirm'
    elif entered_top5_before_confirm and top5_hours > 0.5 and lag_top5 is not None and lag_top5 > 1.0:
        out['path_class_v2'] = 'SlowRank_SlowConfirm'
    elif lag_top5 is not None and lag_top5 > 1.0 and rank_range is not None and rank_range >= 6:
        out['path_class_v2'] = 'HighVolatile_ConfirmLate'
    elif lag_top5 is not None and lag_top5 <= 1.5 and rank_range is not None and rank_range <= 3 and rank_std is not None and rank_std <= 1.5:
        out['path_class_v2'] = 'StableAdvance_ConfirmMid'
    else:
        out['path_class_v2'] = 'Unclassified'

    return out


def klines_symbol_dir(symbol: str, interval: str) -> Path:
    return KLINES_DIR / symbol.upper() / interval


def klines_csv_path(symbol: str, interval: str) -> Path:
    return klines_symbol_dir(symbol, interval) / "candles.csv"


def klines_manifest_path(symbol: str, interval: str) -> Path:
    return KLINES_META_DIR / f"{symbol.upper()}__{interval}.json"


def load_kline_manifest(symbol: str, interval: str):
    path = klines_manifest_path(symbol, interval)
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def save_kline_manifest(symbol: str, interval: str, payload: dict):
    path = klines_manifest_path(symbol, interval)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def fetch_binance_klines(symbol_pair: str, interval: str, start_ms: int, end_ms: int, limit: int = KLINE_LIMIT):
    params = urlencode({
        "symbol": symbol_pair,
        "interval": interval,
        "startTime": start_ms,
        "endTime": end_ms,
        "limit": limit,
    })
    url = f"https://api.binance.com/api/v3/klines?{params}"
    return get_json(url, timeout=30)


def load_existing_kline_open_times(path: Path):
    open_times = set()
    if not path.exists():
        return open_times
    with path.open("r", encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            try:
                open_times.add(int(row.get("open_time_ms")))
            except Exception:
                continue
    return open_times


def append_klines_csv(path: Path, rows):
    fieldnames = [
        "symbol","binance_pair","interval","open_time_ms","open_time_utc","open_time_cst",
        "open_price","high_price","low_price","close_price","volume_base",
        "close_time_ms","close_time_utc","close_time_cst","quote_volume",
        "trade_count","taker_buy_base_volume","taker_buy_quote_volume","source","fetched_at_utc"
    ]
    path.parent.mkdir(parents=True, exist_ok=True)
    exists = path.exists()
    with path.open("a", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        if not exists:
            w.writeheader()
        for row in rows:
            w.writerow({k: row.get(k) for k in fieldnames})


def sync_symbol_klines(symbol: str, binance_pair: str, now_dt: datetime):
    if not binance_pair:
        return []
    synced = []
    end_ms = int(now_dt.timestamp() * 1000)
    default_start_ms = int((now_dt - timedelta(days=KLINE_LOOKBACK_DAYS)).timestamp() * 1000)

    for interval, interval_ms in KLINE_INTERVALS.items():
        csv_path = klines_csv_path(symbol, interval)
        manifest = load_kline_manifest(symbol, interval)
        existing_open_times = load_existing_kline_open_times(csv_path)
        last_open_ms = manifest.get("last_open_time_ms")
        if isinstance(last_open_ms, int):
            start_ms = max(default_start_ms, last_open_ms + interval_ms)
        else:
            start_ms = default_start_ms
        if start_ms >= end_ms:
            continue

        payload = fetch_binance_klines(binance_pair, interval, start_ms, end_ms)
        new_rows = []
        max_open_ms = last_open_ms if isinstance(last_open_ms, int) else None
        for item in payload:
            open_time_ms = int(item[0])
            if open_time_ms in existing_open_times:
                continue
            close_time_ms = int(item[6])
            open_dt = datetime.fromtimestamp(open_time_ms / 1000, tz=timezone.utc)
            close_dt = datetime.fromtimestamp(close_time_ms / 1000, tz=timezone.utc)
            row = {
                "symbol": symbol.upper(),
                "binance_pair": binance_pair,
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
                "fetched_at_utc": now_dt.isoformat(),
            }
            new_rows.append(row)
            existing_open_times.add(open_time_ms)
            if max_open_ms is None or open_time_ms > max_open_ms:
                max_open_ms = open_time_ms

        if new_rows:
            new_rows.sort(key=lambda x: int(x["open_time_ms"]))
            append_klines_csv(csv_path, new_rows)
            save_kline_manifest(symbol, interval, {
                "symbol": symbol.upper(),
                "binance_pair": binance_pair,
                "interval": interval,
                "lookback_days": KLINE_LOOKBACK_DAYS,
                "last_open_time_ms": max_open_ms,
                "last_open_time_utc": datetime.fromtimestamp(max_open_ms / 1000, tz=timezone.utc).isoformat() if max_open_ms else None,
                "updated_at_utc": now_dt.isoformat(),
                "csv_path": str(csv_path.relative_to(WORKDIR)),
            })
        elif not manifest:
            save_kline_manifest(symbol, interval, {
                "symbol": symbol.upper(),
                "binance_pair": binance_pair,
                "interval": interval,
                "lookback_days": KLINE_LOOKBACK_DAYS,
                "last_open_time_ms": last_open_ms,
                "last_open_time_utc": datetime.fromtimestamp(last_open_ms / 1000, tz=timezone.utc).isoformat() if isinstance(last_open_ms, int) else None,
                "updated_at_utc": now_dt.isoformat(),
                "csv_path": str(csv_path.relative_to(WORKDIR)),
            })

        synced.append({
            "interval": interval,
            "new_rows": len(new_rows),
            "csv_path": str(csv_path.relative_to(WORKDIR)),
            "start_ms": start_ms,
            "end_ms": end_ms,
        })
    return synced


def load_kline_rows(symbol: str, interval: str):
    path = klines_csv_path(symbol, interval)
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def perp_snapshot_csv_path(symbol: str) -> Path:
    return PERP_SNAPSHOTS_DIR / f"{symbol.upper()}.csv"


def perp_manifest_path(symbol: str) -> Path:
    return PERP_META_DIR / f"{symbol.upper()}.json"


def load_perp_manifest(symbol: str):
    path = perp_manifest_path(symbol)
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def save_perp_manifest(symbol: str, payload: dict):
    path = perp_manifest_path(symbol)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def fetch_binance_futures_24h():
    return get_json("https://fapi.binance.com/fapi/v1/ticker/24hr", timeout=30)


def fetch_binance_futures_open_interest(symbol_pair: str):
    params = urlencode({"symbol": symbol_pair})
    return get_json(f"https://fapi.binance.com/fapi/v1/openInterest?{params}", timeout=30)


def fetch_binance_futures_open_interest_hist(symbol_pair: str, period: str = PERP_OI_PERIOD, limit: int = PERP_OI_LIMIT):
    params = urlencode({"symbol": symbol_pair, "period": period, "limit": limit})
    return get_json(f"https://fapi.binance.com/futures/data/openInterestHist?{params}", timeout=30)


def fetch_binance_futures_funding_rate(symbol_pair: str, limit: int = FUNDING_RATE_LIMIT):
    params = urlencode({"symbol": symbol_pair, "limit": limit})
    return get_json(f"https://fapi.binance.com/fapi/v1/fundingRate?{params}", timeout=30)


def hist_window_pct_change(rows, steps_back: int, field: str):
    if len(rows) <= steps_back:
        return None
    current = safe_float(rows[-1].get(field))
    previous = safe_float(rows[-(steps_back + 1)].get(field))
    if current is None or previous in (None, 0):
        return None
    return (current - previous) / previous * 100


def sync_symbol_perp(symbol: str, perp_symbol: str, perp_ticker: dict, run_dt: datetime, run_id: str, captured_at_cst: str):
    summary = {
        "binance_perp_status": "not_listed_or_no_usd_perp_found",
        "binance_perp_symbol": None,
        "binance_perp_error": None,
        "perp_last_price": None,
        "perp_change_24h_pct": None,
        "perp_quote_volume_24h": None,
        "perp_trade_count_24h": None,
        "open_interest_contracts_now": None,
        "open_interest_value_usd_now": None,
        "oi_hist_value_latest_usd": None,
        "oi_change_15m_pct": None,
        "oi_change_1h_pct": None,
        "oi_change_4h_pct": None,
        "funding_rate_latest": None,
        "funding_rate_mean_24h": None,
        "funding_time_latest_utc": None,
        "funding_time_latest_cst": None,
        "oi_hist_latest_utc": None,
        "oi_hist_latest_cst": None,
    }
    sync_info = {
        "symbol": symbol.upper(),
        "binance_perp_symbol": perp_symbol,
        "status": summary["binance_perp_status"],
        "snapshot_path": None,
        "manifest_path": None,
    }
    if not perp_symbol or not perp_ticker:
        return summary, sync_info

    errors = []
    open_interest_payload = {}
    oi_hist_payload = []
    funding_payload = []

    try:
        open_interest_payload = fetch_binance_futures_open_interest(perp_symbol)
    except Exception as e:
        errors.append(f"open_interest:{repr(e)}")
    try:
        oi_hist_payload = fetch_binance_futures_open_interest_hist(perp_symbol)
    except Exception as e:
        errors.append(f"open_interest_hist:{repr(e)}")
    try:
        funding_payload = fetch_binance_futures_funding_rate(perp_symbol)
    except Exception as e:
        errors.append(f"funding_rate:{repr(e)}")

    oi_hist_rows = sorted(
        [row for row in (oi_hist_payload or []) if safe_int(row.get("timestamp")) is not None],
        key=lambda row: int(row["timestamp"])
    )
    funding_rows = sorted(
        [row for row in (funding_payload or []) if safe_int(row.get("fundingTime")) is not None],
        key=lambda row: int(row["fundingTime"])
    )

    open_interest_contracts_now = safe_float(open_interest_payload.get("openInterest"))
    perp_last_price = safe_float(perp_ticker.get("lastPrice"))
    perp_change_24h_pct = safe_float(perp_ticker.get("priceChangePercent"))
    perp_quote_volume_24h = safe_float(perp_ticker.get("quoteVolume"))
    perp_trade_count_24h = safe_int(perp_ticker.get("count"))
    open_interest_value_usd_now = (open_interest_contracts_now * perp_last_price) if (open_interest_contracts_now is not None and perp_last_price is not None) else None

    oi_hist_latest_dt = None
    oi_hist_value_latest_usd = None
    if oi_hist_rows:
        oi_hist_latest_dt = datetime.fromtimestamp(int(oi_hist_rows[-1]["timestamp"]) / 1000, tz=timezone.utc)
        oi_hist_value_latest_usd = safe_float(oi_hist_rows[-1].get("sumOpenInterestValue"))

    funding_latest_dt = None
    funding_rate_latest = None
    funding_rate_mean_24h = None
    if funding_rows:
        funding_latest_dt = datetime.fromtimestamp(int(funding_rows[-1]["fundingTime"]) / 1000, tz=timezone.utc)
        funding_rate_latest = safe_float(funding_rows[-1].get("fundingRate"))
        cutoff_ms = int((funding_latest_dt - timedelta(hours=24)).timestamp() * 1000)
        funding_rate_mean_24h = mean_float(
            row.get("fundingRate")
            for row in funding_rows
            if int(row["fundingTime"]) >= cutoff_ms
        )

    status = "matched" if not errors else "matched_partial_error"
    error_text = " | ".join(errors) if errors else None
    summary.update({
        "binance_perp_status": status,
        "binance_perp_symbol": perp_symbol,
        "binance_perp_error": error_text,
        "perp_last_price": perp_last_price,
        "perp_change_24h_pct": perp_change_24h_pct,
        "perp_quote_volume_24h": perp_quote_volume_24h,
        "perp_trade_count_24h": perp_trade_count_24h,
        "open_interest_contracts_now": open_interest_contracts_now,
        "open_interest_value_usd_now": open_interest_value_usd_now,
        "oi_hist_value_latest_usd": oi_hist_value_latest_usd,
        "oi_change_15m_pct": hist_window_pct_change(oi_hist_rows, 3, "sumOpenInterestValue"),
        "oi_change_1h_pct": hist_window_pct_change(oi_hist_rows, 12, "sumOpenInterestValue"),
        "oi_change_4h_pct": hist_window_pct_change(oi_hist_rows, 48, "sumOpenInterestValue"),
        "funding_rate_latest": funding_rate_latest,
        "funding_rate_mean_24h": funding_rate_mean_24h,
        "funding_time_latest_utc": funding_latest_dt.isoformat() if funding_latest_dt else None,
        "funding_time_latest_cst": funding_latest_dt.astimezone(CN_TZ).isoformat() if funding_latest_dt else None,
        "oi_hist_latest_utc": oi_hist_latest_dt.isoformat() if oi_hist_latest_dt else None,
        "oi_hist_latest_cst": oi_hist_latest_dt.astimezone(CN_TZ).isoformat() if oi_hist_latest_dt else None,
    })

    snapshot_row = {
        "snapshot_id": run_id,
        "captured_at_utc": run_dt.isoformat(),
        "captured_at_cst": captured_at_cst,
        "symbol": symbol.upper(),
        "binance_perp_symbol": perp_symbol,
        "binance_perp_status": status,
        "perp_last_price": perp_last_price,
        "perp_change_24h_pct": perp_change_24h_pct,
        "perp_quote_volume_24h": perp_quote_volume_24h,
        "perp_trade_count_24h": perp_trade_count_24h,
        "open_interest_contracts_now": open_interest_contracts_now,
        "open_interest_value_usd_now": open_interest_value_usd_now,
        "oi_hist_value_latest_usd": oi_hist_value_latest_usd,
        "oi_change_15m_pct": summary["oi_change_15m_pct"],
        "oi_change_1h_pct": summary["oi_change_1h_pct"],
        "oi_change_4h_pct": summary["oi_change_4h_pct"],
        "funding_rate_latest": funding_rate_latest,
        "funding_rate_mean_24h": funding_rate_mean_24h,
        "funding_time_latest_utc": summary["funding_time_latest_utc"],
        "funding_time_latest_cst": summary["funding_time_latest_cst"],
        "oi_hist_latest_utc": summary["oi_hist_latest_utc"],
        "oi_hist_latest_cst": summary["oi_hist_latest_cst"],
        "binance_perp_error": error_text,
        "source": "Binance Futures",
        "fetched_at_utc": run_dt.isoformat(),
    }
    csv_path = perp_snapshot_csv_path(symbol)
    append_history_csv(csv_path, [snapshot_row], PERP_SNAPSHOT_FIELDNAMES)
    manifest_payload = {
        "symbol": symbol.upper(),
        "binance_perp_symbol": perp_symbol,
        "status": status,
        "updated_at_utc": run_dt.isoformat(),
        "csv_path": str(csv_path.relative_to(WORKDIR)),
        "latest_snapshot_id": run_id,
        "latest_oi_hist_utc": summary["oi_hist_latest_utc"],
        "latest_funding_time_utc": summary["funding_time_latest_utc"],
        "error": error_text,
    }
    save_perp_manifest(symbol, manifest_payload)
    sync_info.update({
        "status": status,
        "snapshot_path": str(csv_path.relative_to(WORKDIR)),
        "manifest_path": str(perp_manifest_path(symbol).relative_to(WORKDIR)),
        "oi_hist_rows": len(oi_hist_rows),
        "funding_rows": len(funding_rows),
        "error": error_text,
    })
    return summary, sync_info


def compute_structure_features(symbol: str):
    rows_1h = load_kline_rows(symbol, "1h")
    rows_4h = load_kline_rows(symbol, "4h")
    rows_1d = load_kline_rows(symbol, "1d")
    closes_1h = [safe_float(r.get("close_price")) for r in rows_1h if safe_float(r.get("close_price")) is not None]
    closes_4h = [safe_float(r.get("close_price")) for r in rows_4h if safe_float(r.get("close_price")) is not None]
    closes_1d = [safe_float(r.get("close_price")) for r in rows_1d if safe_float(r.get("close_price")) is not None]

    chg_7d = pct_change(closes_1d[0], closes_1d[-1]) if len(closes_1d) >= 2 else None
    chg_4h = pct_change(closes_4h[0], closes_4h[-1]) if len(closes_4h) >= 2 else None
    chg_1h = pct_change(closes_1h[0], closes_1h[-1]) if len(closes_1h) >= 2 else None
    drawdown_7d = max_drawdown_pct(closes_1h)
    breakout_1h = breakout_label(rows_1h[-24:]) if rows_1h else "Unknown"
    breakout_4h = breakout_label(rows_4h[-12:]) if rows_4h else "Unknown"
    trend_1d = interval_trend_label(closes_1d[0], closes_1d[-1]) if len(closes_1d) >= 2 else "Unknown"
    trend_4h = interval_trend_label(closes_4h[0], closes_4h[-1]) if len(closes_4h) >= 2 else "Unknown"
    trend_1h = interval_trend_label(closes_1h[0], closes_1h[-1]) if len(closes_1h) >= 2 else "Unknown"

    score = 0
    for chg in [chg_7d, chg_4h, chg_1h]:
        if chg is None:
            continue
        if chg >= 15:
            score += 2
        elif chg >= 5:
            score += 1
        elif chg <= -10:
            score -= 2
        elif chg < 0:
            score -= 1
    if drawdown_7d is not None:
        if drawdown_7d >= -8:
            score += 1
        elif drawdown_7d <= -20:
            score -= 1
    if breakout_1h == "VolumeBreakout":
        score += 2
    elif breakout_1h == "PriceBreakout":
        score += 1
    if breakout_4h == "VolumeBreakout":
        score += 1

    if score >= 6:
        structure_grade = "A"
        structure_state = "TrendLeader"
    elif score >= 3:
        structure_grade = "B"
        structure_state = "Strong"
    elif score >= 0:
        structure_grade = "C"
        structure_state = "Neutral"
    else:
        structure_grade = "D"
        structure_state = "Weak"

    return {
        "kline_window_days": KLINE_LOOKBACK_DAYS,
        "kline_1h_bars": len(rows_1h),
        "kline_4h_bars": len(rows_4h),
        "kline_1d_bars": len(rows_1d),
        "price_change_7d_pct": chg_7d,
        "price_change_4h_window_pct": chg_4h,
        "price_change_1h_window_pct": chg_1h,
        "max_drawdown_7d_pct": drawdown_7d,
        "trend_1d": trend_1d,
        "trend_4h": trend_4h,
        "trend_1h": trend_1h,
        "breakout_1h": breakout_1h,
        "breakout_4h": breakout_4h,
        "structure_score": score,
        "structure_grade": structure_grade,
        "structure_state": structure_state,
    }


def compute_darkhorse_features(row):
    score = 0
    structure_score = row.get("structure_score")
    if structure_score is not None:
        score += float(structure_score)
    momentum = row.get("change_24h_pct")
    if momentum is not None:
        if momentum >= 20:
            score += 2
        elif momentum >= 10:
            score += 1
        elif momentum < 0:
            score -= 2
    turnover = row.get("turnover_ratio_24h")
    if turnover is not None:
        if 0.15 <= turnover <= 1.2:
            score += 2
        elif turnover > 1.8:
            score -= 1
    activity = row.get("activity_bucket")
    if activity == "VeryHigh":
        score += 2
    elif activity == "High":
        score += 1
    elif activity == "Low":
        score -= 1
    trend_1d = row.get("trend_1d")
    trend_4h = row.get("trend_4h")
    breakout_1h = row.get("breakout_1h")
    breakout_4h = row.get("breakout_4h")
    if trend_1d in {"StrongUp", "Up"}:
        score += 2
    elif trend_1d in {"Down", "StrongDown"}:
        score -= 2
    if trend_4h in {"StrongUp", "Up"}:
        score += 1
    if breakout_1h == "VolumeBreakout":
        score += 2
    elif breakout_1h == "PriceBreakout":
        score += 1
    if breakout_4h == "VolumeBreakout":
        score += 1
    drawdown = row.get("max_drawdown_7d_pct")
    if drawdown is not None:
        if drawdown >= -10:
            score += 1
        elif drawdown <= -25:
            score -= 2
    if row.get("sector_primary") == "Meme":
        score -= 1
    if row.get("binance_status") != "matched":
        score -= 2
    if row.get("verify_grade") == "VerifiedStrong":
        score += 1

    if score >= 10:
        top5_potential = "VeryHigh"
        sustainability = "High"
        darkhorse_tag = "高确定性黑马"
    elif score >= 7:
        top5_potential = "High"
        sustainability = "MediumHigh"
        darkhorse_tag = "强势冲榜型"
    elif score >= 4:
        top5_potential = "Medium"
        sustainability = "Medium"
        darkhorse_tag = "可跟踪候选"
    elif score >= 1:
        top5_potential = "Low"
        sustainability = "Low"
        darkhorse_tag = "短线观察型"
    else:
        top5_potential = "VeryLow"
        sustainability = "VeryLow"
        darkhorse_tag = "高噪音非优先"

    if drawdown is not None and momentum is not None:
        if momentum >= 10 and drawdown >= -12:
            risk_reward_profile = "Asymmetric"
        elif momentum >= 10 and drawdown <= -20:
            risk_reward_profile = "HighRiskHighBeta"
        elif momentum < 5 and drawdown >= -10:
            risk_reward_profile = "Balanced"
        else:
            risk_reward_profile = "Fragile"
    else:
        risk_reward_profile = "Unknown"

    return {
        "darkhorse_score": score,
        "top5_potential": top5_potential,
        "sustainability": sustainability,
        "risk_reward_profile": risk_reward_profile,
        "darkhorse_tag": darkhorse_tag,
    }


def compute_persistence_features(row):
    score = 0
    evidence = []

    t1d = row.get("trend_1d")
    t4h = row.get("trend_4h")
    t1h = row.get("trend_1h")

    if t1d == "StrongUp":
        score += 3
        evidence.append("1d强上行")
    elif t1d == "Up":
        score += 2
        evidence.append("1d上行")
    elif t1d in {"Down", "StrongDown"}:
        score -= 3
        evidence.append("1d转弱")

    if t4h == "StrongUp":
        score += 3
        evidence.append("4h强上行")
    elif t4h == "Up":
        score += 2
        evidence.append("4h上行")
    elif t4h in {"Down", "StrongDown"}:
        score -= 2
        evidence.append("4h转弱")

    if t1h == "StrongUp":
        score += 2
        evidence.append("1h推进")
    elif t1h == "Up":
        score += 1
    elif t1h in {"Down", "StrongDown"}:
        score -= 1

    drawdown = row.get("max_drawdown_7d_pct")
    if drawdown is not None:
        if drawdown >= -8:
            score += 2
            evidence.append("回撤可控")
        elif drawdown >= -15:
            score += 1
        elif drawdown <= -25:
            score -= 3
            evidence.append("回撤过深")
        elif drawdown <= -18:
            score -= 1

    activity = row.get("activity_bucket")
    if activity == "VeryHigh":
        score += 2
        evidence.append("活跃承接强")
    elif activity == "High":
        score += 1
    elif activity == "Low":
        score -= 1

    if row.get("breakout_4h") == "VolumeBreakout":
        score += 2
        evidence.append("4h放量突破")
    elif row.get("breakout_4h") == "PriceBreakout":
        score += 1
    if row.get("breakout_1h") == "VolumeBreakout":
        score += 1
        evidence.append("1h放量突破")

    turnover = row.get("turnover_ratio_24h")
    if turnover is not None:
        if 0.10 <= turnover <= 1.0:
            score += 1
        elif turnover > 2.0:
            score -= 2
            evidence.append("换手过热")

    momentum = row.get("change_24h_pct")
    if momentum is not None and momentum >= 25:
        score -= 2
        evidence.append("短线过热")

    if row.get("sector_primary") == "Meme":
        score -= 1
        evidence.append("情绪属性偏强")

    if row.get("verify_grade") == "VerifiedStrong":
        score += 1
        evidence.append("价格验证强")

    if score >= 8:
        label = "PersistenceHigh"
        risk = "Low"
    elif score >= 5:
        label = "PersistenceMediumHigh"
        risk = "LowMedium"
    elif score >= 2:
        label = "PersistenceMedium"
        risk = "Medium"
    elif score >= -1:
        label = "PersistenceLow"
        risk = "MediumHigh"
    else:
        label = "PersistenceVeryLow"
        risk = "High"

    evidence_text = "；".join(evidence[:6]) if evidence else "证据不足"
    return {
        "persistence_score": score,
        "persistence_label": label,
        "continuation_risk": risk,
        "continuation_evidence": evidence_text,
    }




def compute_overlap_features(row):
    darkhorse_score = safe_float(row.get("darkhorse_score")) or 0.0
    persistence_score = safe_float(row.get("persistence_score")) or 0.0
    persistence_hours = safe_float(row.get("top15_persistence_hours")) or 0.0
    presence_ratio = safe_float(row.get("top15_presence_ratio_24h")) or 0.0
    drawdown = safe_float(row.get("max_drawdown_7d_pct"))
    trend_1d = row.get("trend_1d")
    trend_4h = row.get("trend_4h")
    continuation_risk = row.get("continuation_risk")

    gate_pass = (
        darkhorse_score >= 7
        and persistence_score >= 5
        and persistence_hours >= 1
        and continuation_risk != "High"
        and trend_1d not in {"Down", "StrongDown"}
        and trend_4h not in {"Down", "StrongDown"}
    )

    score = 0
    evidence = []

    if darkhorse_score >= 10:
        score += 6
        evidence.append("黑马强度高")
    elif darkhorse_score >= 8:
        score += 5
        evidence.append("黑马强度较高")
    elif darkhorse_score >= 7:
        score += 4
        evidence.append("黑马达标")
    elif darkhorse_score >= 5:
        score += 2

    if persistence_score >= 8:
        score += 6
        evidence.append("持续走强强")
    elif persistence_score >= 6:
        score += 5
        evidence.append("持续走强较强")
    elif persistence_score >= 5:
        score += 4
        evidence.append("持续走强达标")
    elif persistence_score >= 3:
        score += 2

    if persistence_hours >= 6:
        score += 4
        evidence.append(f"TOP15连续在榜{persistence_hours:.1f}h")
    elif persistence_hours >= 3:
        score += 3
        evidence.append(f"TOP15连续在榜{persistence_hours:.1f}h")
    elif persistence_hours >= 1:
        score += 2
        evidence.append(f"TOP15连续在榜{persistence_hours:.1f}h")
    elif persistence_hours >= 0.5:
        score += 1

    if presence_ratio >= 0.75:
        score += 2
        evidence.append(f"24h在榜占比{presence_ratio:.2f}")
    elif presence_ratio >= 0.5:
        score += 1
        evidence.append(f"24h在榜占比{presence_ratio:.2f}")

    if trend_1d in {"Up", "StrongUp"}:
        score += 1
    if trend_4h in {"Up", "StrongUp"}:
        score += 1

    if drawdown is not None:
        if drawdown <= -25:
            score -= 2
            evidence.append("回撤偏深")
        elif drawdown <= -18:
            score -= 1

    if continuation_risk == "High":
        score -= 2
        evidence.append("延续风险高")
    elif continuation_risk == "MediumHigh":
        score -= 1

    if score >= 16:
        overlap_label = "OverlapElite"
        overlap_rank_signal = "高确定性交叉候选"
    elif score >= 13:
        overlap_label = "OverlapStrong"
        overlap_rank_signal = "强确认趋势候选"
    elif score >= 10:
        overlap_label = "OverlapConfirmed"
        overlap_rank_signal = "已确认跟踪候选"
    elif score >= 7:
        overlap_label = "OverlapWatch"
        overlap_rank_signal = "观察中候选"
    else:
        overlap_label = "OverlapWeak"
        overlap_rank_signal = "未确认候选"

    overlap_candidate = bool(gate_pass and score >= 10)

    if overlap_candidate:
        evidence_text = "；".join(evidence[:6]) if evidence else "黑马、持续走强与在榜时长共振"
    else:
        blockers = []
        if darkhorse_score < 7:
            blockers.append("黑马分未达标")
        if persistence_score < 5:
            blockers.append("持续走强分未达标")
        if persistence_hours < 1:
            blockers.append("在榜时长不足1h")
        if continuation_risk == "High":
            blockers.append("延续风险过高")
        if trend_1d in {"Down", "StrongDown"} or trend_4h in {"Down", "StrongDown"}:
            blockers.append("中周期趋势转弱")
        evidence_text = "；".join(blockers[:6]) if blockers else ("；".join(evidence[:6]) if evidence else "交叉确认不足")

    return {
        "overlap_gate_pass": gate_pass,
        "overlap_score": score,
        "overlap_label": overlap_label,
        "overlap_rank_signal": overlap_rank_signal,
        "overlap_candidate": overlap_candidate,
        "overlap_evidence": evidence_text,
    }

def build_display_rows(rows):
    display_rows = []
    for row in rows:
        display_rows.append({
            "snapshot_id": row.get("snapshot_id"),
            "captured_at_utc": row.get("captured_at_utc"),
            "captured_at_cst": row.get("captured_at_cst"),
            "rank_in_top15": row.get("top15_position"),
            "market_cap_rank": row.get("market_cap_rank"),
            "symbol": row.get("symbol"),
            "name": row.get("name"),
            "display_name": f"{row.get('symbol')} | {row.get('name')}",
            "asset_type": row.get("asset_type"),
            "sector_primary": row.get("sector_primary"),
            "narrative_tags": "|".join(row.get("narrative_tags_normalized") or []),
            "narrative_summary": row.get("narrative_summary"),
            "market_cap_usd": row.get("market_cap_usd"),
            "market_cap_band": row.get("market_cap_band"),
            "price_usd": row.get("price_usd"),
            "change_24h_pct": row.get("change_24h_pct"),
            "momentum_bucket": row.get("momentum_bucket"),
            "volume_24h_usd": row.get("volume_24h_usd"),
            "liquidity_bucket": row.get("liquidity_bucket"),
            "turnover_ratio_24h": row.get("turnover_ratio_24h"),
            "turnover_bucket": row.get("turnover_bucket"),
            "binance_status": row.get("binance_status"),
            "verify_grade": row.get("verify_grade"),
            "binance_pair": row.get("binance_pair"),
            "binance_quote_volume_usd": row.get("binance_quote_volume_usd"),
            "binance_trade_count_24h": row.get("binance_trade_count_24h"),
            "activity_bucket": row.get("activity_bucket"),
            "binance_perp_status": row.get("binance_perp_status"),
            "binance_perp_symbol": row.get("binance_perp_symbol"),
            "perp_quote_volume_24h": row.get("perp_quote_volume_24h"),
            "perp_trade_count_24h": row.get("perp_trade_count_24h"),
            "open_interest_value_usd_now": row.get("open_interest_value_usd_now"),
            "oi_change_15m_pct": row.get("oi_change_15m_pct"),
            "oi_change_1h_pct": row.get("oi_change_1h_pct"),
            "oi_change_4h_pct": row.get("oi_change_4h_pct"),
            "funding_rate_latest": row.get("funding_rate_latest"),
            "funding_rate_mean_24h": row.get("funding_rate_mean_24h"),
            "perp_to_spot_volume_ratio_24h": row.get("perp_to_spot_volume_ratio_24h"),
            "oi_to_perp_volume_ratio_24h": row.get("oi_to_perp_volume_ratio_24h"),
            "perp_premium_pct_vs_spot": row.get("perp_premium_pct_vs_spot"),
            "structure_front_high_price": row.get("structure_front_high_price"),
            "structure_stop_anchor_price": row.get("structure_stop_anchor_price"),
            "structure_atr_1h_pct": row.get("structure_atr_1h_pct"),
            "structure_snapshot_range_1h_pct": row.get("structure_snapshot_range_1h_pct"),
            "structure_vol_base_pct": row.get("structure_vol_base_pct"),
            "structure_vol_source": row.get("structure_vol_source"),
            "structure_stop_buffer_pct": row.get("structure_stop_buffer_pct"),
            "structure_stop_price": row.get("structure_stop_price"),
            "structure_stop_pct": row.get("structure_stop_pct"),
            "structure_target_price_r1": row.get("structure_target_price_r1"),
            "structure_stop_tradable": row.get("structure_stop_tradable"),
            "structure_stop_window_min_pct": row.get("structure_stop_window_min_pct"),
            "structure_stop_window_max_pct": row.get("structure_stop_window_max_pct"),
            "structure_grade": row.get("structure_grade"),
            "structure_state": row.get("structure_state"),
            "structure_score": row.get("structure_score"),
            "trend_1d": row.get("trend_1d"),
            "trend_4h": row.get("trend_4h"),
            "trend_1h": row.get("trend_1h"),
            "breakout_1h": row.get("breakout_1h"),
            "breakout_4h": row.get("breakout_4h"),
            "price_change_7d_pct": row.get("price_change_7d_pct"),
            "max_drawdown_7d_pct": row.get("max_drawdown_7d_pct"),
            "darkhorse_score": row.get("darkhorse_score"),
            "top5_potential": row.get("top5_potential"),
            "sustainability": row.get("sustainability"),
            "risk_reward_profile": row.get("risk_reward_profile"),
            "darkhorse_tag": row.get("darkhorse_tag"),
            "persistence_score": row.get("persistence_score"),
            "persistence_label": row.get("persistence_label"),
            "continuation_risk": row.get("continuation_risk"),
            "continuation_evidence": row.get("continuation_evidence"),
            "top15_persistence_hours": row.get("top15_persistence_hours"),
            "top15_presence_ratio_24h": row.get("top15_presence_ratio_24h"),
            "top15_presence_snapshots_24h": row.get("top15_presence_snapshots_24h"),
            "top15_snapshot_count_24h": row.get("top15_snapshot_count_24h"),
            "top15_observation_window_hours": row.get("top15_observation_window_hours"),
            "top15_snapshot_interval_hours_est": row.get("top15_snapshot_interval_hours_est"),
            "current_episode_start_utc": row.get("current_episode_start_utc"),
            "current_episode_start_cst": row.get("current_episode_start_cst"),
            "current_episode_duration_hours": row.get("current_episode_duration_hours"),
            "hours_to_top10": row.get("hours_to_top10"),
            "hours_to_top5": row.get("hours_to_top5"),
            "hours_to_top3": row.get("hours_to_top3"),
            "entry_to_confirmation_hours": row.get("entry_to_confirmation_hours"),
            "confirmation_lag_vs_top10_h": row.get("confirmation_lag_vs_top10_h"),
            "confirmation_lag_vs_top5_h": row.get("confirmation_lag_vs_top5_h"),
            "confirmation_lag_vs_top3_h": row.get("confirmation_lag_vs_top3_h"),
            "top10_to_top5_hours": row.get("top10_to_top5_hours"),
            "top5_to_top3_hours": row.get("top5_to_top3_hours"),
            "top3_to_confirmation_hours": row.get("top3_to_confirmation_hours"),
            "recent_overlap_candidate_2h": row.get("recent_overlap_candidate_2h"),
            "recent_overlap_window_hours": row.get("recent_overlap_window_hours"),
            "last_overlap_candidate_utc": row.get("last_overlap_candidate_utc"),
            "last_overlap_candidate_cst": row.get("last_overlap_candidate_cst"),
            "hours_since_last_overlap_candidate": row.get("hours_since_last_overlap_candidate"),
            "was_in_top15_15m_ago": row.get("was_in_top15_15m_ago"),
            "was_in_top15_30m_ago": row.get("was_in_top15_30m_ago"),
            "was_in_top15_60m_ago": row.get("was_in_top15_60m_ago"),
            "rank_change_15m": row.get("rank_change_15m"),
            "rank_change_30m": row.get("rank_change_30m"),
            "rank_change_60m": row.get("rank_change_60m"),
            "darkhorse_score_delta_30m": row.get("darkhorse_score_delta_30m"),
            "persistence_score_delta_30m": row.get("persistence_score_delta_30m"),
            "overlap_score_delta_30m": row.get("overlap_score_delta_30m"),
            "overlap_gate_pass": row.get("overlap_gate_pass"),
            "overlap_score": row.get("overlap_score"),
            "overlap_label": row.get("overlap_label"),
            "overlap_rank_signal": row.get("overlap_rank_signal"),
            "overlap_candidate": row.get("overlap_candidate"),
            "overlap_evidence": row.get("overlap_evidence"),
            "short_strategy_version": row.get("short_strategy_version"),
            "short_signal_name": row.get("short_signal_name"),
            "short_setup_tier": row.get("short_setup_tier"),
            "short_setup_label": row.get("short_setup_label"),
            "short_setup_openable": row.get("short_setup_openable"),
            "short_setup_quality_score": row.get("short_setup_quality_score"),
            "short_signal_openable": row.get("short_signal_openable"),
            "short_signal_quality_score": row.get("short_signal_quality_score"),
            "short_signal_summary": row.get("short_signal_summary"),
            "confirm_anchor_state": row.get("confirm_anchor_state"),
            "confirm_anchor_active": row.get("confirm_anchor_active"),
            "confirm_anchor_age_hours": row.get("confirm_anchor_age_hours"),
            "confirm_anchor_window_hours": row.get("confirm_anchor_window_hours"),
            "weakening_state": row.get("weakening_state"),
            "weakening_score": row.get("weakening_score"),
            "unwind_confirm_state": row.get("unwind_confirm_state"),
            "short_blockers": row.get("short_blockers"),
            "short_blocker_count": row.get("short_blocker_count"),
            "short_base_signal": row.get("short_base_signal"),
            "short_standard_ready": row.get("short_standard_ready"),
            "short_sniper_ready": row.get("short_sniper_ready"),
            "short_historical_default_confirm": row.get("short_historical_default_confirm"),
            "short_historical_sniper_confirm": row.get("short_historical_sniper_confirm"),
            "short_live_replacement_sniper": row.get("short_live_replacement_sniper"),
            "short_historical_default_status": row.get("short_historical_default_status"),
            "short_historical_sniper_status": row.get("short_historical_sniper_status"),
            "short_live_replacement_status": row.get("short_live_replacement_status"),
            "short_oi_expanding": row.get("short_oi_expanding"),
            "short_premium_deep_discount": row.get("short_premium_deep_discount"),
            "short_basis_weakening": row.get("short_basis_weakening"),
            "short_top_position_unwinding": row.get("short_top_position_unwinding"),
            "short_basis_extreme_discount": row.get("short_basis_extreme_discount"),
            "short_top_account_crowded": row.get("short_top_account_crowded"),
            "risk_flags": "|".join(row.get("risk_flags") or []),
            "website": row.get("website"),
            "explorer": row.get("explorer"),
        })
    return display_rows


def is_stablecoin_candidate(row):
    symbol = (row.get("symbol") or "").upper()
    name = (row.get("name") or "").strip().lower()
    if symbol in KNOWN_STABLECOIN_SYMBOLS:
        return True
    if name in KNOWN_STABLECOIN_NAMES:
        return True
    return False


def main():
    run_dt = now_utc()
    run_id = ts_slug(run_dt)
    captured_at_cst = run_dt.astimezone(CN_TZ).isoformat()

    cp = get_json("https://api.coinpaprika.com/v1/tickers")
    bn = get_json("https://api.binance.com/api/v3/ticker/24hr")
    bn_futures = fetch_binance_futures_24h()
    bn_by_symbol = {(r.get("symbol") or "").upper(): r for r in bn}
    bn_futures_by_symbol = {(r.get("symbol") or "").upper(): r for r in bn_futures}

    filtered = []
    for r in cp:
        q = (r.get("quotes") or {}).get("USD") or {}
        try:
            vol = float(q.get("volume_24h"))
            chg = float(q.get("percent_change_24h"))
            price = float(q.get("price"))
            mc = float(q.get("market_cap")) if q.get("market_cap") is not None else None
        except Exception:
            continue
        if vol > 15_000_000:
            row = {
                "coinpaprika_id": r.get("id"),
                "market_cap_rank": r.get("rank"),
                "name": r.get("name"),
                "symbol": (r.get("symbol") or "").upper(),
                "price_usd": price,
                "change_24h_pct": chg,
                "volume_24h_usd": vol,
                "market_cap_usd": mc,
                "source_last_updated": r.get("last_updated"),
            }
            if not is_stablecoin_candidate(row):
                filtered.append(row)
    filtered.sort(key=lambda x: x["change_24h_pct"], reverse=True)
    spot_eligible = []
    for row in filtered:
        symbol = row["symbol"]
        for q in BINANCE_SPOT_QUOTES:
            pair = f"{symbol}{q}"
            if pair in bn_by_symbol:
                row["pre_matched_binance_pair"] = pair
                spot_eligible.append(row)
                break
    top15 = spot_eligible[:15]

    cache = load_meta_cache()
    recent_history_rows = load_recent_top15_history(lookback_hours=24)
    final_rows = []
    kline_sync_summary = []
    perp_sync_summary = []
    for pos, row in enumerate(top15, start=1):
        meta = ensure_coin_meta(row["coinpaprika_id"], cache)
        if meta.get("sector_primary") == "Stablecoin":
            continue
        base = dict(row)
        base["snapshot_id"] = run_id
        base["captured_at_utc"] = run_dt.isoformat()
        base["captured_at_cst"] = captured_at_cst
        base["top15_position"] = pos
        base["filter_rule"] = "24h_volume_usd_gt_15m_excluding_stablecoins_binance_spot_only"
        base["source_primary"] = "CoinPaprika"
        base["source_verify"] = "Binance"
        base["turnover_ratio_24h"] = (base["volume_24h_usd"] / base["market_cap_usd"]) if base.get("market_cap_usd") else None
        base["liquidity_bucket"] = liquidity_bucket(base["volume_24h_usd"])
        base.update(meta)
        base["narrative_tags_normalized"] = normalize_narrative_tags(base.get("sector_primary"), base.get("sector_tags"), base.get("symbol") or "")
        base["market_cap_band"] = market_cap_band(base.get("market_cap_usd"))
        base["momentum_bucket"] = momentum_bucket(base.get("change_24h_pct"))
        base["turnover_bucket"] = turnover_bucket(base.get("turnover_ratio_24h"))

        symbol = base["symbol"]
        match = None
        matched_pair = None
        for q in BINANCE_SPOT_QUOTES:
            pair = f"{symbol}{q}"
            if pair in bn_by_symbol:
                matched_pair = pair
                match = bn_by_symbol[pair]
                break
        if match:
            binance_last_price = float(match.get("lastPrice")) if match.get("lastPrice") is not None else None
            binance_change = float(match.get("priceChangePercent")) if match.get("priceChangePercent") is not None else None
            binance_quote_volume = float(match.get("quoteVolume")) if match.get("quoteVolume") is not None else None
            binance_count = int(match.get("count")) if match.get("count") is not None else None
            base.update({
                "binance_status": "matched",
                "binance_pair": matched_pair,
                "binance_last_price": binance_last_price,
                "binance_change_24h_pct": binance_change,
                "binance_quote_volume_usd": binance_quote_volume,
                "binance_trade_count_24h": binance_count,
                "price_diff_pct_vs_binance": ((base["price_usd"] - binance_last_price) / binance_last_price * 100) if binance_last_price else None,
                "change_diff_pct_points_vs_binance": (base["change_24h_pct"] - binance_change) if binance_change is not None else None,
                "volume_vs_binance_ratio": (base["volume_24h_usd"] / binance_quote_volume) if binance_quote_volume else None,
                "activity_bucket": activity_bucket(binance_count, binance_quote_volume),
                "trade_activity_24h": binance_count,
            })
        else:
            base.update({
                "binance_status": "not_listed_or_no_usd_quote_found",
                "binance_pair": None,
                "binance_last_price": None,
                "binance_change_24h_pct": None,
                "binance_quote_volume_usd": None,
                "binance_trade_count_24h": None,
                "price_diff_pct_vs_binance": None,
                "change_diff_pct_points_vs_binance": None,
                "volume_vs_binance_ratio": None,
                "activity_bucket": "Unknown",
                "trade_activity_24h": None,
            })

        matched_perp_symbol, perp_match = resolve_binance_perp_symbol(symbol, bn_futures_by_symbol)
        perp_summary, perp_sync = sync_symbol_perp(symbol, matched_perp_symbol, perp_match, run_dt, run_id, captured_at_cst)
        perp_sync_summary.append(perp_sync)
        base.update(perp_summary)
        base["perp_to_spot_volume_ratio_24h"] = (
            base["perp_quote_volume_24h"] / base["binance_quote_volume_usd"]
        ) if (base.get("perp_quote_volume_24h") is not None and base.get("binance_quote_volume_usd")) else None
        base["oi_to_perp_volume_ratio_24h"] = (
            base["open_interest_value_usd_now"] / base["perp_quote_volume_24h"]
        ) if (base.get("open_interest_value_usd_now") is not None and base.get("perp_quote_volume_24h")) else None
        base["perp_premium_pct_vs_spot"] = (
            (base["perp_last_price"] - base["binance_last_price"]) / base["binance_last_price"] * 100
        ) if (base.get("perp_last_price") is not None and base.get("binance_last_price")) else None

        base["verify_grade"] = verify_grade(base.get("binance_status"), base.get("price_diff_pct_vs_binance"))
        base["risk_flags"] = build_risk_flags(base)
        if base.get("binance_status") == "matched" and base.get("binance_pair"):
            kline_sync_summary.append({
                "symbol": base.get("symbol"),
                "binance_pair": base.get("binance_pair"),
                "intervals": sync_symbol_klines(base.get("symbol"), base.get("binance_pair"), run_dt),
            })
        base.update(compute_structure_features(base.get("symbol")))
        base.update(compute_darkhorse_features(base))
        base.update(compute_persistence_features(base))
        base.update(compute_top15_presence_features(base.get("symbol"), recent_history_rows, run_dt, window_hours=24))
        base.update(compute_overlap_features(base))
        base["top15_position"] = len(final_rows) + 1
        base.update(compute_path_research_features(base, recent_history_rows, run_dt))
        base.update(compute_short_setup_fields(base))
        final_rows.append(base)

    for idx, row in enumerate(final_rows, start=1):
        row["top15_position"] = idx

    save_meta_cache(cache)

    raw_payload = {
        "snapshot_id": run_id,
        "captured_at_utc": run_dt.isoformat(),
        "captured_at_cst": captured_at_cst,
        "filter": "24h volume > 15,000,000 USD, stablecoins excluded, Binance spot only",
        "count_filtered": len(filtered),
        "top15": final_rows,
        "kline_sync_summary": kline_sync_summary,
        "perp_sync_summary": perp_sync_summary,
    }
    (RAW_DIR / f"{run_id}.json").write_text(json.dumps(raw_payload, ensure_ascii=False, indent=2), encoding="utf-8")

    fieldnames = [
        "snapshot_id","captured_at_utc","captured_at_cst","top15_position","filter_rule","source_primary","source_verify",
        "coinpaprika_id","market_cap_rank","name","symbol","asset_type","sector_primary","sector_tags","narrative_tags_normalized","narrative_summary",
        "price_usd","change_24h_pct","momentum_bucket","volume_24h_usd","market_cap_usd","market_cap_band",
        "turnover_ratio_24h","turnover_bucket","liquidity_bucket",
        "binance_status","verify_grade","binance_pair","binance_last_price","binance_change_24h_pct","binance_quote_volume_usd",
        "binance_trade_count_24h","activity_bucket","trade_activity_24h",
        "price_diff_pct_vs_binance","change_diff_pct_points_vs_binance","volume_vs_binance_ratio",
        "binance_perp_status","binance_perp_symbol","binance_perp_error",
        "perp_last_price","perp_change_24h_pct","perp_quote_volume_24h","perp_trade_count_24h",
        "open_interest_contracts_now","open_interest_value_usd_now","oi_hist_value_latest_usd",
        "oi_change_15m_pct","oi_change_1h_pct","oi_change_4h_pct",
        "funding_rate_latest","funding_rate_mean_24h","funding_time_latest_utc","funding_time_latest_cst",
        "oi_hist_latest_utc","oi_hist_latest_cst",
        "perp_to_spot_volume_ratio_24h","oi_to_perp_volume_ratio_24h","perp_premium_pct_vs_spot",
        "structure_front_high_price","structure_stop_anchor_price","structure_atr_1h_pct","structure_snapshot_range_1h_pct",
        "structure_vol_base_pct","structure_vol_source","structure_stop_buffer_pct","structure_stop_price",
        "structure_stop_pct","structure_target_price_r1","structure_stop_tradable",
        "structure_stop_window_min_pct","structure_stop_window_max_pct",
        "kline_window_days","kline_1h_bars","kline_4h_bars","kline_1d_bars",
        "price_change_7d_pct","price_change_4h_window_pct","price_change_1h_window_pct","max_drawdown_7d_pct",
        "trend_1d","trend_4h","trend_1h","breakout_1h","breakout_4h",
        "structure_score","structure_grade","structure_state",
        "darkhorse_score","top5_potential","sustainability","risk_reward_profile","darkhorse_tag",
        "persistence_score","persistence_label","continuation_risk","continuation_evidence",
        "top15_persistence_hours","top15_presence_ratio_24h","top15_presence_snapshots_24h","top15_snapshot_count_24h","top15_observation_window_hours","top15_snapshot_interval_hours_est",
        "current_episode_start_utc","current_episode_start_cst","current_episode_duration_hours",
        "hours_to_top10","hours_to_top5","hours_to_top3","entry_to_confirmation_hours",
        "confirmation_lag_vs_top10_h","confirmation_lag_vs_top5_h","confirmation_lag_vs_top3_h",
        "top10_to_top5_hours","top5_to_top3_hours","top3_to_confirmation_hours",
        "episode_snapshot_count","episode_best_rank","episode_worst_rank","episode_rank_improve_range",
        "episode_confirmation_snapshot_index","episode_confirmation_progress_ratio",
        "episode_best_rank_before_confirmation","episode_worst_rank_before_confirmation",
        "pre_confirmation_rank_range","pre_confirmation_rank_std",
        "pre_confirmation_top10_presence_ratio","pre_confirmation_top5_presence_ratio","pre_confirmation_top3_presence_ratio",
        "path_class_v2","recent_overlap_candidate_2h","recent_overlap_window_hours","last_overlap_candidate_utc","last_overlap_candidate_cst","hours_since_last_overlap_candidate",
        "was_in_top15_15m_ago","was_in_top15_30m_ago","was_in_top15_60m_ago",
        "rank_change_15m","rank_change_30m","rank_change_60m",
        "darkhorse_score_delta_30m","persistence_score_delta_30m","overlap_score_delta_30m",
        "overlap_gate_pass","overlap_score","overlap_label","overlap_rank_signal","overlap_candidate","overlap_evidence",
        "short_strategy_version","short_signal_name","short_setup_tier","short_setup_label",
        "short_setup_openable","short_setup_quality_score",
        "short_signal_openable","short_signal_quality_score","short_signal_summary",
        "confirm_anchor_state","confirm_anchor_active","confirm_anchor_age_hours","confirm_anchor_window_hours",
        "weakening_state","weakening_score","unwind_confirm_state","short_blockers","short_blocker_count",
        "short_base_signal","short_standard_ready","short_sniper_ready",
        "short_historical_default_confirm","short_historical_sniper_confirm","short_live_replacement_sniper",
        "short_historical_default_status","short_historical_sniper_status","short_live_replacement_status",
        "short_oi_expanding","short_premium_deep_discount","short_basis_weakening",
        "short_top_position_unwinding","short_basis_extreme_discount","short_top_account_crowded",
        "risk_flags","website","source_code","explorer","source_last_updated","meta_fetched_at"
    ]

    clean_csv = CLEAN_DIR / f"{run_id}.csv"
    clean_json = CLEAN_DIR / f"{run_id}.json"
    write_csv(clean_csv, final_rows, fieldnames)
    clean_json.write_text(json.dumps(final_rows, ensure_ascii=False, indent=2), encoding="utf-8")

    append_history_csv(HISTORY_CSV, final_rows, fieldnames)
    with HISTORY_JSONL.open("a", encoding="utf-8") as f:
        for row in final_rows:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")

    display_rows = build_display_rows(final_rows)
    display_fieldnames = [
        "snapshot_id","captured_at_utc","captured_at_cst","rank_in_top15","market_cap_rank","symbol","name","display_name",
        "asset_type","sector_primary","narrative_tags","narrative_summary",
        "market_cap_usd","market_cap_band","price_usd","change_24h_pct","momentum_bucket",
        "volume_24h_usd","liquidity_bucket","turnover_ratio_24h","turnover_bucket",
        "binance_status","verify_grade","binance_pair","binance_quote_volume_usd","binance_trade_count_24h","activity_bucket",
        "binance_perp_status","binance_perp_symbol","perp_quote_volume_24h","perp_trade_count_24h","open_interest_value_usd_now",
        "oi_change_15m_pct","oi_change_1h_pct","oi_change_4h_pct","funding_rate_latest","funding_rate_mean_24h",
        "perp_to_spot_volume_ratio_24h","oi_to_perp_volume_ratio_24h","perp_premium_pct_vs_spot",
        "structure_front_high_price","structure_stop_anchor_price","structure_atr_1h_pct","structure_snapshot_range_1h_pct",
        "structure_vol_base_pct","structure_vol_source","structure_stop_buffer_pct","structure_stop_price",
        "structure_stop_pct","structure_target_price_r1","structure_stop_tradable",
        "structure_stop_window_min_pct","structure_stop_window_max_pct",
        "structure_state","structure_grade","structure_score","trend_1d","trend_4h","trend_1h",
        "breakout_1h","breakout_4h","price_change_7d_pct","max_drawdown_7d_pct",
        "darkhorse_score","top5_potential","sustainability","risk_reward_profile","darkhorse_tag",
        "persistence_score","persistence_label","continuation_risk","continuation_evidence",
        "top15_persistence_hours","top15_presence_ratio_24h","top15_presence_snapshots_24h","top15_snapshot_count_24h","top15_observation_window_hours","top15_snapshot_interval_hours_est",
        "current_episode_start_utc","current_episode_start_cst","current_episode_duration_hours",
        "hours_to_top10","hours_to_top5","hours_to_top3","entry_to_confirmation_hours",
        "confirmation_lag_vs_top10_h","confirmation_lag_vs_top5_h","confirmation_lag_vs_top3_h",
        "top10_to_top5_hours","top5_to_top3_hours","top3_to_confirmation_hours",
        "episode_snapshot_count","episode_best_rank","episode_worst_rank","episode_rank_improve_range",
        "episode_confirmation_snapshot_index","episode_confirmation_progress_ratio",
        "episode_best_rank_before_confirmation","episode_worst_rank_before_confirmation",
        "pre_confirmation_rank_range","pre_confirmation_rank_std",
        "pre_confirmation_top10_presence_ratio","pre_confirmation_top5_presence_ratio","pre_confirmation_top3_presence_ratio",
        "path_class_v2","recent_overlap_candidate_2h","recent_overlap_window_hours","last_overlap_candidate_utc","last_overlap_candidate_cst","hours_since_last_overlap_candidate",
        "was_in_top15_15m_ago","was_in_top15_30m_ago","was_in_top15_60m_ago",
        "rank_change_15m","rank_change_30m","rank_change_60m",
        "darkhorse_score_delta_30m","persistence_score_delta_30m","overlap_score_delta_30m",
        "overlap_gate_pass","overlap_score","overlap_label","overlap_rank_signal","overlap_candidate","overlap_evidence",
        "short_strategy_version","short_signal_name","short_setup_tier","short_setup_label",
        "short_setup_openable","short_setup_quality_score",
        "short_signal_openable","short_signal_quality_score","short_signal_summary",
        "confirm_anchor_state","confirm_anchor_active","confirm_anchor_age_hours","confirm_anchor_window_hours",
        "weakening_state","weakening_score","unwind_confirm_state","short_blockers","short_blocker_count",
        "short_base_signal","short_standard_ready","short_sniper_ready",
        "short_historical_default_confirm","short_historical_sniper_confirm","short_live_replacement_sniper",
        "short_historical_default_status","short_historical_sniper_status","short_live_replacement_status",
        "short_oi_expanding","short_premium_deep_discount","short_basis_weakening",
        "short_top_position_unwinding","short_basis_extreme_discount","short_top_account_crowded",
        "risk_flags","website","explorer"
    ]
    display_csv = DISPLAY_SNAPSHOT_DIR / f"{run_id}.csv"
    write_csv(display_csv, display_rows, display_fieldnames)
    append_history_csv(HISTORY_DISPLAY_CSV, display_rows, display_fieldnames)
    write_csv(DISPLAY_DIR / "latest_display.csv", display_rows, display_fieldnames)
    (DISPLAY_DIR / "latest_display.json").write_text(json.dumps(display_rows, ensure_ascii=False, indent=2), encoding="utf-8")

    write_csv(LATEST_DIR / "latest.csv", final_rows, fieldnames)
    (LATEST_DIR / "latest.json").write_text(json.dumps(final_rows, ensure_ascii=False, indent=2), encoding="utf-8")
    paper_trader_payload = None
    paper_trader_error = PAPER_TRADER_IMPORT_ERROR
    if process_paper_trader_snapshot:
        try:
            paper_trader_payload = process_paper_trader_snapshot(
                final_rows,
                run_id,
                run_dt.isoformat(),
                captured_at_cst,
            )
            paper_trader_error = None
        except Exception as exc:
            paper_trader_error = repr(exc)

    (LATEST_DIR / "manifest.json").write_text(json.dumps({
        "latest_snapshot_id": run_id,
        "captured_at_utc": run_dt.isoformat(),
        "captured_at_cst": captured_at_cst,
        "count_filtered": len(filtered),
        "top15_count": len(final_rows),
        "paper_trader": {
            "ok": paper_trader_error is None,
            "error": paper_trader_error,
            "last_processed_snapshot_id": (
                (paper_trader_payload or {}).get("last_processed_snapshot_id")
                if isinstance(paper_trader_payload, dict)
                else None
            ),
        },
        "paths": {
            "raw_json": str((RAW_DIR / f"{run_id}.json").relative_to(WORKDIR)),
            "clean_csv": str(clean_csv.relative_to(WORKDIR)),
            "clean_json": str(clean_json.relative_to(WORKDIR)),
            "display_csv": str(display_csv.relative_to(WORKDIR)),
            "latest_display_csv": str((DISPLAY_DIR / 'latest_display.csv').relative_to(WORKDIR)),
            "history_csv": str(HISTORY_CSV.relative_to(WORKDIR)),
            "history_display_csv": str(HISTORY_DISPLAY_CSV.relative_to(WORKDIR)),
            "history_jsonl": str(HISTORY_JSONL.relative_to(WORKDIR)),
            "klines_dir": str(KLINES_DIR.relative_to(WORKDIR)),
            "klines_meta_dir": str(KLINES_META_DIR.relative_to(WORKDIR)),
            "perp_snapshots_dir": str(PERP_SNAPSHOTS_DIR.relative_to(WORKDIR)),
            "perp_meta_dir": str(PERP_META_DIR.relative_to(WORKDIR)),
            "paper_trader_latest_json": (
                str(PAPER_TRADER_LATEST_PATH.relative_to(WORKDIR))
                if PAPER_TRADER_LATEST_PATH
                else None
            ),
            "paper_trader_state_json": (
                str(PAPER_TRADER_STATE_PATH.relative_to(WORKDIR))
                if PAPER_TRADER_STATE_PATH
                else None
            ),
            "paper_trader_orders_csv": (
                str(PAPER_TRADER_ORDERS_CSV_PATH.relative_to(WORKDIR))
                if PAPER_TRADER_ORDERS_CSV_PATH
                else None
            ),
            "paper_trader_equity_curve_csv": (
                str(PAPER_TRADER_EQUITY_CURVE_CSV_PATH.relative_to(WORKDIR))
                if PAPER_TRADER_EQUITY_CURVE_CSV_PATH
                else None
            ),
        }
    }, ensure_ascii=False, indent=2), encoding="utf-8")

    print(json.dumps({
        "ok": True,
        "snapshot_id": run_id,
        "count_filtered": len(filtered),
        "top15_count": len(final_rows),
        "latest_csv": str((LATEST_DIR / 'latest.csv').relative_to(WORKDIR)),
        "latest_display_csv": str((DISPLAY_DIR / 'latest_display.csv').relative_to(WORKDIR)),
        "history_csv": str(HISTORY_CSV.relative_to(WORKDIR)),
        "history_display_csv": str(HISTORY_DISPLAY_CSV.relative_to(WORKDIR)),
        "kline_sync_summary": kline_sync_summary,
        "perp_sync_summary": perp_sync_summary,
        "paper_trader": {
            "ok": paper_trader_error is None,
            "error": paper_trader_error,
            "last_processed_snapshot_id": (
                (paper_trader_payload or {}).get("last_processed_snapshot_id")
                if isinstance(paper_trader_payload, dict)
                else None
            ),
            "summary": (
                (paper_trader_payload or {}).get("summary")
                if isinstance(paper_trader_payload, dict)
                else None
            ),
        },
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print(json.dumps({"ok": False, "error": repr(e)}), file=sys.stderr)
        raise
