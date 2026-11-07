"""策略信号引擎：订单状态机、持仓变化、已实现盈亏。"""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone

from .common import num
from .sinks import BaseSink


class SignalEngine:
    def __init__(self, emit):
        self.emit = emit
        self.positions: dict[tuple[str, str], float] = {}
        self.realized_pnl: dict[tuple[str, str], float] = {}

    def _pos(self, market: str, symbol: str) -> float:
        return self.positions.get((market, symbol), 0.0)

    def on_event(self, n: dict):
        e = n["event_type"]
        m, s = n["market"], n.get("symbol") or ""

        if e == "executionReport":
            o = n["order"]
            x = n["raw"].get("x")
            status = o.get("status")
            if status == "NEW":
                self.emit({"signal": "ORDER_PLACED", "market": m, "symbol": s,
                           "order_id": o.get("order_id"), "side": o.get("side"),
                           "order_type": o.get("order_type"), "price": o.get("price"),
                           "qty": o.get("orig_qty")})
            if x == "TRADE":
                self._apply_fill(m, s, o, n["fills"][0])
            if status == "FILLED":
                self.emit({"signal": "ORDER_FILLED", "market": m, "symbol": s,
                           "order_id": o.get("order_id"), "cum_qty": o.get("executed_qty")})
            elif status == "PARTIALLY_FILLED":
                self.emit({"signal": "PARTIAL_FILL", "market": m, "symbol": s,
                           "order_id": o.get("order_id"), "cum_qty": o.get("executed_qty")})
            elif status in ("CANCELED", "EXPIRED", "REJECTED"):
                self.emit({"signal": "ORDER_" + status, "market": m, "symbol": s,
                           "order_id": o.get("order_id")})

        elif e == "ORDER_TRADE_UPDATE":
            o = n["order"]
            x = n["raw"].get("o", {}).get("x") if isinstance(n["raw"].get("o"), dict) else None
            status = o.get("status")
            if status == "NEW":
                self.emit({"signal": "ORDER_PLACED", "market": m, "symbol": s,
                           "order_id": o.get("order_id"), "side": o.get("side"),
                           "order_type": o.get("order_type"), "price": o.get("price"),
                           "qty": o.get("orig_qty")})
            if x == "TRADE":
                self._apply_fill(m, s, o, n["fills"][0])
            if status == "FILLED":
                self.emit({"signal": "ORDER_FILLED", "market": m, "symbol": s,
                           "order_id": o.get("order_id"), "cum_qty": o.get("executed_qty")})
            elif status == "PARTIALLY_FILLED":
                self.emit({"signal": "PARTIAL_FILL", "market": m, "symbol": s,
                           "order_id": o.get("order_id"), "cum_qty": o.get("executed_qty")})
            elif status in ("CANCELED", "EXPIRED", "REJECTED"):
                self.emit({"signal": "ORDER_" + status, "market": m, "symbol": s,
                           "order_id": o.get("order_id")})

        elif e == "ACCOUNT_UPDATE":
            for p in n["positions"]:
                sym = p.get("symbol") or ""
                self.positions[(m, sym)] = num(p.get("position_amt")) or 0.0

        elif e == "balanceUpdate":
            self.emit({"signal": "BALANCE_CHANGED", "market": m, "asset": n.get("asset"),
                       "delta": n.get("delta")})

    def _apply_fill(self, market: str, symbol: str, order: dict, fill: dict):
        qty = num(fill.get("qty")) or 0.0
        signed = qty if (order.get("side") == "BUY") else -qty
        prev = self._pos(market, symbol)
        new = round(prev + signed, 12)
        self.positions[(market, symbol)] = new
        self.emit({"signal": "FILL", "market": market, "symbol": symbol,
                   "order_id": order.get("order_id"), "side": order.get("side"),
                   "price": fill.get("price"), "qty": fill.get("qty"),
                   "position_before": prev, "position_after": new})
        if prev == 0 and new != 0:
            sig_name = "POSITION_OPENED"
        elif new == 0 and prev != 0:
            sig_name = "POSITION_CLOSED"
        elif prev * new < 0:
            sig_name = "POSITION_FLIPPED"
        elif abs(new) > abs(prev):
            sig_name = "POSITION_INCREASED"
        else:
            sig_name = "POSITION_REDUCED"
        self.emit({"signal": sig_name, "market": market, "symbol": symbol,
                   "position_before": prev, "position_after": new})
        rp = num(fill.get("realized_pnl")) or 0.0
        if rp:
            key = (market, symbol)
            self.realized_pnl[key] = self.realized_pnl.get(key, 0.0) + rp
            self.emit({"signal": "PNL_REALIZED", "market": market, "symbol": symbol,
                       "delta": rp, "cumulative": self.realized_pnl[key]})


class SignalSink(BaseSink):
    name = "signals"

    def __init__(self, path: str, quiet: bool = False):
        self.path = path
        os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
        self.fh = open(path, "a", encoding="utf-8")
        self.quiet = quiet
        self.count = 0

    def _emit(self, s: dict):
        rec = {"ts": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ"), **s}
        self.fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
        self.fh.flush()
        self.count += 1
        if not self.quiet:
            extra = " ".join(f"{k}={v}" for k, v in s.items()
                             if k in ("order_id", "side", "price", "qty", "position_after",
                                      "delta", "cumulative", "asset"))
            print(f"[signal] {s['signal']:20s} {s.get('market','')} {s.get('symbol',''):10s} {extra}")

    def write(self, n: dict):
        self.on_event(n)

    def on_event(self, n: dict):
        if not hasattr(self, "_engine"):
            self._engine = SignalEngine(self._emit)
        self._engine.on_event(n)

    def close(self):
        self.fh.close()
