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
import run_wave_short_1h_oi_softscore_study as soft


LAB_DIR = Path(__file__).resolve().parent
OUTPUT_DIR = LAB_DIR / "output"
OUTPUT_JSON_PATH = OUTPUT_DIR / "wave_short_1h_A_profit_expansion_matrix_latest.json"
OUTPUT_MD_PATH = OUTPUT_DIR / "wave_short_1h_A_profit_expansion_matrix_latest.md"

STARTING_EQUITY_USD = 10000.0
RISK_PCT = 4.0
MAX_GROSS_PCT = 200.0

BASE_SIGNAL_VARIANT = soft.ResearchVariant(
    variant_id="core_cap_runup_oi_first",
    description="A 层最优已验证版本，只拿它的入场与过滤，不改信号集合。",
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
class ProfitExitVariant:
    variant_id: str
    description: str
    min_hold_hours: float
    max_hold_hours: float
    tp1_r: float
    tp1_ratio: float
    tp2_r: float
    resume_ma_period: int
    resume_confirm_bars: int
    profit_mode_trigger_pct: float | None = None
    profit_mode_resume_ma_period: int | None = None
    profit_mode_resume_confirm_bars: int | None = None
    profit_mode_lock_pct: float | None = None


EXIT_VARIANTS = [
    ProfitExitVariant(
        variant_id="baseline_12h_tail",
        description="当前 A 层基线：12h_tail。",
        min_hold_hours=12.0,
        max_hold_hours=72.0,
        tp1_r=1.0,
        tp1_ratio=0.35,
        tp2_r=3.0,
        resume_ma_period=8,
        resume_confirm_bars=2,
    ),
    ProfitExitVariant(
        variant_id="slow_resume_21ema_3bar",
        description="更慢退出：更少部分止盈，恢复改看 21EMA 且 3 根确认。",
        min_hold_hours=18.0,
        max_hold_hours=96.0,
        tp1_r=1.25,
        tp1_ratio=0.20,
        tp2_r=4.0,
        resume_ma_period=21,
        resume_confirm_bars=3,
    ),
    ProfitExitVariant(
        variant_id="ultra_tail_21ema_4bar",
        description="更贪心：24h 最低持有，21EMA 4 根确认后才离场。",
        min_hold_hours=24.0,
        max_hold_hours=120.0,
        tp1_r=1.5,
        tp1_ratio=0.15,
        tp2_r=5.0,
        resume_ma_period=21,
        resume_confirm_bars=4,
    ),
    ProfitExitVariant(
        variant_id="profit_mode_4pct_lock15",
        description="一旦浮盈达到 4%，切到更慢恢复判定，并锁定 1.5% 利润。",
        min_hold_hours=16.0,
        max_hold_hours=96.0,
        tp1_r=1.0,
        tp1_ratio=0.20,
        tp2_r=4.5,
        resume_ma_period=8,
        resume_confirm_bars=2,
        profit_mode_trigger_pct=4.0,
        profit_mode_resume_ma_period=21,
        profit_mode_resume_confirm_bars=3,
        profit_mode_lock_pct=1.5,
    ),
    ProfitExitVariant(
        variant_id="profit_mode_6pct_lock30",
        description="一旦浮盈达到 6%，切到更慢恢复判定，并锁定 3% 利润。",
        min_hold_hours=18.0,
        max_hold_hours=120.0,
        tp1_r=1.25,
        tp1_ratio=0.15,
        tp2_r=5.0,
        resume_ma_period=8,
        resume_confirm_bars=2,
        profit_mode_trigger_pct=6.0,
        profit_mode_resume_ma_period=21,
        profit_mode_resume_confirm_bars=4,
        profit_mode_lock_pct=3.0,
    ),
    ProfitExitVariant(
        variant_id="profit_mode_4pct_lock20_55ema",
        description="达到 4% 浮盈后切到更趋势化的 55EMA 恢复，并锁定 2% 利润。",
        min_hold_hours=18.0,
        max_hold_hours=120.0,
        tp1_r=1.0,
        tp1_ratio=0.15,
        tp2_r=5.5,
        resume_ma_period=8,
        resume_confirm_bars=2,
        profit_mode_trigger_pct=4.0,
        profit_mode_resume_ma_period=55,
        profit_mode_resume_confirm_bars=2,
        profit_mode_lock_pct=2.0,
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


def ema_value(state, period, idx):
    if period == 8:
        return state["ema8_1h"][idx]
    if period == 21:
        return state["ema21_1h"][idx]
    if period == 55:
        return state["ema55_1h"][idx]
    raise ValueError(f"unsupported ema period: {period}")


def resolve_position_notional(equity_usd, stop_pct):
    if stop_pct in (None, 0):
        return None
    risk_usd = equity_usd * (RISK_PCT / 100.0)
    gross_cap_usd = equity_usd * (MAX_GROSS_PCT / 100.0)
    return min(risk_usd / (stop_pct / 100.0), gross_cap_usd)


def strength_resume_signal(state, idx, ma_period, confirm_fast_ema=True):
    selected_ema = ema_value(state, ma_period, idx)
    selected_ema_prev = ema_value(state, ma_period, idx - 1)
    candle = state["1h"][idx]
    prev = state["1h"][idx - 1]
    base_cond = (
        candle.close_price > selected_ema
        and selected_ema >= selected_ema_prev
        and candle.close_price > prev.close_price
    )
    if not confirm_fast_ema:
        return base_cond
    return base_cond and state["ema8_1h"][idx] >= state["ema8_1h"][idx - 1]


def simulate_trade(state, entry_idx, signal, equity_usd, variant: ProfitExitVariant):
    candles = state["1h"]
    entry_price = signal["entry_price"]
    stop_price = signal["stop_price"]
    stop_pct = signal["stop_pct"]
    entry_dt = signal["entry_dt"]
    notional_usd = resolve_position_notional(equity_usd, stop_pct)
    if notional_usd in (None, 0):
        return None

    qty = notional_usd / entry_price if entry_price else None
    risk_abs = stop_price - entry_price
    tp1_price = entry_price - risk_abs * variant.tp1_r
    tp2_price = entry_price - risk_abs * variant.tp2_r
    min_hold_dt = entry_dt + timedelta(hours=variant.min_hold_hours)
    end_dt = entry_dt + timedelta(hours=variant.max_hold_hours)

    remaining_weight = 1.0
    realized_return_pct = 0.0
    best_path_return_pct = None
    worst_path_return_pct = None
    exit_code = "timeout"
    exit_dt = None
    exit_price = None
    tp1_taken = False
    tp2_taken = False
    stop_price_live = stop_price
    resume_hits = 0
    profit_mode_active = False
    profit_mode_activated_at = None

    for j in range(entry_idx + 1, len(candles)):
        bar = candles[j]
        if bar.close_dt > end_dt:
            break

        best_bar_return = base.short_return_pct(entry_price, bar.low_price)
        close_return = base.short_return_pct(entry_price, bar.close_price)
        worst_bar_return = base.short_return_pct(entry_price, bar.high_price)
        if best_bar_return is not None:
            best_path_return_pct = best_bar_return if best_path_return_pct is None else max(best_path_return_pct, best_bar_return)
        if worst_bar_return is not None:
            worst_path_return_pct = worst_bar_return if worst_path_return_pct is None else min(worst_path_return_pct, worst_bar_return)

        if (
            variant.profit_mode_trigger_pct is not None
            and not profit_mode_active
            and best_path_return_pct is not None
            and best_path_return_pct >= variant.profit_mode_trigger_pct
        ):
            profit_mode_active = True
            profit_mode_activated_at = bar.close_dt.isoformat()
            if variant.profit_mode_lock_pct is not None:
                lock_price = entry_price * (1.0 - variant.profit_mode_lock_pct / 100.0)
                stop_price_live = min(stop_price_live, lock_price)

        if bar.high_price >= stop_price_live:
            stop_return = base.short_return_pct(entry_price, stop_price_live)
            realized_return_pct += remaining_weight * (stop_return or 0.0)
            remaining_weight = 0.0
            exit_code = "stop_after_tp1" if tp1_taken else "stop_loss"
            if profit_mode_active and (stop_return or 0.0) > 0:
                exit_code = "profit_lock_after_tp1" if tp1_taken else "profit_lock"
            exit_dt = bar.close_dt
            exit_price = stop_price_live
            break

        if not tp1_taken and bar.low_price <= tp1_price and remaining_weight > 0:
            ratio = min(variant.tp1_ratio, remaining_weight)
            realized_return_pct += ratio * (stop_pct * variant.tp1_r)
            remaining_weight -= ratio
            tp1_taken = True
            stop_price_live = min(stop_price_live, entry_price)

        if tp1_taken and not tp2_taken and bar.low_price <= tp2_price and remaining_weight > 0:
            realized_return_pct += remaining_weight * (stop_pct * variant.tp2_r)
            remaining_weight = 0.0
            tp2_taken = True
            exit_code = "take_profit_tail"
            exit_dt = bar.close_dt
            exit_price = tp2_price
            break

        if bar.close_dt >= min_hold_dt:
            if profit_mode_active:
                ma_period = variant.profit_mode_resume_ma_period or variant.resume_ma_period
                confirm_bars = variant.profit_mode_resume_confirm_bars or variant.resume_confirm_bars
            else:
                ma_period = variant.resume_ma_period
                confirm_bars = variant.resume_confirm_bars
            resumed_now = strength_resume_signal(state, j, ma_period)
            resume_hits = resume_hits + 1 if resumed_now else 0
            if resume_hits >= confirm_bars:
                realized_return_pct += remaining_weight * (close_return or 0.0)
                remaining_weight = 0.0
                if profit_mode_active:
                    exit_code = "profit_mode_resume_after_tp1" if tp1_taken else "profit_mode_resume"
                else:
                    exit_code = "strength_resume_after_tp1" if tp1_taken else "strength_resume"
                exit_dt = bar.close_dt
                exit_price = bar.close_price
                break

    if remaining_weight > 0:
        timeout_bar = None
        for j in range(entry_idx + 1, len(candles)):
            bar = candles[j]
            if bar.close_dt > end_dt:
                break
            timeout_bar = bar
        if timeout_bar is None:
            return None
        timeout_return = base.short_return_pct(entry_price, timeout_bar.close_price)
        realized_return_pct += remaining_weight * (timeout_return or 0.0)
        exit_code = "timeout_after_tp1" if tp1_taken else "timeout"
        exit_dt = timeout_bar.close_dt
        exit_price = timeout_bar.close_price

    pnl_usd = notional_usd * (realized_return_pct / 100.0)
    realized_r = realized_return_pct / stop_pct if stop_pct else None
    hold_hours = (exit_dt - entry_dt).total_seconds() / 3600.0 if exit_dt else None
    profit_capture_ratio = None
    if best_path_return_pct not in (None, 0):
        profit_capture_ratio = realized_return_pct / best_path_return_pct
    return {
        "variant_id": variant.variant_id,
        "symbol": state["symbol"],
        "entry_dt": entry_dt.isoformat(),
        "exit_dt": exit_dt.isoformat() if exit_dt else None,
        "entry_price": entry_price,
        "exit_price": exit_price,
        "stop_pct": stop_pct,
        "tp1_price": tp1_price,
        "tp2_price": tp2_price,
        "position_notional_usd": notional_usd,
        "qty": qty,
        "realized_return_pct": realized_return_pct,
        "realized_r": realized_r,
        "realized_pnl_usd": pnl_usd,
        "best_path_return_pct": best_path_return_pct,
        "worst_path_return_pct": worst_path_return_pct,
        "profit_capture_ratio": profit_capture_ratio,
        "hold_hours": hold_hours,
        "exit_code": exit_code,
        "tp1_taken": tp1_taken,
        "tp2_taken": tp2_taken,
        "profit_mode_active": profit_mode_active,
        "profit_mode_activated_at": profit_mode_activated_at,
        "signal": {
            "runup_24h_pct": signal["runup_24h_pct"],
            "trend_7d_pct": signal["trend_7d_pct"],
            "retrace_from_peak_pct": signal["retrace_from_peak_pct"],
            "peak_age_hours": signal["peak_age_hours"],
            "breakout_margin_pct": signal["breakout_margin_pct"],
            "lower_high_gap_pct": signal["lower_high_gap_pct"],
            "weakness_score": signal["weakness_score"],
            "oi_1h_pct": signal["oi_1h_pct"],
            "oi_4h_pct": signal["oi_4h_pct"],
            "oi_12h_pct": signal["oi_12h_pct"],
            "oi_24h_pct": signal["oi_24h_pct"],
            "oi_to_vol_ratio": signal["oi_to_vol_ratio"],
        },
    }


def run_variant(states, selected_signals, variant: ProfitExitVariant):
    equity_usd = STARTING_EQUITY_USD
    peak = equity_usd
    max_dd = 0.0
    open_until = None
    trades = []
    exit_code_counts = {}
    equity_curve = []

    for item in selected_signals:
        sig_dt = item["signal"]["entry_dt"]
        if open_until and sig_dt < open_until:
            continue
        trade = simulate_trade(item["state"], item["index"], item["signal"], equity_usd, variant)
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
    profit_capture_values = [t["profit_capture_ratio"] for t in trades]
    large_winner_count = sum(1 for t in trades if (safe_float(t["realized_return_pct"]) or -999.0) >= 6.0)
    research_score = (
        ((equity_usd - STARTING_EQUITY_USD) / STARTING_EQUITY_USD * 100.0)
        - max_dd * 0.75
        + (mean(realized_r_values) or 0.0) * 4.0
        + (mean(profit_capture_values) or 0.0) * 4.0
        + large_winner_count * 0.9
    )
    robust_research_score = research_score - robustness_penalty(len(trades))
    return {
        "variant_id": variant.variant_id,
        "description": variant.description,
        "config": asdict(variant),
        "summary": {
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
            "avg_profit_capture_ratio": mean(profit_capture_values),
            "median_profit_capture_ratio": median(profit_capture_values),
            "max_drawdown_pct": max_dd,
            "tp1_hit_ratio": ratio_true(t["tp1_taken"] for t in trades),
            "tp2_hit_ratio": ratio_true(t["tp2_taken"] for t in trades),
            "profit_mode_triggered_count": sum(1 for t in trades if t["profit_mode_active"]),
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
        "# A-Layer Profit Expansion Matrix",
        "",
        "## Goal",
        "",
        "- 固定当前最优 A 层信号集合，不改入场，只改持仓与退出。",
        "- 目标是让同样的票，更多把 `盘中已出现的利润` 变成 `已实现利润`。",
        "",
        f"- Signals fixed from variant: `{payload['signal_source']['variant_id']}`",
        f"- Selected signals: {payload['signal_source']['selected_signal_count']}",
        "",
        "## Exit Variant Summary",
        "",
        "| variant | return | max DD | trades | avg realized | avg best path | capture | win rate | score |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for item in ranked:
        s = item["summary"]
        lines.append(
            "| {variant} | {ret:.2f}% | {dd:.2f}% | {trades} | {real:.2f}% | {best:.2f}% | {cap:.2f} | {win:.1f}% | {score:.2f} |".format(
                variant=item["variant_id"],
                ret=s["return_pct"],
                dd=s["max_drawdown_pct"] or 0.0,
                trades=s["executed_trade_count"],
                real=s["avg_realized_return_pct"] or 0.0,
                best=s["avg_best_path_return_pct"] or 0.0,
                cap=s["avg_profit_capture_ratio"] or 0.0,
                win=(s["win_rate"] or 0.0) * 100.0,
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
                f"- Avg realized / best path: {best['summary']['avg_realized_return_pct']:.2f}% / {best['summary']['avg_best_path_return_pct']:.2f}%",
                f"- Avg capture ratio: {best['summary']['avg_profit_capture_ratio']:.2f}",
                "",
                "### Biggest Profit Gaps",
                "",
            ]
        )
        top_gap_trades = sorted(
            best["trades"],
            key=lambda t: (safe_float(t["best_path_return_pct"]) or -999.0) - (safe_float(t["realized_return_pct"]) or -999.0),
            reverse=True,
        )
        for trade in top_gap_trades[:10]:
            best_path = trade["best_path_return_pct"] or 0.0
            realized = trade["realized_return_pct"] or 0.0
            lines.append(
                "- `{symbol}` {entry} -> {exit} | realized={real:.2f}% | best={bestp:.2f}% | gap={gap:.2f}% | `{code}`".format(
                    symbol=trade["symbol"],
                    entry=trade["entry_dt"],
                    exit=trade["exit_dt"],
                    real=realized,
                    bestp=best_path,
                    gap=best_path - realized,
                    code=trade["exit_code"],
                )
            )
    return "\n".join(lines)


def main():
    states = ctx.load_perp_context_states()
    for state in states:
        state["snapshots"] = matrix.compute_state_snapshots(state)

    entry_profile = next(x for x in matrix.ENTRY_PROFILES if x.profile_id == BASE_SIGNAL_VARIANT.entry_profile_id)
    stop_profile = next(x for x in matrix.STOP_PROFILES if x.profile_id == BASE_SIGNAL_VARIANT.stop_profile_id)
    raw_signals, clusters, selected_signals = soft.build_candidate_list(states, entry_profile, stop_profile, BASE_SIGNAL_VARIANT)

    variants = [run_variant(states, selected_signals, variant) for variant in EXIT_VARIANTS]
    ranked = sorted(variants, key=lambda item: item["summary"]["robust_research_score"], reverse=True)

    payload = {
        "ok": True,
        "study_id": "wave_short_1h_A_profit_expansion_matrix_v1",
        "generated_at_utc": datetime.utcnow().isoformat() + "Z",
        "dataset": ctx.dataset_summary(states),
        "signal_source": {
            "variant_id": BASE_SIGNAL_VARIANT.variant_id,
            "raw_signal_count": len(raw_signals),
            "cluster_count": len(clusters),
            "selected_signal_count": len(selected_signals),
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
