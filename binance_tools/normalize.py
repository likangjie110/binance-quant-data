"""事件归一化：三类市场异构字段 → 统一结构（原始字段只在此解析）。"""
from __future__ import annotations

import time

from .common import num


def normalize(market: str, ev: dict) -> dict:
    e = ev.get("e") or "unknown"
    ts = ev.get("E") or ev.get("T") or int(time.time() * 1000)
    out = {
        "market": market, "event_type": e, "symbol": ev.get("s"),
        "ts": ts, "order": None, "fills": [], "balances": [], "positions": [],
        "raw": ev,
    }
    if e == "executionReport":
        out["symbol"] = ev.get("s")
        out["order"] = {
            "order_id": ev.get("i"), "client_order_id": ev.get("c"),
            "side": ev.get("S"), "order_type": ev.get("o"), "status": ev.get("X"),
            "price": ev.get("p"), "orig_qty": ev.get("q"),
            "executed_qty": ev.get("z"), "avg_price": None,
            "cum_quote": ev.get("Z"), "last_qty": ev.get("l"), "last_price": ev.get("L"),
            "is_maker": ev.get("m"), "event_time": ts,
        }
        if ev.get("x") == "TRADE":
            out["fills"].append({
                "order_id": ev.get("i"), "trade_id": ev.get("t"),
                "trade_time": ev.get("T"), "price": ev.get("L"), "qty": ev.get("l"),
                "quote_qty": (num(ev.get("L")) or 0) * (num(ev.get("l")) or 0),
                "commission": ev.get("n"), "commission_asset": ev.get("N"),
                "is_maker": ev.get("m"), "realized_pnl": None,
            })
    elif e == "ORDER_TRADE_UPDATE":
        o = ev.get("o") or {}
        out["symbol"] = o.get("s")
        out["order"] = {
            "order_id": o.get("i"), "client_order_id": o.get("c"),
            "side": o.get("S"), "order_type": o.get("o"), "status": o.get("X"),
            "price": o.get("p"), "orig_qty": o.get("q"),
            "executed_qty": o.get("z"), "avg_price": o.get("ap"),
            "cum_quote": None, "last_qty": o.get("l"), "last_price": o.get("L"),
            "is_maker": o.get("m"), "event_time": ts, "realized_pnl": o.get("rp"),
        }
        if o.get("x") == "TRADE":
            out["fills"].append({
                "order_id": o.get("i"), "trade_id": o.get("t"),
                "trade_time": o.get("T") or ts, "price": o.get("L"), "qty": o.get("l"),
                "quote_qty": (num(o.get("L")) or 0) * (num(o.get("l")) or 0),
                "commission": o.get("n"), "commission_asset": o.get("N"),
                "is_maker": o.get("m"), "realized_pnl": o.get("rp"),
            })
    elif e == "ACCOUNT_UPDATE":
        a = ev.get("a") or {}
        out["reason"] = a.get("m")
        for b in a.get("B") or []:
            out["balances"].append({"asset": b.get("a"), "free": b.get("wb"), "locked": None})
        for p in a.get("P") or []:
            out["positions"].append({
                "symbol": p.get("s"), "position_amt": p.get("pa"),
                "entry_price": p.get("ep"), "unrealized_pnl": p.get("up"),
            })
    elif e == "outboundAccountPosition":
        for b in ev.get("B") or []:
            out["balances"].append({"asset": b.get("a"), "free": b.get("f"), "locked": b.get("l")})
    elif e == "balanceUpdate":
        out["asset"] = ev.get("a")
        out["delta"] = ev.get("d")
    elif e == "listStatus":
        out["symbol"] = ev.get("s")
        out["order_list_id"] = ev.get("g")
        out["list_status_type"] = ev.get("l")
    return out
