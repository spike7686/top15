#!/usr/bin/env python3
import argparse
import json
import subprocess
import sys
from pathlib import Path


WORKDIR = Path(__file__).resolve().parents[1]
CONFIG_DIR = WORKDIR / "config" / "live_trader_accounts"
TRADER_SCRIPT = WORKDIR / "scripts" / "top15_c_strategy_live_trader.py"


def read_json(path: Path, default=None):
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


def slugify_account_id(value):
    text = str(value or "").strip().lower()
    chars = []
    for char in text:
        if char.isalnum():
            chars.append(char)
        elif char in {"-", "_", "."}:
            chars.append("-")
    slug = "".join(chars).strip("-")
    while "--" in slug:
        slug = slug.replace("--", "-")
    return slug or "default"


def resolve_account_id(config, config_path: Path):
    explicit = (config or {}).get("account_id") or (config or {}).get("runtime_dirname")
    if explicit:
        return slugify_account_id(explicit)
    return slugify_account_id(config_path.stem)


def iter_config_paths(config_dir: Path):
    if not config_dir.exists():
        return []
    return sorted(
        path for path in config_dir.glob("*.json")
        if ".example." not in path.name
    )


def main():
    parser = argparse.ArgumentParser(description="Run live trader once for every configured mainnet account.")
    parser.add_argument("--config-dir", default=str(CONFIG_DIR), help="Directory containing per-account config JSON files.")
    parser.add_argument("--python-bin", default=sys.executable, help="Python executable used to spawn account workers.")
    parser.add_argument("--account-id", action="append", help="Only run specific account_id(s). Can be passed multiple times.")
    parser.add_argument("--reprocess-snapshot", action="store_true", help="Pass through to account workers.")
    parser.add_argument("--candidate-preview-limit", type=int, default=5, help="Pass through to account workers.")
    args = parser.parse_args()

    config_dir = Path(args.config_dir).expanduser().resolve()
    config_paths = iter_config_paths(config_dir)
    only_accounts = {slugify_account_id(item) for item in (args.account_id or []) if item}

    if not config_paths:
        raise RuntimeError(f"no account configs found under {config_dir}")

    summaries = []
    failed = False
    for config_path in config_paths:
        raw = read_json(config_path, default={}) or {}
        account_id = resolve_account_id(raw, config_path)
        if only_accounts and account_id not in only_accounts:
            continue
        cmd = [
            args.python_bin,
            str(TRADER_SCRIPT),
            "--config",
            str(config_path),
            "--candidate-preview-limit",
            str(args.candidate_preview_limit),
        ]
        if args.reprocess_snapshot:
            cmd.append("--reprocess-snapshot")
        proc = subprocess.run(cmd, capture_output=True, text=True)
        stdout = proc.stdout.strip()
        stderr = proc.stderr.strip()
        payload = None
        if stdout:
            try:
                payload = json.loads(stdout)
            except Exception:
                payload = None
        summaries.append({
            "account_id": account_id,
            "config_path": str(config_path),
            "returncode": proc.returncode,
            "summary": payload,
            "stderr": stderr,
        })
        if proc.returncode != 0:
            failed = True

    print(json.dumps({
        "ok": not failed,
        "account_count": len(summaries),
        "accounts": summaries,
    }, ensure_ascii=False, indent=2))
    if failed:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
