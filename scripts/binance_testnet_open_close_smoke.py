#!/usr/bin/env python3
import argparse
import contextlib
import json
import os
import sys
import time
import uuid
from decimal import Decimal, ROUND_DOWN, ROUND_UP

try:
    from binance_common.configuration import ConfigurationRestAPI
    from binance_sdk_derivatives_trading_usds_futures import (
        DERIVATIVES_TRADING_USDS_FUTURES_REST_API_TESTNET_URL,
        DerivativesTradingUsdsFutures,
    )
except Exception as exc:  # pragma: no cover
    print(
        json.dumps(
            {
                "ok": False,
                "error": "binance_sdk_import_failed",
                "detail": repr(exc),
            },
            ensure_ascii=False,
        ),
        file=sys.stderr,
    )
    raise


def safe_float(value):
    try:
        num = float(value)
    except (TypeError, ValueError):
        return None
    return num if num == num else None


def model_to_plain(value):
    if isinstance(value, list):
        return [model_to_plain(item) for item in value]
    if isinstance(value, dict):
        return {key: model_to_plain(item) for key, item in value.items()}
    if hasattr(value, "to_dict"):
        return model_to_plain(value.to_dict())
    return value


def build_filter_map(symbol_info):
    filters = {}
    for item in symbol_info.get("filters") or []:
        if isinstance(item, dict) and item.get("filterType"):
            filters[item["filterType"]] = item
    return filters


def decimal_floor(value, step):
    if step in (None, 0, "0", ""):
        return Decimal(str(value))
    step_dec = Decimal(str(step))
    value_dec = Decimal(str(value))
    units = (value_dec / step_dec).to_integral_value(rounding=ROUND_DOWN)
    return units * step_dec


def round_qty_down(quantity, step):
    qty = decimal_floor(quantity, step)
    return float(qty) if qty > 0 else 0.0


def decimal_ceil(value, step):
    if step in (None, 0, "0", ""):
        return Decimal(str(value))
    step_dec = Decimal(str(step))
    value_dec = Decimal(str(value))
    units = (value_dec / step_dec).to_integral_value(rounding=ROUND_UP)
    return units * step_dec


def round_price_up(price, tick):
    return float(decimal_ceil(price, tick))


def round_price_down(price, tick):
    return float(decimal_floor(price, tick))


def short_client_id(prefix, symbol):
    return f"{prefix}-{symbol}-{uuid.uuid4().hex[:12]}"


def main():
    parser = argparse.ArgumentParser(description="Binance Futures testnet smoke test: market short then market close.")
    parser.add_argument("--symbol", default="BTCUSDT", help="USDS-M perpetual symbol.")
    parser.add_argument("--notional-usd", type=float, default=25.0, help="Approximate entry notional in USD.")
    parser.add_argument("--hold-seconds", type=float, default=2.0, help="Seconds to wait before market close.")
    parser.add_argument("--leverage", type=int, default=1, help="Initial leverage to set before entry.")
    parser.add_argument("--with-protection", action="store_true", help="Attach STOP_MARKET and TAKE_PROFIT_MARKET then verify.")
    parser.add_argument("--stop-pct", type=float, default=1.0, help="Stop trigger percent above short entry when --with-protection.")
    parser.add_argument("--tp-pct", type=float, default=1.0, help="Take-profit trigger percent below short entry when --with-protection.")
    parser.add_argument("--working-type", default="MARK_PRICE", help="Working type for algo protection orders.")
    parser.add_argument("--api-key-env", default="BINANCE_C_TESTNET_API_KEY", help="Env var for API key.")
    parser.add_argument("--api-secret-env", default="BINANCE_C_TESTNET_API_SECRET", help="Env var for API secret.")
    args = parser.parse_args()

    api_key = os.environ.get(args.api_key_env, "")
    api_secret = os.environ.get(args.api_secret_env, "")
    if not api_key or not api_secret:
        raise RuntimeError(f"missing env vars: {args.api_key_env} / {args.api_secret_env}")

    cfg = ConfigurationRestAPI(
        api_key=api_key,
        api_secret=api_secret,
        base_path=DERIVATIVES_TRADING_USDS_FUTURES_REST_API_TESTNET_URL,
        timeout=10000,
        retries=3,
        backoff=1000,
    )
    client = DerivativesTradingUsdsFutures(config_rest_api=cfg).rest_api

    exchange_info = model_to_plain(client.exchange_information().data())
    symbols = {}
    for item in exchange_info.get("symbols") or []:
        if hasattr(item, "to_dict"):
            item = item.to_dict()
        if isinstance(item, dict) and item.get("symbol"):
            symbols[item["symbol"]] = item

    symbol = args.symbol.upper()
    symbol_info = symbols.get(symbol)
    if not symbol_info:
        raise RuntimeError(f"symbol_not_found: {symbol}")
    if symbol_info.get("status") != "TRADING":
        raise RuntimeError(f"symbol_not_trading: {symbol} status={symbol_info.get('status')}")

    filters = build_filter_map(symbol_info)
    market_lot = filters.get("MARKET_LOT_SIZE") or {}
    lot = filters.get("LOT_SIZE") or {}
    step_size = market_lot.get("stepSize") or lot.get("stepSize") or "0"
    min_qty = safe_float(market_lot.get("minQty")) or safe_float(lot.get("minQty")) or 0.0
    price_filter = filters.get("PRICE_FILTER") or {}
    tick_size = price_filter.get("tickSize") or "0"
    notional_filter = filters.get("MIN_NOTIONAL") or filters.get("NOTIONAL") or {}
    min_notional = safe_float(notional_filter.get("notional")) or 0.0

    mark_price_resp = model_to_plain(client.mark_price(symbol=symbol).data())
    mark_price = safe_float(mark_price_resp.get("markPrice")) or safe_float(mark_price_resp.get("indexPrice"))
    if mark_price in (None, 0):
        raise RuntimeError(f"invalid_mark_price: {mark_price_resp}")

    client.change_initial_leverage(symbol, args.leverage, recv_window=5000)
    raw_qty = args.notional_usd / mark_price
    qty = round_qty_down(raw_qty, step_size)
    entry_notional = qty * mark_price
    if qty < min_qty:
        raise RuntimeError(f"quantity_below_min_qty: qty={qty} min_qty={min_qty}")
    if entry_notional < min_notional:
        raise RuntimeError(
            f"quantity_below_min_notional: notional={entry_notional} min_notional={min_notional}"
        )

    client.test_order(
        symbol=symbol,
        side="SELL",
        type="MARKET",
        quantity=qty,
        recv_window=5000,
    )

    entry_resp = model_to_plain(
        client.new_order(
            symbol=symbol,
            side="SELL",
            type="MARKET",
            quantity=qty,
            new_client_order_id=short_client_id("sme", symbol),
            new_order_resp_type="RESULT",
            recv_window=5000,
        ).data()
    )

    protection = {"enabled": bool(args.with_protection)}
    if args.with_protection:
        entry_price = safe_float(entry_resp.get("avgPrice")) or mark_price
        stop_price = round_price_up(entry_price * (1 + args.stop_pct / 100.0), tick_size)
        tp_price = round_price_down(entry_price * (1 - args.tp_pct / 100.0), tick_size)
        if tp_price <= 0 or stop_price <= entry_price:
            raise RuntimeError(
                f"invalid_protection_prices: entry={entry_price} stop={stop_price} tp={tp_price}"
            )
        stop_client_id = short_client_id("sms", symbol)
        tp_client_id = short_client_id("smt", symbol)
        stop_resp = model_to_plain(
            client.new_algo_order(
                algo_type="CONDITIONAL",
                symbol=symbol,
                side="BUY",
                type="STOP_MARKET",
                trigger_price=stop_price,
                working_type=args.working_type,
                close_position="true",
                price_protect="FALSE",
                client_algo_id=stop_client_id,
                recv_window=5000,
            ).data()
        )
        tp_resp = model_to_plain(
            client.new_algo_order(
                algo_type="CONDITIONAL",
                symbol=symbol,
                side="BUY",
                type="TAKE_PROFIT_MARKET",
                trigger_price=tp_price,
                working_type=args.working_type,
                close_position="true",
                price_protect="FALSE",
                client_algo_id=tp_client_id,
                recv_window=5000,
            ).data()
        )
        time.sleep(1.0)
        algo_orders = model_to_plain(
            client.current_all_algo_open_orders(
                algo_type="CONDITIONAL",
                symbol=symbol,
                recv_window=5000,
            ).data()
        )
        if not isinstance(algo_orders, list):
            algo_orders = [algo_orders] if algo_orders else []
        open_client_ids = {item.get("clientAlgoId") for item in algo_orders if isinstance(item, dict)}
        protection = {
            "enabled": True,
            "working_type": args.working_type,
            "stop_pct": args.stop_pct,
            "tp_pct": args.tp_pct,
            "stop_trigger_price": stop_price,
            "tp_trigger_price": tp_price,
            "stop_response": stop_resp,
            "tp_response": tp_resp,
            "verification": {
                "open_algo_order_count": len(algo_orders),
                "open_client_ids": sorted(item for item in open_client_ids if item),
                "stop_found": stop_client_id in open_client_ids,
                "tp_found": tp_client_id in open_client_ids,
            },
        }
        if not protection["verification"]["stop_found"] or not protection["verification"]["tp_found"]:
            raise RuntimeError(f"protection_not_visible_in_open_algo_orders: {protection['verification']}")

    time.sleep(max(0.0, args.hold_seconds))

    cancel_resp = None
    if args.with_protection:
        cancel_resp = model_to_plain(
            client.cancel_all_algo_open_orders(
                symbol=symbol,
                recv_window=5000,
            ).data()
        )

    close_resp = None
    try:
        close_resp = model_to_plain(
            client.new_order(
                symbol=symbol,
                side="BUY",
                type="MARKET",
                quantity=qty,
                reduce_only="true",
                new_client_order_id=short_client_id("smc", symbol),
                new_order_resp_type="RESULT",
                recv_window=5000,
            ).data()
        )
    except Exception:
        pos_qty = 0.0
        with contextlib.suppress(Exception):
            pos = model_to_plain(client.position_information_v3(symbol=symbol, recv_window=5000).data())
            if isinstance(pos, list):
                pos = pos[0] if pos else {}
            if isinstance(pos, dict):
                pos_qty = abs(safe_float(pos.get("positionAmt")) or 0.0)
        if pos_qty > 0:
            with contextlib.suppress(Exception):
                close_resp = model_to_plain(
                    client.new_order(
                        symbol=symbol,
                        side="BUY",
                        type="MARKET",
                        quantity=pos_qty,
                        reduce_only="true",
                        new_client_order_id=short_client_id("smc", symbol),
                        new_order_resp_type="RESULT",
                        recv_window=5000,
                    ).data()
                )
        raise

    print(
        json.dumps(
            {
                "ok": True,
                "symbol": symbol,
                "requested_notional_usd": args.notional_usd,
                "mark_price": mark_price,
                "quantity": qty,
                "entry_response": entry_resp,
                "protection": protection,
                "cancel_algo_response": cancel_resp,
                "close_response": close_resp,
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(json.dumps({"ok": False, "error": repr(exc)}, ensure_ascii=False), file=sys.stderr)
        raise
