#!/usr/bin/env python3
from __future__ import annotations

import json
from bisect import bisect_left
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta
from pathlib import Path

import run_wave_short_kline_backtest as base
import run_wave_short_1h_continuation_exit_study as cexit
import run_wave_short_1h_rebuild_then_dump_study as rb


LAB_DIR = Path(__file__).resolve().parent
OUTPUT_DIR = LAB_DIR / "output"
OUTPUT_JSON_PATH = OUTPUT_DIR / "wave_short_1h_retop_shelf_breakdown_study_latest.json"
OUTPUT_MD_PATH = OUTPUT_DIR / "wave_short_1h_retop_shelf_breakdown_study_latest.md"

STARTING_EQUITY_USD = 10000.0
EXIT_VARIANT = next(x for x in cexit.EXIT_VARIANTS if x.variant_id == "profit_mode_4pct_lock20_55ema")


@dataclass(frozen=True)
class ShelfVariant:
    variant_id: str
    description: str
    min_rebound_pct: float
    min_anchor_gap_pct: float
    max_anchor_gap_pct: float
    shelf_min_hours: int
    shelf_max_range_pct: float
    require_ema8_flat_or_down: bool
    min_negative_close_count_last3: int
    max_oi_12h_pct: float | None = None


VARIANTS = [
    ShelfVariant(
        variant_id="shelf_break_core",
        description="反弹重建后形成 6h+ 窄平台，再失守平台下沿做空。",
        min_rebound_pct=12.0,
        min_anchor_gap_pct=-6.0,
        max_anchor_gap_pct=5.0,
        shelf_min_hours=6,
        shelf_max_range_pct=3.0,
        require_ema8_flat_or_down=True,
        min_negative_close_count_last3=2,
        max_oi_12h_pct=1.5,
    ),
    ShelfVariant(
        variant_id="shelf_break_loose",
        description="更宽松的平台失守：允许 4h 平台和更宽波动，专门覆盖 XPLUSDT 这类重建后阴跌破位。",
        min_rebound_pct=10.0,
        min_anchor_gap_pct=-8.0,
        max_anchor_gap_pct=6.0,
        shelf_min_hours=4,
        shelf_max_range_pct=4.5,
        require_ema8_flat_or_down=True,
        min_negative_close_count_last3=2,
        max_oi_12h_pct=3.0,
    ),
]


def safe_float(value):
    return base.safe_float(value)


def mean(values):
    vals = [safe_float(v) for v in values]
    vals = [v for v in vals if v is not None]
    return sum(vals) / len(vals) if vals else None


def robustness_penalty(trade_count):
    trade_count = int(trade_count or 0)
    if trade_count >= 4:
        return 0.0
    if trade_count >= 3:
        return 3.0
    if trade_count >= 2:
        return 6.0
    return 10.0


def negative_close_count(rows):
    return sum(1 for row in rows if row.close_price < row.open_price)


def build_base_trade_infos(states):
    _, _, selected = rb.build_base_signal_items(states)
    return rb.build_base_trade_infos(selected)


def generate_candidates(base_trade_infos, variant: ShelfVariant):
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
            search_start_dt = anchor["base_exit_dt"] + timedelta(hours=12)
            search_end_dt = anchor["base_exit_dt"] + timedelta(hours=14 * 24)
            if pos + 1 < len(rows):
                next_base_dt = rows[pos + 1]["base_entry_dt"]
                search_end_dt = min(search_end_dt, next_base_dt - timedelta(hours=1))
            start_idx = bisect_left(close_times, search_start_dt)
            end_idx = bisect_left(close_times, search_end_dt)
            anchor_peak = anchor["anchor_peak_price"]
            anchor_floor_idx = anchor["index"] + 1
            found = None

            for j in range(max(start_idx, anchor_floor_idx + 10), min(end_idx + 1, len(one_h))):
                snap = state["snapshots"][j]
                if snap is None:
                    continue
                if snap.get("weakness_score") is None or snap["weakness_score"] < 7:
                    continue
                if not snap.get("close_below_prev_low"):
                    continue
                if variant.max_oi_12h_pct is not None:
                    oi12 = snap.get("oi_12h_pct")
                    if oi12 is None or oi12 > variant.max_oi_12h_pct:
                        continue

                win_start = max(anchor_floor_idx, j - 96)
                win = one_h[win_start:j]
                if len(win) < 12:
                    continue
                rel_high_idx = max(range(len(win)), key=lambda k: win[k].high_price)
                rebound_high_bar = win[rel_high_idx]
                rebound_abs_idx = win_start + rel_high_idx
                low_before = min(r.low_price for r in one_h[win_start:rebound_abs_idx + 1])
                if low_before in (None, 0):
                    continue
                rebound_pct = ((rebound_high_bar.high_price / low_before) - 1.0) * 100.0
                anchor_gap_pct = ((anchor_peak - rebound_high_bar.high_price) / anchor_peak) * 100.0 if anchor_peak else None
                if rebound_pct < variant.min_rebound_pct:
                    continue
                if anchor_gap_pct is None or not (variant.min_anchor_gap_pct <= anchor_gap_pct <= variant.max_anchor_gap_pct):
                    continue

                shelf_start = max(rebound_abs_idx + 1, j - variant.shelf_min_hours)
                shelf = one_h[shelf_start:j]
                if len(shelf) < variant.shelf_min_hours:
                    continue
                shelf_high = max(r.high_price for r in shelf)
                shelf_low = min(r.low_price for r in shelf)
                shelf_range_pct = ((shelf_high - shelf_low) / shelf_high) * 100.0 if shelf_high else None
                if shelf_range_pct is None or shelf_range_pct > variant.shelf_max_range_pct:
                    continue
                if one_h[j].close_price >= shelf_low:
                    continue
                if negative_close_count(one_h[max(j - 3, 0):j]) < variant.min_negative_close_count_last3:
                    continue
                if variant.require_ema8_flat_or_down and state["ema8_1h"][j] > state["ema8_1h"][j - 1]:
                    continue

                atr_pct = snap.get("atr_1h_pct")
                stop_buffer_pct = max(rb.matrix.MIN_BUFFER_PCT, (atr_pct or 0.0) * 0.45)
                raw_stop_price = shelf_high * (1.0 + stop_buffer_pct / 100.0)
                raw_stop_pct = ((raw_stop_price / one_h[j].close_price) - 1.0) * 100.0 if one_h[j].close_price else None
                if raw_stop_pct is None:
                    continue
                stop_pct = max(4.5, raw_stop_pct)
                if stop_pct > 12.0:
                    continue
                stop_price = raw_stop_price if raw_stop_pct >= 4.5 else one_h[j].close_price * (1.0 + stop_pct / 100.0)

                found = {
                    "kind": "rebuild_retop",
                    "family_id": "rebuild_retop",
                    "state": state,
                    "index": j,
                    "signal": {
                        **snap,
                        "entry_dt": snap["entry_dt"],
                        "entry_price": snap["entry_price"],
                        "stop_pct": stop_pct,
                        "stop_price": stop_price,
                        "rebound_pct": rebound_pct,
                        "anchor_gap_pct": anchor_gap_pct,
                        "shelf_high": shelf_high,
                        "shelf_low": shelf_low,
                        "shelf_range_pct": shelf_range_pct,
                        "base_anchor_entry_dt": anchor["base_entry_dt"].isoformat(),
                        "base_anchor_exit_dt": anchor["base_exit_dt"].isoformat(),
                    },
                }
                break
            if found:
                candidates.append(found)
    candidates.sort(key=lambda x: x["signal"]["entry_dt"])
    return candidates


def run_variant(base_events, candidates, variant: ShelfVariant):
    payload = cexit.run_sequence(base_events, candidates, EXIT_VARIANT)
    returns = [t["realized_return_pct"] for t in payload["continuation_only"]["trades"]]
    bests = [t["best_path_return_pct"] for t in payload["continuation_only"]["trades"]]
    research_score = (
        (payload["summary"]["combined_return_pct"] or 0.0)
        - (payload["summary"]["combined_max_drawdown_pct"] or 0.0) * 0.6
        + (mean(returns) or 0.0) * 2.0
        + (mean(bests) or 0.0) * 0.4
    )
    robust_research_score = research_score - robustness_penalty(len(payload["continuation_only"]["trades"]))
    return {
        "variant_id": variant.variant_id,
        "description": variant.description,
        "config": asdict(variant),
        "selected_candidate_count": len(candidates),
        "summary": {
            **payload["summary"],
            "research_score": research_score,
            "robust_research_score": robust_research_score,
        },
        "combined": payload["combined"],
        "continuation_only": payload["continuation_only"],
    }


def build_markdown(payload):
    ranked = sorted(payload["variants"], key=lambda x: x["summary"]["robust_research_score"], reverse=True)
    lines = [
        "# Retop Shelf Breakdown Study",
        "",
        "## Goal",
        "",
        "- 研究 `rebuild -> shelf -> breakdown` 这一类二段空。",
        "- 固定使用当前 continuation 最优退出：`profit_mode_4pct_lock20_55ema`。",
        "- 重点验证这类平台失守是否比 `retop first weakness` 更接近 XPLUSDT。",
        "",
        "## Variant Summary",
        "",
        "| variant | selected | cont trades | cont return | cont avg | combined return | combined DD | score |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for item in ranked:
        s = item["summary"]
        lines.append(
            "| {variant} | {selected} | {trades} | {cont_ret:.2f}% | {avg_ret:.2f}% | {comb_ret:.2f}% | {comb_dd:.2f}% | {score:.2f} |".format(
                variant=item["variant_id"],
                selected=item["selected_candidate_count"],
                trades=s["continuation_trade_count"],
                cont_ret=s["continuation_return_pct"] or 0.0,
                avg_ret=s["continuation_avg_return_pct"] or 0.0,
                comb_ret=s["combined_return_pct"] or 0.0,
                comb_dd=s["combined_max_drawdown_pct"] or 0.0,
                score=s["robust_research_score"] or 0.0,
            )
        )
    return "\n".join(lines)


def main():
    states = rb.ctx.load_perp_context_states()
    for state in states:
        state["snapshots"] = rb.matrix.compute_state_snapshots(state)

    base_trade_infos = build_base_trade_infos(states)
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
    variants = []
    for variant in VARIANTS:
        candidates = generate_candidates(base_trade_infos, variant)
        variants.append(run_variant(base_events, candidates, variant))
    ranked = sorted(variants, key=lambda x: x["summary"]["robust_research_score"], reverse=True)

    payload = {
        "ok": True,
        "study_id": "wave_short_1h_retop_shelf_breakdown_study_v1",
        "generated_at_utc": datetime.utcnow().isoformat() + "Z",
        "dataset": rb.ctx.dataset_summary(states),
        "exit_variant": EXIT_VARIANT.variant_id,
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
