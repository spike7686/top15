#!/usr/bin/env python3
from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path

import run_wave_short_kline_backtest as base
import run_wave_short_perp_context_loader as ctx
import run_wave_short_1h_A_profit_expansion_matrix as exits
import run_wave_short_1h_breakdown_continuation_study as bd
import run_wave_short_1h_rebuild_then_dump_study as rb


LAB_DIR = Path(__file__).resolve().parent
OUTPUT_DIR = LAB_DIR / "output"
OUTPUT_JSON_PATH = OUTPUT_DIR / "wave_short_1h_continuation_exit_study_latest.json"
OUTPUT_MD_PATH = OUTPUT_DIR / "wave_short_1h_continuation_exit_study_latest.md"

STARTING_EQUITY_USD = 10000.0


@dataclass(frozen=True)
class EntryFamily:
    family_id: str
    description: str
    priority: int


ENTRY_FAMILIES = [
    EntryFamily(
        family_id="breakdown_failed_reclaim",
        description="急跌后弱反弹到 21EMA 附近再失败。",
        priority=1,
    ),
    EntryFamily(
        family_id="rebuild_retop",
        description="重新组织一轮大反弹，靠近旧高后第二次转弱。",
        priority=2,
    ),
    EntryFamily(
        family_id="breakdown_flag_break",
        description="破位后小平台续跌下破。",
        priority=3,
    ),
]


EXIT_VARIANTS = [
    next(item for item in exits.EXIT_VARIANTS if item.variant_id == "baseline_12h_tail"),
    next(item for item in exits.EXIT_VARIANTS if item.variant_id == "slow_resume_21ema_3bar"),
    next(item for item in exits.EXIT_VARIANTS if item.variant_id == "ultra_tail_21ema_4bar"),
    next(item for item in exits.EXIT_VARIANTS if item.variant_id == "profit_mode_4pct_lock15"),
    next(item for item in exits.EXIT_VARIANTS if item.variant_id == "profit_mode_6pct_lock30"),
    next(item for item in exits.EXIT_VARIANTS if item.variant_id == "profit_mode_4pct_lock20_55ema"),
    exits.ProfitExitVariant(
        variant_id="cont_trend_55ema_24h",
        description="Continuation 专用：最少持有 24h，1R 只落 15%，盈利后看 55EMA 恢复，偏向吃二段长尾。",
        min_hold_hours=24.0,
        max_hold_hours=144.0,
        tp1_r=1.0,
        tp1_ratio=0.15,
        tp2_r=6.0,
        resume_ma_period=21,
        resume_confirm_bars=3,
        profit_mode_trigger_pct=5.0,
        profit_mode_resume_ma_period=55,
        profit_mode_resume_confirm_bars=2,
        profit_mode_lock_pct=2.0,
    ),
    exits.ProfitExitVariant(
        variant_id="cont_loose_21ema_18h",
        description="Continuation 专用：最少持有 18h，1R 先落 20%，21EMA 3 根确认才出。",
        min_hold_hours=18.0,
        max_hold_hours=120.0,
        tp1_r=1.0,
        tp1_ratio=0.20,
        tp2_r=5.0,
        resume_ma_period=21,
        resume_confirm_bars=3,
        profit_mode_trigger_pct=4.0,
        profit_mode_resume_ma_period=21,
        profit_mode_resume_confirm_bars=4,
        profit_mode_lock_pct=1.5,
    ),
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
    if trade_count >= 6:
        return 1.5
    if trade_count >= 4:
        return 4.0
    if trade_count >= 2:
        return 7.0
    return 10.0


def attach_family(item, family_id):
    return {
        **item,
        "family_id": family_id,
    }


def build_candidate_universe(base_trade_infos):
    breakdown_failed_reclaim = next(x for x in bd.ENTRY_SPECS if x.spec_id == "failed_reclaim_ema21")
    breakdown_flag_break = next(x for x in bd.ENTRY_SPECS if x.spec_id == "flag_break_core")
    rebuild_retop = next(x for x in rb.ENTRY_SPECS if x.spec_id == "retop_near_anchor")

    raw = []
    raw.extend(attach_family(item, "breakdown_failed_reclaim") for item in bd.generate_breakdown_candidates(base_trade_infos, breakdown_failed_reclaim))
    raw.extend(attach_family(item, "breakdown_flag_break") for item in bd.generate_breakdown_candidates(base_trade_infos, breakdown_flag_break))
    raw.extend(attach_family(item, "rebuild_retop") for item in rb.generate_rebuild_candidates(base_trade_infos, rebuild_retop))

    priority = {item.family_id: item.priority for item in ENTRY_FAMILIES}
    deduped = {}
    for item in sorted(raw, key=lambda x: (x["signal"]["entry_dt"], priority[x["family_id"]])):
        key = (item["state"]["symbol"], item["signal"]["entry_dt"].isoformat())
        current = deduped.get(key)
        if current is None or priority[item["family_id"]] < priority[current["family_id"]]:
            deduped[key] = item
    return list(sorted(deduped.values(), key=lambda x: x["signal"]["entry_dt"]))


def run_sequence(base_events, continuation_candidates, exit_variant):
    equity_usd = STARTING_EQUITY_USD
    peak = equity_usd
    max_dd = 0.0
    open_until_by_symbol = {}
    continuation_trades = []
    combined_trades = []
    exit_code_counts = {}

    base_items = [
        {
            "kind": "base",
            "symbol": item["state"]["symbol"],
            "entry_dt": item["signal"]["entry_dt"],
            "base_trade": item["trade"],
        }
        for item in base_events
    ]
    cont_items = [
        {
            "kind": "continuation",
            "symbol": item["state"]["symbol"],
            "entry_dt": item["signal"]["entry_dt"],
            "candidate": item,
        }
        for item in continuation_candidates
    ]
    events = sorted([*base_items, *cont_items], key=lambda x: x["entry_dt"])

    for event in events:
        symbol = event["symbol"]
        blocked_until = open_until_by_symbol.get(symbol)
        if blocked_until and event["entry_dt"] < blocked_until:
            continue

        if event["kind"] == "base":
            trade = dict(event["base_trade"])
        else:
            candidate = event["candidate"]
            trade = exits.simulate_trade(candidate["state"], candidate["index"], candidate["signal"], equity_usd, exit_variant)
            if not trade:
                continue
            trade["entry_kind"] = "continuation"
            trade["family_id"] = candidate["family_id"]
            trade["signal"]["base_anchor_entry_dt"] = candidate["signal"].get("base_anchor_entry_dt")
            trade["signal"]["base_anchor_exit_dt"] = candidate["signal"].get("base_anchor_exit_dt")

        combined_trades.append(trade)
        equity_usd += trade["realized_pnl_usd"]
        peak = max(peak, equity_usd)
        dd = ((peak - equity_usd) / peak * 100.0) if peak else 0.0
        max_dd = max(max_dd, dd)
        open_until_by_symbol[symbol] = datetime.fromisoformat(trade["exit_dt"]) if trade["exit_dt"] else None
        exit_code_counts[trade["exit_code"]] = exit_code_counts.get(trade["exit_code"], 0) + 1
        if event["kind"] == "continuation":
            continuation_trades.append(trade)

    cont_returns = [t["realized_return_pct"] for t in continuation_trades]
    cont_best = [t["best_path_return_pct"] for t in continuation_trades]
    continuation_return_pct = sum((t["realized_pnl_usd"] for t in continuation_trades), 0.0) / STARTING_EQUITY_USD * 100.0
    family_breakdown = {}
    for family in ENTRY_FAMILIES:
        subset = [t for t in continuation_trades if t.get("family_id") == family.family_id]
        family_breakdown[family.family_id] = {
            "trade_count": len(subset),
            "avg_return_pct": mean(t["realized_return_pct"] for t in subset),
            "avg_best_path_pct": mean(t["best_path_return_pct"] for t in subset),
            "win_rate": ratio_true((safe_float(t["realized_return_pct"]) or -999999.0) > 0 for t in subset),
        }

    research_score = (
        ((equity_usd - STARTING_EQUITY_USD) / STARTING_EQUITY_USD * 100.0)
        - max_dd * 0.6
        + (mean(cont_returns) or 0.0) * 1.8
        + min(len(continuation_trades), 10) * 0.5
        + (mean(cont_best) or 0.0) * 0.35
    )
    robust_research_score = research_score - robustness_penalty(len(continuation_trades))

    return {
        "combined": {
            "trade_count": len(combined_trades),
            "return_pct": (equity_usd - STARTING_EQUITY_USD) / STARTING_EQUITY_USD * 100.0,
            "max_drawdown_pct": max_dd,
            "win_rate": ratio_true((safe_float(t["realized_pnl_usd"]) or -999999.0) > 0 for t in combined_trades),
            "avg_realized_r": mean(t["realized_r"] for t in combined_trades),
        },
        "continuation_only": {
            "trade_count": len(continuation_trades),
            "return_pct": continuation_return_pct,
            "avg_return_pct": mean(cont_returns),
            "avg_best_path_pct": mean(cont_best),
            "win_rate": ratio_true((safe_float(x) or -999999.0) > 0 for x in cont_returns),
            "exit_code_counts": exit_code_counts,
            "family_breakdown": family_breakdown,
            "trades": continuation_trades,
        },
        "summary": {
            "combined_return_pct": (equity_usd - STARTING_EQUITY_USD) / STARTING_EQUITY_USD * 100.0,
            "combined_max_drawdown_pct": max_dd,
            "continuation_trade_count": len(continuation_trades),
            "continuation_return_pct": continuation_return_pct,
            "continuation_avg_return_pct": mean(cont_returns),
            "continuation_avg_best_path_pct": mean(cont_best),
            "research_score": research_score,
            "robust_research_score": robust_research_score,
        },
    }


def build_markdown(payload):
    ranked = sorted(payload["variants"], key=lambda x: x["summary"]["robust_research_score"], reverse=True)
    lines = [
        "# Continuation Exit Study",
        "",
        "## Goal",
        "",
        "- 不再研究 continuation 入场，而是研究 continuation 专用退出。",
        "- 候选池同时包含三类：`failed_reclaim`、`flag_break`、`rebuild_retop`。",
        "- 重点看能否减少 `strength_resume` 过早洗出，提升 XPLUSDT 这类二段空的兑现效率。",
        "",
        f"- Continuation candidate count: {payload['candidate_universe']['candidate_count']}",
        f"- Base executed trades: {payload['base_source']['executed_trade_count']}",
        "",
        "## Variant Summary",
        "",
        "| exit variant | cont trades | cont return | cont avg | cont best avg | combined return | combined DD | score |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for item in ranked:
        s = item["summary"]
        lines.append(
            "| {variant} | {trades} | {cont_ret:.2f}% | {avg_ret:.2f}% | {avg_best:.2f}% | {comb_ret:.2f}% | {comb_dd:.2f}% | {score:.2f} |".format(
                variant=item["variant_id"],
                trades=s["continuation_trade_count"],
                cont_ret=s["continuation_return_pct"] or 0.0,
                avg_ret=s["continuation_avg_return_pct"] or 0.0,
                avg_best=s["continuation_avg_best_path_pct"] or 0.0,
                comb_ret=s["combined_return_pct"] or 0.0,
                comb_dd=s["combined_max_drawdown_pct"] or 0.0,
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
                f"- Continuation trades: {best['summary']['continuation_trade_count']}",
                f"- Continuation return: {best['summary']['continuation_return_pct']:.2f}%",
                f"- Combined return: {best['summary']['combined_return_pct']:.2f}%",
                f"- Combined max drawdown: {best['summary']['combined_max_drawdown_pct']:.2f}%",
                "",
                "### Family Breakdown",
                "",
            ]
        )
        for family in ENTRY_FAMILIES:
            row = best["continuation_only"]["family_breakdown"][family.family_id]
            lines.append(
                "- `{family}` trades={count} avg_ret={avg_ret:.2f}% avg_best={avg_best:.2f}% win_rate={win:.1%}".format(
                    family=family.family_id,
                    count=row["trade_count"],
                    avg_ret=row["avg_return_pct"] or 0.0,
                    avg_best=row["avg_best_path_pct"] or 0.0,
                    win=row["win_rate"] or 0.0,
                )
            )
        xplus_rows = [t for t in best["continuation_only"]["trades"] if t["symbol"] == "XPLUSDT"]
        if xplus_rows:
            lines.extend(["", "### XPLUSDT", ""])
            for trade in xplus_rows:
                lines.append(
                    "- `{entry}` -> `{exit}` | realized={ret:.2f}% | best_path={bestp:.2f}% | exit=`{code}`".format(
                        entry=trade["entry_dt"],
                        exit=trade["exit_dt"],
                        ret=trade["realized_return_pct"] or 0.0,
                        bestp=trade["best_path_return_pct"] or 0.0,
                        code=trade["exit_code"],
                    )
                )
    return "\n".join(lines)


def main():
    states = ctx.load_perp_context_states()
    for state in states:
        state["snapshots"] = bd.matrix.compute_state_snapshots(state)

    raw_signals, clusters, selected_signals = bd.build_base_signal_items(states)
    base_trade_infos = bd.build_base_trade_infos(selected_signals)
    base_events = [
        {
            "kind": "base",
            "state": info["state"],
            "index": info["index"],
            "signal": info["signal"],
            "trade": info["trade"],
        }
        for info in base_trade_infos
    ]
    candidate_universe = build_candidate_universe(base_trade_infos)
    variants = []
    for exit_variant in EXIT_VARIANTS:
        result = run_sequence(base_events, candidate_universe, exit_variant)
        variants.append(
            {
                "variant_id": exit_variant.variant_id,
                "description": exit_variant.description,
                "config": asdict(exit_variant),
                **result,
            }
        )

    ranked = sorted(variants, key=lambda x: x["summary"]["robust_research_score"], reverse=True)
    payload = {
        "ok": True,
        "study_id": "wave_short_1h_continuation_exit_study_v1",
        "generated_at_utc": datetime.utcnow().isoformat() + "Z",
        "dataset": ctx.dataset_summary(states),
        "base_source": {
            "variant_id": bd.BASE_SIGNAL_VARIANT.variant_id,
            "raw_signal_count": len(raw_signals),
            "cluster_count": len(clusters),
            "selected_signal_count": len(selected_signals),
            "executed_trade_count": len(base_trade_infos),
        },
        "candidate_universe": {
            "candidate_count": len(candidate_universe),
            "family_counts": {
                family.family_id: sum(1 for item in candidate_universe if item["family_id"] == family.family_id)
                for family in ENTRY_FAMILIES
            },
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
