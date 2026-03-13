#!/usr/bin/env python3
import csv
import json
import re
import sys
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

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
META_CACHE_PATH = META_DIR / "coinpaprika_coin_cache.json"
HISTORY_JSONL = DATA_DIR / "history.jsonl"
HISTORY_CSV = DATA_DIR / "history.csv"
HISTORY_DISPLAY_CSV = DATA_DIR / "history_display.csv"

for p in [DATA_DIR, SNAPSHOT_DIR, LATEST_DIR, META_DIR, DISPLAY_DIR, RAW_DIR, CLEAN_DIR, DISPLAY_SNAPSHOT_DIR]:
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
    tags = set(sector_tags or [])
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


def append_history_csv(path: Path, rows, fieldnames):
    exists = path.exists()
    with path.open("a", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        if not exists:
            w.writeheader()
        for row in rows:
            w.writerow({k: row.get(k) for k in fieldnames})


def build_display_rows(rows):
    display_rows = []
    for row in rows:
        display_rows.append({
            "snapshot_id": row.get("snapshot_id"),
            "captured_at_utc": row.get("captured_at_utc"),
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
            "risk_flags": "|".join(row.get("risk_flags") or []),
            "website": row.get("website"),
            "explorer": row.get("explorer"),
        })
    return display_rows


def main():
    run_dt = now_utc()
    run_id = ts_slug(run_dt)

    cp = get_json("https://api.coinpaprika.com/v1/tickers")
    bn = get_json("https://api.binance.com/api/v3/ticker/24hr")
    bn_by_symbol = {(r.get("symbol") or "").upper(): r for r in bn}
    quotes = ["USDT", "FDUSD", "USDC", "BUSD", "TUSD"]

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
        if vol > 150_000_000:
            filtered.append({
                "coinpaprika_id": r.get("id"),
                "market_cap_rank": r.get("rank"),
                "name": r.get("name"),
                "symbol": (r.get("symbol") or "").upper(),
                "price_usd": price,
                "change_24h_pct": chg,
                "volume_24h_usd": vol,
                "market_cap_usd": mc,
                "source_last_updated": r.get("last_updated"),
            })
    filtered.sort(key=lambda x: x["change_24h_pct"], reverse=True)
    top15 = filtered[:15]

    cache = load_meta_cache()
    final_rows = []
    for pos, row in enumerate(top15, start=1):
        meta = ensure_coin_meta(row["coinpaprika_id"], cache)
        base = dict(row)
        base["snapshot_id"] = run_id
        base["captured_at_utc"] = run_dt.isoformat()
        base["top15_position"] = pos
        base["filter_rule"] = "24h_volume_usd_gt_150m"
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
        for q in quotes:
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

        base["verify_grade"] = verify_grade(base.get("binance_status"), base.get("price_diff_pct_vs_binance"))
        base["risk_flags"] = build_risk_flags(base)
        final_rows.append(base)

    save_meta_cache(cache)

    raw_payload = {
        "snapshot_id": run_id,
        "captured_at_utc": run_dt.isoformat(),
        "filter": "24h volume > 150,000,000 USD",
        "count_filtered": len(filtered),
        "top15": final_rows,
    }
    (RAW_DIR / f"{run_id}.json").write_text(json.dumps(raw_payload, ensure_ascii=False, indent=2), encoding="utf-8")

    fieldnames = [
        "snapshot_id","captured_at_utc","top15_position","filter_rule","source_primary","source_verify",
        "coinpaprika_id","market_cap_rank","name","symbol","asset_type","sector_primary","sector_tags","narrative_tags_normalized","narrative_summary",
        "price_usd","change_24h_pct","momentum_bucket","volume_24h_usd","market_cap_usd","market_cap_band",
        "turnover_ratio_24h","turnover_bucket","liquidity_bucket",
        "binance_status","verify_grade","binance_pair","binance_last_price","binance_change_24h_pct","binance_quote_volume_usd",
        "binance_trade_count_24h","activity_bucket","trade_activity_24h",
        "price_diff_pct_vs_binance","change_diff_pct_points_vs_binance","volume_vs_binance_ratio",
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
        "snapshot_id","captured_at_utc","rank_in_top15","market_cap_rank","symbol","name","display_name",
        "asset_type","sector_primary","narrative_tags","narrative_summary",
        "market_cap_usd","market_cap_band","price_usd","change_24h_pct","momentum_bucket",
        "volume_24h_usd","liquidity_bucket","turnover_ratio_24h","turnover_bucket",
        "binance_status","verify_grade","binance_pair","binance_quote_volume_usd","binance_trade_count_24h","activity_bucket",
        "risk_flags","website","explorer"
    ]
    display_csv = DISPLAY_SNAPSHOT_DIR / f"{run_id}.csv"
    write_csv(display_csv, display_rows, display_fieldnames)
    append_history_csv(HISTORY_DISPLAY_CSV, display_rows, display_fieldnames)
    write_csv(DISPLAY_DIR / "latest_display.csv", display_rows, display_fieldnames)
    (DISPLAY_DIR / "latest_display.json").write_text(json.dumps(display_rows, ensure_ascii=False, indent=2), encoding="utf-8")

    write_csv(LATEST_DIR / "latest.csv", final_rows, fieldnames)
    (LATEST_DIR / "latest.json").write_text(json.dumps(final_rows, ensure_ascii=False, indent=2), encoding="utf-8")
    (LATEST_DIR / "manifest.json").write_text(json.dumps({
        "latest_snapshot_id": run_id,
        "captured_at_utc": run_dt.isoformat(),
        "count_filtered": len(filtered),
        "top15_count": len(final_rows),
        "paths": {
            "raw_json": str((RAW_DIR / f"{run_id}.json").relative_to(WORKDIR)),
            "clean_csv": str(clean_csv.relative_to(WORKDIR)),
            "clean_json": str(clean_json.relative_to(WORKDIR)),
            "display_csv": str(display_csv.relative_to(WORKDIR)),
            "latest_display_csv": str((DISPLAY_DIR / 'latest_display.csv').relative_to(WORKDIR)),
            "history_csv": str(HISTORY_CSV.relative_to(WORKDIR)),
            "history_display_csv": str(HISTORY_DISPLAY_CSV.relative_to(WORKDIR)),
            "history_jsonl": str(HISTORY_JSONL.relative_to(WORKDIR)),
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
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print(json.dumps({"ok": False, "error": repr(e)}), file=sys.stderr)
        raise
