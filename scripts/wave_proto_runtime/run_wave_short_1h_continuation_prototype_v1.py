#!/usr/bin/env python3
from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path

import run_wave_short_kline_backtest as base
import run_wave_short_1h_breakdown_continuation_study as bd
import run_wave_short_1h_continuation_exit_study as cexit
import run_wave_short_1h_retop_shelf_breakdown_study as shelf


LAB_DIR = Path(__file__).resolve().parent
OUTPUT_DIR = LAB_DIR / "output"
OUTPUT_JSON_PATH = OUTPUT_DIR / "wave_short_1h_continuation_prototype_v1_latest.json"
OUTPUT_MD_PATH = OUTPUT_DIR / "wave_short_1h_continuation_prototype_v1_latest.md"

STARTING_EQUITY_USD = 10000.0
EXIT_VARIANT = next(x for x in cexit.EXIT_VARIANTS if x.variant_id == "profit_mode_4pct_lock20_55ema")


@dataclass(frozen=True)
class PrototypeConfig:
    config_id: str
    description: str
    use_failed_reclaim: bool
    use_shelf_break: bool
    max_oi_to_vol_ratio: float
    max_stop_pct: float
    min_impulse_or_pullback_pct: float
    require_pre12h_rebuild_nonnegative: bool
    require_pre24h_rebuild_nonnegative: bool


CONFIGS = [
    PrototypeConfig(
        config_id="proto_core",
        description="统一原型：保留 failed_reclaim 与 shelf_break，只做低拥挤、较强前置冲击、入场前有重组的 continuation。",
        use_failed_reclaim=True,
        use_shelf_break=True,
        max_oi_to_vol_ratio=0.90,
        max_stop_pct=5.5,
        min_impulse_or_pullback_pct=6.0,
        require_pre12h_rebuild_nonnegative=True,
        require_pre24h_rebuild_nonnegative=True,
    ),
    PrototypeConfig(
        config_id="proto_balanced",
        description="稍宽版统一原型：允许更多样本，但仍保留共性过滤。",
        use_failed_reclaim=True,
        use_shelf_break=True,
        max_oi_to_vol_ratio=1.00,
        max_stop_pct=6.0,
        min_impulse_or_pullback_pct=5.0,
        require_pre12h_rebuild_nonnegative=True,
        require_pre24h_rebuild_nonnegative=False,
    ),
    PrototypeConfig(
        config_id="proto_failed_reclaim_only",
        description="只保留目前最干净的 failed_reclaim 支路，作为保守基线。",
        use_failed_reclaim=True,
        use_shelf_break=False,
        max_oi_to_vol_ratio=1.10,
        max_stop_pct=6.0,
        min_impulse_or_pullback_pct=6.0,
        require_pre12h_rebuild_nonnegative=False,
        require_pre24h_rebuild_nonnegative=False,
    ),
]


def safe_float(value):
    return base.safe_float(value)


def mean(values):
    vals = [safe_float(v) for v in values]
    vals = [v for v in vals if v is not None]
    return sum(vals) / len(vals) if vals else None


def build_base_trade_infos(states):
    _, _, selected = bd.build_base_signal_items(states)
    return bd.build_base_trade_infos(selected)


def candidate_features(candidate):
    state = candidate["state"]
    j = candidate["index"]
    sig = candidate["signal"]
    rows = state["1h"]
    prev12 = rows[max(0, j - 12):j]
    prev24 = rows[max(0, j - 24):j]
    pre12_close_change = base.pct_change(prev12[0].close_price, prev12[-1].close_price) if len(prev12) >= 2 else None
    pre24_close_change = base.pct_change(prev24[0].close_price, prev24[-1].close_price) if len(prev24) >= 2 else None
    impulse_or_pullback = None
    for k in ["pullback_pct", "impulse_drop_pct", "rebound_pct"]:
        if sig.get(k) is not None:
            impulse_or_pullback = max(impulse_or_pullback or -999999.0, sig.get(k))
    return {
        "oi_to_vol_ratio": sig.get("oi_to_vol_ratio"),
        "stop_pct": sig.get("stop_pct"),
        "pre12h_close_change_pct": pre12_close_change,
        "pre24h_close_change_pct": pre24_close_change,
        "impulse_or_pullback_pct": impulse_or_pullback,
    }


def build_candidate_universe(base_trade_infos):
    failed_reclaim = next(x for x in bd.ENTRY_SPECS if x.spec_id == "failed_reclaim_ema21")
    shelf_break = next(x for x in shelf.VARIANTS if x.variant_id == "shelf_break_loose")

    raw = []
    raw.extend({**item, "family_id": "breakdown_failed_reclaim"} for item in bd.generate_breakdown_candidates(base_trade_infos, failed_reclaim))
    raw.extend({**item, "family_id": "rebuild_shelf_break"} for item in shelf.generate_candidates(base_trade_infos, shelf_break))

    deduped = {}
    priority = {"breakdown_failed_reclaim": 1, "rebuild_shelf_break": 2}
    for item in sorted(raw, key=lambda x: (x["signal"]["entry_dt"], priority[x["family_id"]])):
        key = (item["state"]["symbol"], item["signal"]["entry_dt"].isoformat())
        cur = deduped.get(key)
        if cur is None or priority[item["family_id"]] < priority[cur["family_id"]]:
            deduped[key] = item
    return list(sorted(deduped.values(), key=lambda x: x["signal"]["entry_dt"]))


def filter_candidates(candidates, config: PrototypeConfig):
    filtered = []
    for item in candidates:
        family = item["family_id"]
        if family == "breakdown_failed_reclaim" and not config.use_failed_reclaim:
            continue
        if family == "rebuild_shelf_break" and not config.use_shelf_break:
            continue

        feat = candidate_features(item)
        if feat["oi_to_vol_ratio"] is None or feat["oi_to_vol_ratio"] > config.max_oi_to_vol_ratio:
            continue
        if feat["stop_pct"] is None or feat["stop_pct"] > config.max_stop_pct:
            continue
        if feat["impulse_or_pullback_pct"] is None or feat["impulse_or_pullback_pct"] < config.min_impulse_or_pullback_pct:
            continue
        if config.require_pre12h_rebuild_nonnegative and (feat["pre12h_close_change_pct"] is None or feat["pre12h_close_change_pct"] < 0):
            continue
        if config.require_pre24h_rebuild_nonnegative and (feat["pre24h_close_change_pct"] is None or feat["pre24h_close_change_pct"] < 0):
            continue

        filtered.append(item)
    return filtered


def run_config(base_events, candidates, config: PrototypeConfig):
    selected = filter_candidates(candidates, config)
    payload = cexit.run_sequence(base_events, selected, EXIT_VARIANT)
    returns = [t["realized_return_pct"] for t in payload["continuation_only"]["trades"]]
    bests = [t["best_path_return_pct"] for t in payload["continuation_only"]["trades"]]
    research_score = (
        (payload["summary"]["combined_return_pct"] or 0.0)
        - (payload["summary"]["combined_max_drawdown_pct"] or 0.0) * 0.6
        + (mean(returns) or 0.0) * 2.0
        + (mean(bests) or 0.0) * 0.4
    )
    return {
        "config_id": config.config_id,
        "description": config.description,
        "config": asdict(config),
        "selected_candidate_count": len(selected),
        "selected_candidates": [
            {
                "symbol": item["state"]["symbol"],
                "family_id": item["family_id"],
                "entry_dt": item["signal"]["entry_dt"].isoformat(),
                **candidate_features(item),
            }
            for item in selected
        ],
        "summary": {
            **payload["summary"],
            "research_score": research_score,
        },
        "combined": payload["combined"],
        "continuation_only": payload["continuation_only"],
    }


def build_markdown(payload):
    ranked = sorted(payload["configs"], key=lambda x: x["summary"]["research_score"], reverse=True)
    lines = [
        "# Continuation Prototype V1",
        "",
        "## Goal",
        "",
        "- 综合前序研究，把目前最可信的 continuation 子策略合成统一原型。",
        "- 子策略只保留：`breakdown_failed_reclaim` 与 `rebuild_shelf_break`。",
        "- 退出固定使用当前 continuation 最优：`profit_mode_4pct_lock20_55ema`。",
        "",
        "## Config Summary",
        "",
        "| config | selected | cont trades | cont return | cont avg | combined return | combined DD | score |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for item in ranked:
        s = item["summary"]
        lines.append(
            "| {config} | {selected} | {trades} | {cont_ret:.2f}% | {avg_ret:.2f}% | {comb_ret:.2f}% | {comb_dd:.2f}% | {score:.2f} |".format(
                config=item["config_id"],
                selected=item["selected_candidate_count"],
                trades=s["continuation_trade_count"],
                cont_ret=s["continuation_return_pct"] or 0.0,
                avg_ret=s["continuation_avg_return_pct"] or 0.0,
                comb_ret=s["combined_return_pct"] or 0.0,
                comb_dd=s["combined_max_drawdown_pct"] or 0.0,
                score=s["research_score"] or 0.0,
            )
        )
    if ranked:
        best = ranked[0]
        lines.extend(["", "## Best Config", ""])
        lines.append(f"- Config: `{best['config_id']}`")
        lines.append(f"- Description: {best['description']}")
        lines.append(f"- Selected candidates: {best['selected_candidate_count']}")
        lines.append(f"- Continuation return: {best['summary']['continuation_return_pct']:.2f}%")
        lines.append(f"- Combined return: {best['summary']['combined_return_pct']:.2f}%")
        lines.append(f"- Combined max drawdown: {best['summary']['combined_max_drawdown_pct']:.2f}%")
        lines.append("")
        lines.append("### Selected Candidates")
        lines.append("")
        for row in best["selected_candidates"]:
            lines.append(
                "- `{symbol}` `{family}` {entry} | stop={stop:.2f}% | oi/vol={oi:.2f} | pre12={p12:.2f}% | pre24={p24:.2f}% | impulse/pullback={ip:.2f}%".format(
                    symbol=row["symbol"],
                    family=row["family_id"],
                    entry=row["entry_dt"],
                    stop=row["stop_pct"] or 0.0,
                    oi=row["oi_to_vol_ratio"] or 0.0,
                    p12=row["pre12h_close_change_pct"] or 0.0,
                    p24=row["pre24h_close_change_pct"] or 0.0,
                    ip=row["impulse_or_pullback_pct"] or 0.0,
                )
            )
    return "\n".join(lines)


def main():
    states = bd.ctx.load_perp_context_states()
    for state in states:
        state["snapshots"] = bd.matrix.compute_state_snapshots(state)

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
    candidate_universe = build_candidate_universe(base_trade_infos)
    configs = [run_config(base_events, candidate_universe, config) for config in CONFIGS]
    ranked = sorted(configs, key=lambda x: x["summary"]["research_score"], reverse=True)

    payload = {
        "ok": True,
        "study_id": "wave_short_1h_continuation_prototype_v1",
        "generated_at_utc": datetime.utcnow().isoformat() + "Z",
        "dataset": bd.ctx.dataset_summary(states),
        "exit_variant": EXIT_VARIANT.variant_id,
        "candidate_universe_count": len(candidate_universe),
        "configs": configs,
        "top_config": {
            "config_id": ranked[0]["config_id"] if ranked else None,
            "research_score": ranked[0]["summary"]["research_score"] if ranked else None,
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
                "top_config": payload["top_config"],
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
