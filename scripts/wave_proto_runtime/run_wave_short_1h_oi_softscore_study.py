#!/usr/bin/env python3
from __future__ import annotations

import json
import statistics
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta
from pathlib import Path

import run_wave_short_kline_backtest as base
import run_wave_short_perp_context_loader as ctx
import run_wave_short_1h_oi_failure_swing_matrix as matrix


LAB_DIR = Path(__file__).resolve().parent
OUTPUT_DIR = LAB_DIR / "output"
OUTPUT_JSON_PATH = OUTPUT_DIR / "wave_short_1h_oi_softscore_study_latest.json"
OUTPUT_MD_PATH = OUTPUT_DIR / "wave_short_1h_oi_softscore_study_latest.md"

STARTING_EQUITY_USD = 10000.0
RISK_PCT = 4.0
MAX_GROSS_PCT = 200.0
ENTRY_COOLDOWN_HOURS = 12.0
CLUSTER_GAP_HOURS = 18.0


@dataclass(frozen=True)
class ResearchVariant:
    variant_id: str
    description: str
    entry_profile_id: str
    stop_profile_id: str
    exit_profile_id: str
    max_runup_24h_pct: float | None
    max_oi_12h_pct: float | None
    max_oi_24h_pct: float | None
    max_oi_to_vol_ratio: float | None
    ranker_id: str


ENTRY_PROFILE_IDS = ["entry_core", "entry_deeper_retrace"]
STOP_PROFILE_IDS = ["stop_balanced", "stop_wider"]
EXIT_PROFILE_IDS = ["exit_12h_tail", "exit_21ema_guard"]


VARIANTS = [
    ResearchVariant(
        variant_id="core_baseline_first",
        description="第一轮基线复刻，用作二轮对照。",
        entry_profile_id="entry_core",
        stop_profile_id="stop_balanced",
        exit_profile_id="exit_12h_tail",
        max_runup_24h_pct=None,
        max_oi_12h_pct=None,
        max_oi_24h_pct=None,
        max_oi_to_vol_ratio=None,
        ranker_id="first_signal",
    ),
    ResearchVariant(
        variant_id="core_cap_runup_oi_first",
        description="基线之上加过热上限，测试是否能去掉最晚最挤的顶部。",
        entry_profile_id="entry_core",
        stop_profile_id="stop_balanced",
        exit_profile_id="exit_12h_tail",
        max_runup_24h_pct=18.0,
        max_oi_12h_pct=18.0,
        max_oi_24h_pct=24.0,
        max_oi_to_vol_ratio=0.90,
        ranker_id="first_signal",
    ),
    ResearchVariant(
        variant_id="core_cap_runup_oi_softscore",
        description="加过热上限后，用 OI 软评分排序，优先做更像健康衰竭而非极端过热的顶部。",
        entry_profile_id="entry_core",
        stop_profile_id="stop_balanced",
        exit_profile_id="exit_12h_tail",
        max_runup_24h_pct=18.0,
        max_oi_12h_pct=18.0,
        max_oi_24h_pct=24.0,
        max_oi_to_vol_ratio=0.90,
        ranker_id="soft_oi_quality",
    ),
    ResearchVariant(
        variant_id="core_cap_runup_oi_conservative",
        description="更保守的上限与软评分，优先回避最热、最拥挤、最容易二次拉高的位置。",
        entry_profile_id="entry_core",
        stop_profile_id="stop_balanced",
        exit_profile_id="exit_21ema_guard",
        max_runup_24h_pct=17.0,
        max_oi_12h_pct=14.0,
        max_oi_24h_pct=20.0,
        max_oi_to_vol_ratio=0.75,
        ranker_id="soft_oi_quality",
    ),
    ResearchVariant(
        variant_id="deeper_baseline_first",
        description="更深回踩版本基线，作为低回撤对照。",
        entry_profile_id="entry_deeper_retrace",
        stop_profile_id="stop_balanced",
        exit_profile_id="exit_12h_tail",
        max_runup_24h_pct=None,
        max_oi_12h_pct=None,
        max_oi_24h_pct=None,
        max_oi_to_vol_ratio=None,
        ranker_id="first_signal",
    ),
    ResearchVariant(
        variant_id="deeper_cap_runup_oi_first",
        description="更深回踩 + 过热上限，测试是否进一步压缩回撤。",
        entry_profile_id="entry_deeper_retrace",
        stop_profile_id="stop_balanced",
        exit_profile_id="exit_12h_tail",
        max_runup_24h_pct=18.0,
        max_oi_12h_pct=16.0,
        max_oi_24h_pct=22.0,
        max_oi_to_vol_ratio=0.80,
        ranker_id="first_signal",
    ),
    ResearchVariant(
        variant_id="deeper_cap_runup_oi_softscore",
        description="更深回踩 + 过热上限 + OI 软评分，尝试保住高胜率同时增加样本质量。",
        entry_profile_id="entry_deeper_retrace",
        stop_profile_id="stop_balanced",
        exit_profile_id="exit_12h_tail",
        max_runup_24h_pct=18.0,
        max_oi_12h_pct=16.0,
        max_oi_24h_pct=22.0,
        max_oi_to_vol_ratio=0.80,
        ranker_id="soft_oi_quality",
    ),
    ResearchVariant(
        variant_id="deeper_wider_softscore",
        description="更深回踩 + 宽止损 + OI 软评分，保留顶部噪音容忍度。",
        entry_profile_id="entry_deeper_retrace",
        stop_profile_id="stop_wider",
        exit_profile_id="exit_12h_tail",
        max_runup_24h_pct=18.0,
        max_oi_12h_pct=16.0,
        max_oi_24h_pct=22.0,
        max_oi_to_vol_ratio=0.90,
        ranker_id="soft_oi_quality",
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


def resolve_position_notional(equity_usd, stop_pct):
    if stop_pct in (None, 0):
        return None
    risk_usd = equity_usd * (RISK_PCT / 100.0)
    gross_cap_usd = equity_usd * (MAX_GROSS_PCT / 100.0)
    return min(risk_usd / (stop_pct / 100.0), gross_cap_usd)


def get_profile(items, key, value):
    return next(item for item in items if getattr(item, key) == value)


def candidate_passes_caps(signal, variant: ResearchVariant):
    checks = [
        (variant.max_runup_24h_pct, signal.get("runup_24h_pct")),
        (variant.max_oi_12h_pct, signal.get("oi_12h_pct")),
        (variant.max_oi_24h_pct, signal.get("oi_24h_pct")),
        (variant.max_oi_to_vol_ratio, signal.get("oi_to_vol_ratio")),
    ]
    for cap, value in checks:
        if cap is not None and value is not None and value > cap:
            return False
    return True


def cluster_candidates(signals):
    if not signals:
        return []
    sorted_signals = sorted(signals, key=lambda item: item["signal"]["entry_dt"])
    clusters = [[sorted_signals[0]]]
    gap = timedelta(hours=CLUSTER_GAP_HOURS)
    for item in sorted_signals[1:]:
        prev_dt = clusters[-1][-1]["signal"]["entry_dt"]
        curr_dt = item["signal"]["entry_dt"]
        if curr_dt - prev_dt <= gap:
            clusters[-1].append(item)
        else:
            clusters.append([item])
    return clusters


def zscore(value, values):
    value = safe_float(value)
    vals = [safe_float(v) for v in values]
    vals = [v for v in vals if v is not None]
    if value is None or len(vals) < 2:
        return 0.0
    mu = sum(vals) / len(vals)
    sigma = statistics.pstdev(vals)
    if sigma == 0:
        return 0.0
    return (value - mu) / sigma


def soft_oi_quality_score(item, cluster):
    sig = item["signal"]
    cluster_signals = [x["signal"] for x in cluster]
    oi1_vals = [x.get("oi_1h_pct") for x in cluster_signals]
    oi12_vals = [x.get("oi_12h_pct") for x in cluster_signals]
    oi24_vals = [x.get("oi_24h_pct") for x in cluster_signals]
    ratio_vals = [x.get("oi_to_vol_ratio") for x in cluster_signals]
    retrace_vals = [x.get("retrace_from_peak_pct") for x in cluster_signals]
    runup_vals = [x.get("runup_24h_pct") for x in cluster_signals]

    score = 0.0
    score += zscore(sig.get("retrace_from_peak_pct"), retrace_vals) * 1.2
    score -= abs(zscore(sig.get("oi_1h_pct"), oi1_vals)) * 0.3
    score -= max(0.0, zscore(sig.get("oi_12h_pct"), oi12_vals)) * 1.1
    score -= max(0.0, zscore(sig.get("oi_24h_pct"), oi24_vals)) * 0.8
    score -= max(0.0, zscore(sig.get("oi_to_vol_ratio"), ratio_vals)) * 0.8
    score -= max(0.0, zscore(sig.get("runup_24h_pct"), runup_vals)) * 0.8
    return score


def pick_cluster_candidate(cluster, ranker_id):
    if ranker_id == "first_signal":
        return min(cluster, key=lambda item: item["signal"]["entry_dt"])
    if ranker_id == "soft_oi_quality":
        return max(cluster, key=lambda item: soft_oi_quality_score(item, cluster))
    raise ValueError(f"unsupported ranker: {ranker_id}")


def build_candidate_list(states, entry_profile, stop_profile, variant: ResearchVariant):
    cooldown = timedelta(hours=ENTRY_COOLDOWN_HOURS)
    raw_signals = []
    for state in states:
        active = False
        last_entry_dt = None
        for idx, snapshot in enumerate(state["snapshots"]):
            if snapshot is None:
                continue
            if not matrix.snapshot_matches_entry(snapshot, entry_profile):
                active = False
                continue
            signal = matrix.build_signal(snapshot, stop_profile)
            if not signal:
                active = False
                continue
            if not candidate_passes_caps(signal, variant):
                active = False
                continue
            if not active:
                if last_entry_dt is None or (signal["entry_dt"] - last_entry_dt) >= cooldown:
                    raw_signals.append({"state": state, "index": idx, "signal": signal})
                    last_entry_dt = signal["entry_dt"]
                    active = True
            else:
                continue
    clusters = cluster_candidates(raw_signals)
    picked = [pick_cluster_candidate(cluster, variant.ranker_id) for cluster in clusters]
    picked.sort(key=lambda item: item["signal"]["entry_dt"])
    return raw_signals, clusters, picked


def simulate_trade(state, entry_idx, signal, equity_usd, exit_profile):
    return matrix.simulate_trade(state, entry_idx, signal, equity_usd, exit_profile)


def run_variant(states, variant: ResearchVariant):
    entry_profile = get_profile(matrix.ENTRY_PROFILES, "profile_id", variant.entry_profile_id)
    stop_profile = get_profile(matrix.STOP_PROFILES, "profile_id", variant.stop_profile_id)
    exit_profile = get_profile(matrix.EXIT_PROFILES, "profile_id", variant.exit_profile_id)

    raw_signals, clusters, signals = build_candidate_list(states, entry_profile, stop_profile, variant)
    equity_usd = STARTING_EQUITY_USD
    peak = equity_usd
    max_dd = 0.0
    open_until = None
    trades = []
    equity_curve = []
    exit_code_counts = {}

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
    return {
        "variant_id": variant.variant_id,
        "description": variant.description,
        "config": asdict(variant),
        "summary": {
            "raw_signal_count": len(raw_signals),
            "cluster_count": len(clusters),
            "ranked_signal_count": len(signals),
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
            "stopout_count": stopout_count,
            "large_winner_count": large_winner_count,
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
        "# 1h OI Softscore Study",
        "",
        "## Goal",
        "",
        "- 不再把 OI 当硬开关，而是拿来做 `过热上限 + 同波排序`。",
        "- 目标是保留 1h failure swing 的长波段能力，同时砍掉最晚、最挤、最容易二次拉高的顶部单。",
        "",
        f"- Symbols loaded: {payload['dataset']['symbol_count']}",
        f"- Coverage: {payload['dataset']['start_at']} -> {payload['dataset']['end_at']}",
        "",
        "## Variant Summary",
        "",
        "| variant | return | max DD | trades | win rate | avg R | avg hold | clusters | score |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for item in ranked:
        s = item["summary"]
        lines.append(
            "| {variant} | {ret:.2f}% | {dd:.2f}% | {trades} | {win:.1f}% | {avg_r:.2f} | {hold:.2f}h | {clusters} | {score:.2f} |".format(
                variant=item["variant_id"],
                ret=s["return_pct"],
                dd=s["max_drawdown_pct"] or 0.0,
                trades=s["executed_trade_count"],
                win=(s["win_rate"] or 0.0) * 100.0,
                avg_r=s["avg_realized_r"] or 0.0,
                hold=s["avg_hold_hours"] or 0.0,
                clusters=s["cluster_count"],
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
                f"- Description: {best['description']}",
                f"- Return: {best['summary']['return_pct']:.2f}%",
                f"- Max drawdown: {best['summary']['max_drawdown_pct']:.2f}%",
                f"- Trades: {best['summary']['executed_trade_count']}",
                "",
                "### Sample Trades",
                "",
            ]
        )
        for trade in best["trades"][:12]:
            sig = trade["signal"]
            lines.append(
                "- `{symbol}` {entry} -> {exit} | {ret:.2f}% | {hold:.1f}h | `{code}` | runup={runup:.1f}% | oi12h={oi12:.1f}% | oi24h={oi24:.1f}%".format(
                    symbol=trade["symbol"],
                    entry=trade["entry_dt"],
                    exit=trade["exit_dt"],
                    ret=trade["realized_return_pct"] or 0.0,
                    hold=trade["hold_hours"] or 0.0,
                    code=trade["exit_code"],
                    runup=sig["runup_24h_pct"] or 0.0,
                    oi12=sig["oi_12h_pct"] or 0.0,
                    oi24=sig["oi_24h_pct"] or 0.0,
                )
            )
    return "\n".join(lines)


def main():
    states = ctx.load_perp_context_states()
    for state in states:
        state["snapshots"] = matrix.compute_state_snapshots(state)

    variants = [run_variant(states, variant) for variant in VARIANTS]
    ranked = sorted(variants, key=lambda item: item["summary"]["robust_research_score"], reverse=True)
    payload = {
        "ok": True,
        "study_id": "wave_short_1h_oi_softscore_study_v1",
        "generated_at_utc": datetime.utcnow().isoformat() + "Z",
        "dataset": ctx.dataset_summary(states),
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
