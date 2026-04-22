#!/usr/bin/env python3
import argparse
import json
import subprocess
import sys
import urllib.request
import urllib.error
from datetime import datetime, timezone, timedelta
from pathlib import Path

WORKDIR = Path(__file__).resolve().parents[1]
DATA_DIR = WORKDIR / "data" / "top15_tracker"
LATEST_JSON = DATA_DIR / "latest" / "latest.json"
STATE_PATH = DATA_DIR / "meta" / "overlap_report_state.json"
LOGIC_VERSION = 1
DEFAULT_CHANNEL = "feishu"
DEFAULT_TARGET = "oc_5393fbde5ac800d4a72fc39d2924653e"
DEFAULT_WEBHOOK_KEYWORD = "通知"
THRESHOLD_HOURS = [1, 2, 4, 6]
MAX_ITEMS = 10


def now_utc():
    return datetime.now(timezone.utc)


def read_json(path: Path, default):
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


def write_json(path: Path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def safe_float(v, default=None):
    try:
        if v in (None, ""):
            return default
        return float(v)
    except Exception:
        return default


def safe_bool(v):
    if isinstance(v, bool):
        return v
    if isinstance(v, str):
        return v.strip().lower() in {"true", "1", "yes"}
    return bool(v)


def load_rows():
    rows = read_json(LATEST_JSON, [])
    if not isinstance(rows, list):
        return []
    return rows


def sort_candidates(rows):
    return sorted(
        rows,
        key=lambda r: (
            safe_float(r.get("top15_persistence_hours"), 0.0),
            safe_float(r.get("overlap_score"), -999.0),
        ),
        reverse=True,
    )


def sort_darkhorse_rows(rows):
    return sorted(
        rows,
        key=lambda r: (
            safe_float(r.get("darkhorse_score"), -999.0),
            safe_float(r.get("persistence_score"), -999.0),
            safe_float(r.get("change_24h_pct"), -999.0),
        ),
        reverse=True,
    )


def sort_persistence_rows(rows):
    return sorted(
        rows,
        key=lambda r: (
            safe_float(r.get("persistence_score"), -999.0),
            safe_float(r.get("darkhorse_score"), -999.0),
            safe_float(r.get("structure_score"), -999.0),
        ),
        reverse=True,
    )


def sort_overlap_watch_rows(rows):
    watch_rows = [r for r in rows if not safe_bool(r.get("overlap_candidate"))]
    return sorted(
        watch_rows,
        key=lambda r: (
            safe_float(r.get("overlap_score"), -999.0),
            safe_float(r.get("top15_persistence_hours"), -999.0),
        ),
        reverse=True,
    )


def top_darkhorse_candidates(rows, limit=5):
    out = []
    for idx, r in enumerate(sort_darkhorse_rows(rows)[:limit], start=1):
        out.append({
            "rank": idx,
            "symbol": r.get("symbol"),
            "darkhorse_score": safe_float(r.get("darkhorse_score"), 0.0),
            "top5_potential": r.get("top5_potential") or "--",
            "darkhorse_tag": r.get("darkhorse_tag") or "--",
            "price_usd": safe_float(r.get("price_usd"), 0.0),
        })
    return out


def top_persistence_candidates(rows, limit=5):
    out = []
    for idx, r in enumerate(sort_persistence_rows(rows)[:limit], start=1):
        out.append({
            "rank": idx,
            "symbol": r.get("symbol"),
            "persistence_score": safe_float(r.get("persistence_score"), 0.0),
            "persistence_label": r.get("persistence_label") or "--",
            "continuation_risk": r.get("continuation_risk") or "--",
            "top15_persistence_hours": safe_float(r.get("top15_persistence_hours"), 0.0),
        })
    return out


def top_overlap_watch_candidates(rows, limit=5):
    out = []
    for idx, r in enumerate(sort_overlap_watch_rows(rows)[:limit], start=1):
        out.append({
            "rank": idx,
            "symbol": r.get("symbol"),
            "overlap_score": safe_float(r.get("overlap_score"), 0.0),
            "overlap_label": r.get("overlap_label") or "--",
            "top15_persistence_hours": safe_float(r.get("top15_persistence_hours"), 0.0),
            "overlap_evidence": r.get("overlap_evidence") or "--",
        })
    return out


def normalize_candidates(rows):
    confirmed = [r for r in rows if safe_bool(r.get("overlap_candidate"))]
    confirmed = sort_candidates(confirmed)
    out = []
    for idx, r in enumerate(confirmed, start=1):
        out.append({
            "rank": idx,
            "symbol": r.get("symbol"),
            "name": r.get("name"),
            "overlap_score": safe_float(r.get("overlap_score"), 0.0),
            "overlap_label": r.get("overlap_label") or "--",
            "overlap_rank_signal": r.get("overlap_rank_signal") or "--",
            "top15_persistence_hours": safe_float(r.get("top15_persistence_hours"), 0.0),
            "top15_presence_ratio_24h": safe_float(r.get("top15_presence_ratio_24h"), 0.0),
            "overlap_evidence": r.get("overlap_evidence") or "--",
        })
    return out


def candidate_map(candidates):
    return {c["symbol"]: c for c in candidates if c.get("symbol")}


def crossed_thresholds(prev_hours, curr_hours):
    hit = []
    prev_hours = safe_float(prev_hours, 0.0) or 0.0
    curr_hours = safe_float(curr_hours, 0.0) or 0.0
    for t in THRESHOLD_HOURS:
        if prev_hours < t <= curr_hours:
            hit.append(t)
    return hit


def detect_events(prev_state, candidates, snapshot_id, captured_at_utc):
    prev_candidates = prev_state.get("confirmed_candidates") or []
    prev_map = candidate_map(prev_candidates)
    curr_map = candidate_map(candidates)
    prev_symbols = set(prev_map.keys())
    curr_symbols = set(curr_map.keys())

    reasons = []
    details = {
        "new_candidates": [],
        "rank_changes": [],
        "threshold_breaks": [],
        "cleared": False,
    }

    new_symbols = sorted(curr_symbols - prev_symbols)
    if new_symbols:
        reasons.append("出现新的正式交叉候选")
        details["new_candidates"] = new_symbols

    prev_rank = {c["symbol"]: c["rank"] for c in prev_candidates}
    curr_rank = {c["symbol"]: c["rank"] for c in candidates}

    top_prev = prev_candidates[0]["symbol"] if prev_candidates else None
    top_curr = candidates[0]["symbol"] if candidates else None
    if top_prev and top_curr and top_prev != top_curr:
        reasons.append("排名有明显变化")
        details["rank_changes"].append({"symbol": top_curr, "type": "top_changed", "from": top_prev, "to": top_curr})
    else:
        for symbol in sorted(curr_symbols & prev_symbols):
            delta = abs(curr_rank[symbol] - prev_rank[symbol])
            if delta >= 2:
                reasons.append("排名有明显变化")
                details["rank_changes"].append({"symbol": symbol, "from": prev_rank[symbol], "to": curr_rank[symbol]})
                break
        else:
            prev_top3 = {c["symbol"] for c in prev_candidates[:3]}
            curr_top3 = {c["symbol"] for c in candidates[:3]}
            if prev_top3 != curr_top3 and (prev_top3 or curr_top3):
                reasons.append("排名有明显变化")
                details["rank_changes"].append({"type": "top3_changed"})

    for symbol in sorted(curr_symbols & prev_symbols):
        hits = crossed_thresholds(
            prev_map[symbol].get("top15_persistence_hours"),
            curr_map[symbol].get("top15_persistence_hours"),
        )
        if hits:
            reasons.append("在榜时长突破关键阈值")
            details["threshold_breaks"].append({"symbol": symbol, "thresholds": hits})

    if prev_candidates and not candidates:
        reasons.append("正式候选清空")
        details["cleared"] = True

    reasons = list(dict.fromkeys(reasons))
    should_send = bool(reasons)
    return {
        "should_send": should_send,
        "reasons": reasons,
        "details": details,
        "snapshot_id": snapshot_id,
        "captured_at_utc": captured_at_utc,
    }


def format_pct_ratio(v):
    n = safe_float(v, 0.0) or 0.0
    return f"{n * 100:.1f}%"


def format_hours(v):
    n = safe_float(v, 0.0) or 0.0
    return f"{n:.2f}h"


def build_change_summary(events):
    details = events.get("details") or {}
    parts = []

    new_candidates = details.get("new_candidates") or []
    if new_candidates:
        parts.append("新增正式交叉候选：" + "、".join(new_candidates))

    rank_changes = details.get("rank_changes") or []
    if rank_changes:
        top_change = rank_changes[0]
        if top_change.get("type") == "top_changed":
            parts.append(f"榜首变化：{top_change.get('from')} → {top_change.get('to')}")
        elif top_change.get("type") == "top3_changed":
            parts.append("前3名名单发生变化")
        else:
            parts.append(f"排名显著变化：{top_change.get('symbol')} {top_change.get('from')}→{top_change.get('to')}")

    threshold_breaks = details.get("threshold_breaks") or []
    if threshold_breaks:
        previews = []
        for item in threshold_breaks[:3]:
            thresholds = "/".join(f"{t}h" for t in item.get("thresholds") or [])
            previews.append(f"{item.get('symbol')} 突破 {thresholds}")
        parts.append("时长阈值突破：" + "；".join(previews))

    if details.get("cleared"):
        parts.append("正式交叉候选已清空")

    if not parts:
        return "本次为人工/强制播报，暂无新增变化摘要。"
    return " | ".join(parts)


def build_message(events, candidates, darkhorse_top5, persistence_top5, overlap_watch_top5, keyword=DEFAULT_WEBHOOK_KEYWORD):
    lines = []
    lines.append(f"【{keyword}｜TOP15 交叉确认榜单更新】")
    if events["reasons"]:
        lines.append("触发原因：" + "；".join(events["reasons"]))
    else:
        lines.append("触发原因：定时播报（本小时无新增触发事件）")
    lines.append(f"快照：{events['snapshot_id']}")
    lines.append("新增变化摘要：" + build_change_summary(events))
    lines.append("")

    lines.append("一、正式交叉候选（按在榜时长→交叉确认分排序）")
    if candidates:
        for c in candidates[:MAX_ITEMS]:
            lines.append(f"{c['rank']}. {c['symbol']} | {c['overlap_rank_signal']}")
            lines.append(f"- 在榜时长：{format_hours(c['top15_persistence_hours'])}")
            lines.append(f"- 交叉确认分：{c['overlap_score']:.2f} | 等级：{c['overlap_label']}")
            lines.append(f"- 24h在榜占比：{format_pct_ratio(c['top15_presence_ratio_24h'])}")
            lines.append(f"- 证据：{c['overlap_evidence']}")
        if len(candidates) > MAX_ITEMS:
            lines.append(f"- 其余 {len(candidates) - MAX_ITEMS} 个候选已省略")
    else:
        lines.append("当前正式交叉候选已清空。")
        lines.append("说明：当前可能因在榜时长不足 1 小时，或黑马 / 持续走强门槛未同时满足，导致暂无正式候选。")

    lines.append("")
    lines.append("二、黑马候选榜前五")
    for item in darkhorse_top5:
        lines.append(f"{item['rank']}. {item['symbol']} | 黑马分 {item['darkhorse_score']:.2f} | 前五潜力 {item['top5_potential']} | {item['darkhorse_tag']}")

    lines.append("")
    lines.append("三、持续走强候选榜前五")
    for item in persistence_top5:
        lines.append(f"{item['rank']}. {item['symbol']} | 持续走强分 {item['persistence_score']:.2f} | {item['persistence_label']} | 风险 {item['continuation_risk']} | 在榜 {format_hours(item['top15_persistence_hours'])}")

    lines.append("")
    lines.append("四、观察中前五")
    if overlap_watch_top5:
        for item in overlap_watch_top5:
            lines.append(f"{item['rank']}. {item['symbol']} | 交叉分 {item['overlap_score']:.2f} | {item['overlap_label']} | 在榜 {format_hours(item['top15_persistence_hours'])}")
            lines.append(f"- 观察原因：{item['overlap_evidence']}")
    else:
        lines.append("当前暂无观察中样本。")

    return "\n".join(lines).strip()


def make_markdown_block(title, lines, color="default"):
    content = f"**{title}**\n" + "\n".join(lines)
    return {
        "tag": "markdown",
        "content": content,
        "text_align": "left",
        "text_size": "normal",
    }


def build_feishu_card(events, candidates, darkhorse_top5, persistence_top5, overlap_watch_top5, keyword=DEFAULT_WEBHOOK_KEYWORD):
    reasons_text = "；".join(events["reasons"]) if events["reasons"] else "定时播报（本小时无新增触发事件）"
    summary_text = build_change_summary(events)
    confirmed_count = len(candidates)

    elements = []
    elements.append({
        "tag": "markdown",
        "content": (
            f"**触发原因**：{reasons_text}\n"
            f"**快照**：`{events['snapshot_id']}`\n"
            f"**正式交叉候选数**：**{confirmed_count}**\n"
            f"**变化摘要**：{summary_text}"
        )
    })
    elements.append({"tag": "hr"})

    confirmed_lines = []
    if candidates:
        for c in candidates[:MAX_ITEMS]:
            confirmed_lines.append(
                f"**{c['rank']}. {c['symbol']}**｜{c['overlap_rank_signal']}  \n"
                f"在榜：{format_hours(c['top15_persistence_hours'])}｜交叉分：{c['overlap_score']:.2f}｜等级：{c['overlap_label']}｜24h占比：{format_pct_ratio(c['top15_presence_ratio_24h'])}  \n"
                f"证据：{c['overlap_evidence']}"
            )
        if len(candidates) > MAX_ITEMS:
            confirmed_lines.append(f"其余 {len(candidates) - MAX_ITEMS} 个候选已省略")
    else:
        confirmed_lines.append("当前正式交叉候选已清空。")
        confirmed_lines.append("说明：当前可能因在榜时长不足 1 小时，或黑马 / 持续走强门槛未同时满足，导致暂无正式候选。")
    elements.append(make_markdown_block("一、正式交叉候选", confirmed_lines))
    elements.append({"tag": "hr"})

    darkhorse_lines = [
        f"{item['rank']}. **{item['symbol']}**｜黑马分 {item['darkhorse_score']:.2f}｜前五潜力 {item['top5_potential']}｜{item['darkhorse_tag']}"
        for item in darkhorse_top5
    ] or ["暂无数据"]
    elements.append(make_markdown_block("二、黑马候选榜前五", darkhorse_lines))
    elements.append({"tag": "hr"})

    persistence_lines = [
        f"{item['rank']}. **{item['symbol']}**｜持续走强分 {item['persistence_score']:.2f}｜{item['persistence_label']}｜风险 {item['continuation_risk']}｜在榜 {format_hours(item['top15_persistence_hours'])}"
        for item in persistence_top5
    ] or ["暂无数据"]
    elements.append(make_markdown_block("三、持续走强候选榜前五", persistence_lines))
    elements.append({"tag": "hr"})

    watch_lines = []
    if overlap_watch_top5:
        for item in overlap_watch_top5:
            watch_lines.append(
                f"{item['rank']}. **{item['symbol']}**｜交叉分 {item['overlap_score']:.2f}｜{item['overlap_label']}｜在榜 {format_hours(item['top15_persistence_hours'])}  \n"
                f"观察原因：{item['overlap_evidence']}"
            )
    else:
        watch_lines.append("当前暂无观察中样本。")
    elements.append(make_markdown_block("四、观察中前五", watch_lines))

    return {
        "msg_type": "interactive",
        "card": {
            "schema": "2.0",
            "config": {
                "wide_screen_mode": True,
                "enable_forward": True,
            },
            "header": {
                "title": {
                    "tag": "plain_text",
                    "content": f"{keyword}｜TOP15 交叉确认榜单更新",
                },
                "template": "orange",
            },
            "body": {
                "elements": elements,
            },
        },
    }


def send_feishu_message_cli(message_text, target, account=None, dry_run=False):
    cmd = [
        "openclaw", "message", "send",
        "--channel", DEFAULT_CHANNEL,
        "--target", target,
        "--message", message_text,
    ]
    if account:
        cmd.extend(["--account", account])
    if dry_run:
        cmd.append("--dry-run")
    return subprocess.run(cmd, capture_output=True, text=True)


def send_feishu_webhook(payload, webhook_url, timeout=20):
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(
        webhook_url,
        data=data,
        headers={"Content-Type": "application/json; charset=utf-8"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        body = resp.read().decode("utf-8", errors="replace")
        return resp.getcode(), body


def build_state(snapshot_id, captured_at_utc, candidates):
    return {
        "logic_version": LOGIC_VERSION,
        "snapshot_id": snapshot_id,
        "captured_at_utc": captured_at_utc,
        "confirmed_candidates": candidates,
        "confirmed_count": len(candidates),
        "updated_at_utc": now_utc().isoformat(),
    }


def main():
    parser = argparse.ArgumentParser(description="TOP15 overlap reporter for Feishu group")
    parser.add_argument("--target", default=DEFAULT_TARGET, help="Feishu group id, e.g. oc_xxx")
    parser.add_argument("--account", default="", help="Optional OpenClaw channel account id")
    parser.add_argument("--webhook-url", default="", help="Feishu bot webhook url")
    parser.add_argument("--keyword", default=DEFAULT_WEBHOOK_KEYWORD, help="Required keyword prefix for webhook text")
    parser.add_argument("--dry-run", action="store_true", help="Print message / skip external send")
    parser.add_argument("--force-send", action="store_true", help="Send regardless of trigger conditions")
    args = parser.parse_args()

    rows = load_rows()
    if not rows:
        print(json.dumps({"ok": False, "error": "latest rows missing"}, ensure_ascii=False))
        return 1

    snapshot_id = rows[0].get("snapshot_id") or "unknown"
    captured_at_utc = rows[0].get("captured_at_utc") or now_utc().isoformat()
    candidates = normalize_candidates(rows)
    darkhorse_top5 = top_darkhorse_candidates(rows, limit=5)
    persistence_top5 = top_persistence_candidates(rows, limit=5)
    overlap_watch_top5 = top_overlap_watch_candidates(rows, limit=5)
    prev_state = read_json(STATE_PATH, {})
    events = detect_events(prev_state, candidates, snapshot_id, captured_at_utc)

    message_text = build_message(events, candidates, darkhorse_top5, persistence_top5, overlap_watch_top5, keyword=args.keyword)
    webhook_payload = build_feishu_card(events, candidates, darkhorse_top5, persistence_top5, overlap_watch_top5, keyword=args.keyword)

    if args.dry_run:
        print(json.dumps({
            "ok": True,
            "sent": False,
            "dry_run": True,
            "snapshot_id": snapshot_id,
            "confirmed_count": len(candidates),
            "reasons": events["reasons"],
            "message": message_text,
            "webhook_payload": webhook_payload,
        }, ensure_ascii=False, indent=2))
        new_state = build_state(snapshot_id, captured_at_utc, candidates)
        write_json(STATE_PATH, new_state)
        return 0

    if args.webhook_url:
        try:
            status_code, body = send_feishu_webhook(webhook_payload, args.webhook_url)
        except urllib.error.HTTPError as e:
            err_body = e.read().decode("utf-8", errors="replace")
            print(json.dumps({
                "ok": False,
                "sent": False,
                "snapshot_id": snapshot_id,
                "mode": "webhook",
                "status": e.code,
                "error": err_body,
            }, ensure_ascii=False, indent=2))
            return 1
        except Exception as e:
            print(json.dumps({
                "ok": False,
                "sent": False,
                "snapshot_id": snapshot_id,
                "mode": "webhook",
                "error": repr(e),
            }, ensure_ascii=False, indent=2))
            return 1

        new_state = build_state(snapshot_id, captured_at_utc, candidates)
        write_json(STATE_PATH, new_state)
        print(json.dumps({
            "ok": True,
            "sent": True,
            "snapshot_id": snapshot_id,
            "confirmed_count": len(candidates),
            "reasons": events["reasons"],
            "mode": "webhook",
            "status": status_code,
            "response": body,
        }, ensure_ascii=False, indent=2))
        return 0

    result = send_feishu_message_cli(message_text, target=args.target, account=args.account or None, dry_run=False)
    if result.returncode != 0:
        print(json.dumps({
            "ok": False,
            "sent": False,
            "snapshot_id": snapshot_id,
            "stderr": result.stderr,
            "stdout": result.stdout,
            "mode": "openclaw-message",
        }, ensure_ascii=False, indent=2))
        return result.returncode

    new_state = build_state(snapshot_id, captured_at_utc, candidates)
    write_json(STATE_PATH, new_state)
    print(json.dumps({
        "ok": True,
        "sent": True,
        "snapshot_id": snapshot_id,
        "confirmed_count": len(candidates),
        "reasons": events["reasons"],
        "stdout": result.stdout.strip(),
        "mode": "openclaw-message",
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
