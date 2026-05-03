#!/usr/bin/env python3
from __future__ import annotations

import json
import statistics
from bisect import bisect_left
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta
from pathlib import Path

import run_wave_short_kline_backtest as base
import run_wave_short_perp_context_loader as ctx
import run_wave_short_1h_oi_failure_swing_matrix as matrix
import run_wave_short_1h_oi_softscore_study as soft


LAB_DIR = Path(__file__).resolve().parent
OUTPUT_DIR = LAB_DIR / "output"
OUTPUT_JSON_PATH = OUTPUT_DIR / "wave_short_1h_rebuild_then_dump_study_latest.json"
OUTPUT_MD_PATH = OUTPUT_DIR / "wave_short_1h_rebuild_then_dump_study_latest.md"

STARTING_EQUITY_USD = 10000.0

BASE_SIGNAL_VARIANT = soft.ResearchVariant(
    variant_id="core_cap_runup_oi_first",
    description="A 层最优入场，作为 rebuild-then-dump 锚点来源。",
    entry_profile_id="entry_core",
    stop_profile_id="stop_balanced",
    exit_profile_id="exit_12h_tail",
    max_runup_24h_pct=18.0,
    max_oi_12h_pct=18.0,
    max_oi_24h_pct=24.0,
    max_oi_to_vol_ratio=1.10,
    ranker_id="first_signal",
)


@dataclass(frozen=True)
class RebuildEntrySpec:
    spec_id: str
    description: str
    min_wait_hours_after_base_exit: float
    max_search_hours_after_base_exit: float
    rebound_lookback_hours: int
    min_rebound_pct: float
    min_anchor_gap_pct: float
    max_anchor_gap_pct: float
    min_weakness_score: int
    require_ema8_below_ema21: bool
    require_close_below_prev_low: bool
    require_breakdown_after_rebound: bool
    max_oi_12h_pct: float | None
    stop_floor_pct: float
    stop_cap_pct: float
    stop_atr_buffer_mult: float


@dataclass(frozen=True)
class RebuildVariant:
    variant_id: str
    description: str
    entry: RebuildEntrySpec
    exit: matrix.ExitProfile


ENTRY_SPECS = [
    RebuildEntrySpec(
        spec_id="retop_near_anchor",
        description="二次冲顶失败：A 层退出后重新反弹 12%+，回到旧高附近，再次转弱跌破局部低点。",
        min_wait_hours_after_base_exit=12.0,
        max_search_hours_after_base_exit=336.0,
        rebound_lookback_hours=72,
        min_rebound_pct=12.0,
        min_anchor_gap_pct=-5.0,
        max_anchor_gap_pct=3.0,
        min_weakness_score=7,
        require_ema8_below_ema21=True,
        require_close_below_prev_low=True,
        require_breakdown_after_rebound=True,
        max_oi_12h_pct=1.5,
        stop_floor_pct=4.5,
        stop_cap_pct=12.0,
        stop_atr_buffer_mult=0.45,
    ),
    RebuildEntrySpec(
        spec_id="retop_broad",
        description="更宽的重建后再砸：允许离旧高还有一定距离，但要求反弹足够大且再次明显转弱。",
        min_wait_hours_after_base_exit=12.0,
        max_search_hours_after_base_exit=336.0,
        rebound_lookback_hours=96,
        min_rebound_pct=10.0,
        min_anchor_gap_pct=-6.0,
        max_anchor_gap_pct=10.0,
        min_weakness_score=6,
        require_ema8_below_ema21=True,
        require_close_below_prev_low=True,
        require_breakdown_after_rebound=True,
        max_oi_12h_pct=3.0,
        stop_floor_pct=4.5,
        stop_cap_pct=14.0,
        stop_atr_buffer_mult=0.50,
    ),
]


EXIT_VARIANTS = [
    next(item for item in matrix.EXIT_PROFILES if item.profile_id == "exit_12h_tail"),
    next(item for item in matrix.EXIT_PROFILES if item.profile_id == "exit_21ema_guard"),
]


VARIANTS = [
    RebuildVariant(
        variant_id=f"{entry.spec_id}__{exitv.profile_id}",
        description=f"{entry.description} {exitv.description}",
        entry=entry,
        exit=exitv,
    )
    for entry in ENTRY_SPECS
    for exitv in EXIT_VARIANTS
]


def safe_float(value):
    return base.safe_float(value)


def mean(values):
    cleaned = [safe_float(v) for v in values]
    cleaned = [v for v in cleaned if v is not None]
    return sum(cleaned) / len(cleaned) if cleaned else None


def ratio_true(values):
    vals = [v for v in values if v is not None]
    return sum(1 for v in vals if v) / len(vals) if vals else None


def robustness_penalty(trade_count):
    trade_count = int(trade_count or 0)
    if trade_count >= 8:
        return 0.0
    if trade_count >= 5:
        return 2.0
    if trade_count >= 3:
        return 5.0
    if trade_count >= 2:
        return 8.0
    return 10.0


def build_base_signal_items(states):
    entry_profile = next(x for x in matrix.ENTRY_PROFILES if x.profile_id == BASE_SIGNAL_VARIANT.entry_profile_id)
    stop_profile = next(x for x in matrix.STOP_PROFILES if x.profile_id == BASE_SIGNAL_VARIANT.stop_profile_id)
    raw_signals, clusters, selected_signals = soft.build_candidate_list(states, entry_profile, stop_profile, BASE_SIGNAL_VARIANT)
    return raw_signals, clusters, selected_signals


def build_base_trade_infos(selected_signals):
    base_trade_infos = []
    equity_usd = STARTING_EQUITY_USD
    open_until = None
    exit_profile = next(item for item in matrix.EXIT_PROFILES if item.profile_id == "exit_12h_tail")

    for item in selected_signals:
        sig_dt = item["signal"]["entry_dt"]
        if open_until and sig_dt < open_until:
            continue
        trade = matrix.simulate_trade(item["state"], item["index"], item["signal"], equity_usd, exit_profile)
        if not trade:
            continue
        equity_usd += trade["realized_pnl_usd"]
        open_until = datetime.fromisoformat(trade["exit_dt"]) if trade["exit_dt"] else None
        base_trade_infos.append(
            {
                "state": item["state"],
                "index": item["index"],
                "signal": item["signal"],
                "trade": trade,
                "anchor_peak_price": item["signal"]["peak_price"],
                "base_entry_dt": item["signal"]["entry_dt"],
                "base_exit_dt": datetime.fromisoformat(trade["exit_dt"]),
            }
        )
    return base_trade_infos


def generate_rebuild_candidates(base_trade_infos, entry_spec: RebuildEntrySpec):
    infos_by_symbol = {}
    for info in base_trade_infos:
        infos_by_symbol.setdefault(info["state"]["symbol"], []).append(info)
    for rows in infos_by_symbol.values():
        rows.sort(key=lambda item: item["base_entry_dt"])

    candidates = []
    for rows in infos_by_symbol.values():
        state = rows[0]["state"]
        one_h = state["1h"]
        close_times = state["1h_close_times"]

        for pos, anchor in enumerate(rows):
            search_start_dt = anchor["base_exit_dt"] + timedelta(hours=entry_spec.min_wait_hours_after_base_exit)
            search_end_dt = anchor["base_exit_dt"] + timedelta(hours=entry_spec.max_search_hours_after_base_exit)
            if pos + 1 < len(rows):
                next_base_dt = rows[pos + 1]["base_entry_dt"]
                search_end_dt = min(search_end_dt, next_base_dt - timedelta(hours=1))
            start_idx = bisect_left(close_times, search_start_dt)
            end_idx = bisect_left(close_times, search_end_dt)
            anchor_peak_price = anchor["anchor_peak_price"]
            anchor_idx_floor = anchor["index"] + 1
            found = None

            for j in range(max(start_idx, anchor_idx_floor + 10), min(end_idx + 1, len(one_h))):
                snap = state["snapshots"][j]
                if snap is None:
                    continue
                bar = one_h[j]

                if entry_spec.require_ema8_below_ema21 and not (state["ema8_1h"][j] < state["ema21_1h"][j]):
                    continue
                if entry_spec.require_close_below_prev_low and not snap.get("close_below_prev_low"):
                    continue
                if snap.get("weakness_score") is None or snap["weakness_score"] < entry_spec.min_weakness_score:
                    continue

                win_start = max(anchor_idx_floor, j - entry_spec.rebound_lookback_hours)
                win = one_h[win_start:j]
                if len(win) < 12:
                    continue
                rel_high_idx = max(range(len(win)), key=lambda k: win[k].high_price)
                if rel_high_idx < 4 or rel_high_idx >= len(win) - 1:
                    continue
                rebound_high_bar = win[rel_high_idx]
                rebound_high = rebound_high_bar.high_price
                rebound_high_abs_idx = win_start + rel_high_idx
                low_before = min(r.low_price for r in one_h[win_start:rebound_high_abs_idx + 1])
                if low_before in (None, 0):
                    continue

                rebound_pct = ((rebound_high / low_before) - 1.0) * 100.0
                anchor_gap_pct = ((anchor_peak_price - rebound_high) / anchor_peak_price) * 100.0 if anchor_peak_price else None
                if rebound_pct < entry_spec.min_rebound_pct:
                    continue
                if anchor_gap_pct is None or not (entry_spec.min_anchor_gap_pct <= anchor_gap_pct <= entry_spec.max_anchor_gap_pct):
                    continue

                if entry_spec.max_oi_12h_pct is not None:
                    oi_12h = snap.get("oi_12h_pct")
                    if oi_12h is None or oi_12h > entry_spec.max_oi_12h_pct:
                        continue

                if entry_spec.require_breakdown_after_rebound:
                    floor_window_start = max(rebound_high_abs_idx + 1, j - 8)
                    if floor_window_start >= j:
                        continue
                    prior_floor = min(r.low_price for r in one_h[floor_window_start:j])
                    if bar.close_price >= prior_floor:
                        continue
                else:
                    prior_floor = None

                atr_pct = snap.get("atr_1h_pct")
                stop_buffer_pct = max(matrix.MIN_BUFFER_PCT, (atr_pct or 0.0) * entry_spec.stop_atr_buffer_mult)
                raw_stop_price = rebound_high * (1.0 + stop_buffer_pct / 100.0)
                raw_stop_pct = ((raw_stop_price / bar.close_price) - 1.0) * 100.0 if bar.close_price else None
                if raw_stop_pct is None:
                    continue
                effective_stop_pct = max(entry_spec.stop_floor_pct, raw_stop_pct)
                if effective_stop_pct > entry_spec.stop_cap_pct:
                    continue
                stop_price = raw_stop_price if raw_stop_pct >= entry_spec.stop_floor_pct else bar.close_price * (1.0 + effective_stop_pct / 100.0)

                found = {
                    "kind": "rebuild_then_dump",
                    "state": state,
                    "index": j,
                    "signal": {
                        **snap,
                        "entry_dt": snap["entry_dt"],
                        "entry_price": snap["entry_price"],
                        "stop_pct": effective_stop_pct,
                        "stop_price": stop_price,
                        "rebound_pct": rebound_pct,
                        "anchor_gap_pct": anchor_gap_pct,
                        "rebound_high": rebound_high,
                        "base_anchor_entry_dt": anchor["base_entry_dt"].isoformat(),
                        "base_anchor_exit_dt": anchor["base_exit_dt"].isoformat(),
                    },
                }
                break
            if found:
                candidates.append(found)
    candidates.sort(key=lambda item: item["signal"]["entry_dt"])
    return candidates


def run_event_sequence(events):
    equity_usd = STARTING_EQUITY_USD
    peak = equity_usd
    max_dd = 0.0
    open_until_by_symbol = {}
    trades = []

    for item in events:
        symbol = item["state"]["symbol"]
        sig_dt = item["signal"]["entry_dt"]
        open_until = open_until_by_symbol.get(symbol)
        if open_until and sig_dt < open_until:
            continue
        trade = matrix.simulate_trade(item["state"], item["index"], item["signal"], equity_usd, item["exit_profile"])
        if not trade:
            continue
        trade["entry_kind"] = item["kind"]
        if item["kind"] == "rebuild_then_dump":
            trade["signal"]["rebound_pct"] = item["signal"]["rebound_pct"]
            trade["signal"]["anchor_gap_pct"] = item["signal"]["anchor_gap_pct"]
            trade["signal"]["base_anchor_entry_dt"] = item["signal"]["base_anchor_entry_dt"]
            trade["signal"]["base_anchor_exit_dt"] = item["signal"]["base_anchor_exit_dt"]
        trades.append(trade)
        equity_usd += trade["realized_pnl_usd"]
        peak = max(peak, equity_usd)
        dd = ((peak - equity_usd) / peak * 100.0) if peak else 0.0
        max_dd = max(max_dd, dd)
        open_until_by_symbol[symbol] = datetime.fromisoformat(trade["exit_dt"]) if trade["exit_dt"] else None

    pnl_values = [t["realized_pnl_usd"] for t in trades]
    hold_values = [t["hold_hours"] for t in trades]
    realized_r_values = [t["realized_r"] for t in trades]
    realized_pct_values = [t["realized_return_pct"] for t in trades]
    return {
        "trade_count": len(trades),
        "final_equity_usd": equity_usd,
        "return_pct": (equity_usd - STARTING_EQUITY_USD) / STARTING_EQUITY_USD * 100.0,
        "max_drawdown_pct": max_dd,
        "win_rate": ratio_true((safe_float(x) or -999999.0) > 0 for x in pnl_values),
        "avg_pnl_usd": mean(pnl_values),
        "avg_hold_hours": mean(hold_values),
        "avg_realized_r": mean(realized_r_values),
        "avg_realized_return_pct": mean(realized_pct_values),
        "trades": trades,
    }


def analyze_variant(base_events, variant: RebuildVariant):
    rebuild_events = []
    candidates = generate_rebuild_candidates(
        [
            {
                "state": item["state"],
                "index": item["index"],
                "signal": item["signal"],
                "trade": item["trade"],
                "anchor_peak_price": item["signal"]["peak_price"],
                "base_entry_dt": item["signal"]["entry_dt"],
                "base_exit_dt": datetime.fromisoformat(item["trade"]["exit_dt"]),
            }
            for item in base_events
        ],
        variant.entry,
    )
    for item in candidates:
        rebuild_events.append({**item, "exit_profile": variant.exit})

    continuation_only = run_event_sequence(rebuild_events)
    combined_events = sorted([*base_events, *rebuild_events], key=lambda item: item["signal"]["entry_dt"])
    combined = run_event_sequence(combined_events)

    cont_returns = [t["realized_return_pct"] for t in continuation_only["trades"]]
    cont_best = [t["best_path_return_pct"] for t in continuation_only["trades"]]
    research_score = (
        (combined["return_pct"] or 0.0)
        - (combined["max_drawdown_pct"] or 0.0) * 0.6
        + (mean(cont_returns) or 0.0) * 1.6
        + min(len(continuation_only["trades"]), 10) * 0.6
        + (mean(cont_best) or 0.0) * 0.3
    )
    robust_research_score = research_score - robustness_penalty(len(continuation_only["trades"]))

    return {
        "variant_id": variant.variant_id,
        "description": variant.description,
        "config": {"entry": asdict(variant.entry), "exit": asdict(variant.exit)},
        "summary": {
            "continuation_candidate_count": len(candidates),
            "continuation_trade_count": continuation_only["trade_count"],
            "continuation_return_pct": continuation_only["return_pct"],
            "continuation_max_drawdown_pct": continuation_only["max_drawdown_pct"],
            "combined_trade_count": combined["trade_count"],
            "combined_return_pct": combined["return_pct"],
            "combined_max_drawdown_pct": combined["max_drawdown_pct"],
            "combined_win_rate": combined["win_rate"],
            "combined_avg_realized_r": combined["avg_realized_r"],
            "research_score": research_score,
            "robust_research_score": robust_research_score,
        },
        "continuation_only": continuation_only,
        "combined": combined,
    }


def build_markdown(payload):
    ranked = sorted(payload["variants"], key=lambda item: item["summary"]["robust_research_score"], reverse=True)
    lines = [
        "# Rebuild Then Dump Study",
        "",
        "## Goal",
        "",
        "- 单独研究 A 层退出后再次大幅反弹、靠近旧高、然后第二次转弱的形态。",
        "- 对应 XPLUSDT / SPORTFUNUSDT / OPENUSDT 这类 `rebuild_then_dump` 机会。",
        "",
        f"- Base source variant: `{payload['base_source']['variant_id']}`",
        f"- Base executed trades: {payload['base_source']['executed_trade_count']}",
        "",
        "## Variant Summary",
        "",
        "| variant | cont candidates | cont trades | cont return | combined return | combined DD | combined trades | score |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for item in ranked:
        s = item["summary"]
        lines.append(
            "| {variant} | {cand} | {trades} | {cont_ret:.2f}% | {comb_ret:.2f}% | {comb_dd:.2f}% | {comb_trades} | {score:.2f} |".format(
                variant=item["variant_id"],
                cand=s["continuation_candidate_count"],
                trades=s["continuation_trade_count"],
                cont_ret=s["continuation_return_pct"] or 0.0,
                comb_ret=s["combined_return_pct"] or 0.0,
                comb_dd=s["combined_max_drawdown_pct"] or 0.0,
                comb_trades=s["combined_trade_count"],
                score=s["robust_research_score"] or 0.0,
            )
        )
    return "\n".join(lines)


def main():
    states = ctx.load_perp_context_states()
    for state in states:
        state["snapshots"] = matrix.compute_state_snapshots(state)

    raw_signals, clusters, selected_signals = build_base_signal_items(states)
    base_trade_infos = build_base_trade_infos(selected_signals)
    exit_profile = next(item for item in matrix.EXIT_PROFILES if item.profile_id == "exit_12h_tail")
    base_events = [
        {
            "kind": "base",
            "state": info["state"],
            "index": info["index"],
            "signal": info["signal"],
            "exit_profile": exit_profile,
            "trade": info["trade"],
        }
        for info in base_trade_infos
    ]

    variants = [analyze_variant(base_events, variant) for variant in VARIANTS]
    ranked = sorted(variants, key=lambda item: item["summary"]["robust_research_score"], reverse=True)

    payload = {
        "ok": True,
        "study_id": "wave_short_1h_rebuild_then_dump_study_v1",
        "generated_at_utc": datetime.utcnow().isoformat() + "Z",
        "dataset": ctx.dataset_summary(states),
        "base_source": {
            "variant_id": BASE_SIGNAL_VARIANT.variant_id,
            "raw_signal_count": len(raw_signals),
            "cluster_count": len(clusters),
            "selected_signal_count": len(selected_signals),
            "executed_trade_count": len(base_trade_infos),
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
