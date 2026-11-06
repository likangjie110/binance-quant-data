#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
event_sink.py —— 币安用户数据流的事件落库 + 策略信号示例

设计目标
  * 把 tools/binance_user_stream.py 收到的私有事件（现货 executionReport / 合约
    ORDER_TRADE_UPDATE、ACCOUNT_UPDATE 等）落到可查询的地方：
        - JSONL（原样，最稳）
        - CSV（按事件类型分文件，方便 Excel/pandas）
        - SQLite（零依赖，本地研究/回放）
        - PostgreSQL（生产，psycopg3；DSN 形如 postgresql://user:pass@host:5432/db）
  * 同时提供最小「下单事件 → 策略信号」引擎：
        ORDER_PLACED / PARTIAL_FILL / ORDER_FILLED / ORDER_CANCELED / ORDER_EXPIRED /
        ORDER_REJECTED / POSITION_OPENED / POSITION_INCREASED / POSITION_REDUCED /
        POSITION_FLIPPED / POSITION_CLOSED / PNL_REALIZED / BALANCE_CHANGED

安全
  * 本模块只读上游事件，不产生任何交易动作。
  * 私有事件包含账户信息；落盘目录请勿提交到公开仓库（仓库 .gitignore 已排除 work/private）。

CLI
  # 用内置样例跑通 CSV/SQLite/PG 三种落库 + 信号
  python3 tools/event_sink.py selftest --out work/signals/selftest
  python3 tools/event_sink.py selftest --out work/signals/selftest \
      --pg-dsn postgresql://postgres:test@127.0.0.1:58349/binance_test

  # 回放一份 listen 输出的 JSONL，产出信号
  python3 tools/event_sink.py replay --file work/private/user_stream_xxx.jsonl --out work/signals
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import sqlite3
import sys
import time
from datetime import datetime, timezone

# 事件 -> 用的 CSV 列（按需增删；未知事件走 other.csv）
CSV_COLUMNS = {
    "executionReport": ["ts", "market", "event_type", "symbol", "order_id", "client_order_id",
                        "side", "order_type", "status", "exec_type", "price", "orig_qty",
                        "executed_qty", "last_qty", "last_price", "commission",
                        "commission_asset", "is_maker", "trade_time"],
    "ORDER_TRADE_UPDATE": ["ts", "market", "event_type", "symbol", "order_id", "client_order_id",
                           "side", "order_type", "status", "exec_type", "price", "orig_qty",
                           "executed_qty", "last_qty", "last_price", "avg_price", "commission",
                           "commission_asset", "realized_pnl", "is_maker", "trade_time"],
    "ACCOUNT_UPDATE": ["ts", "market", "event_type", "reason", "balances_json", "positions_json"],
    "outboundAccountPosition": ["ts", "market", "event_type", "balances_json"],
    "balanceUpdate": ["ts", "market", "event_type", "asset", "delta"],
    "listStatus": ["ts", "market", "event_type", "symbol", "order_list_id", "list_status_type"],
    "listenKeyExpired": ["ts", "market", "event_type"],
}
OTHER_COLUMNS = ["ts", "market", "event_type", "symbol", "raw_json"]


# ---------------------------------------------------------------------------
# 工具
# ---------------------------------------------------------------------------
def iso_from_ms(ms) -> str:
    if ms is None:
        return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")
    return datetime.fromtimestamp(float(ms) / 1000.0, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def num(v):
    """把交易所的字符串数字转 float（None/空串安全）。"""
    if v is None or v == "":
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def sig(v):
    """数值字符串保持原样（用于签名/精确落库）；空值 None。"""
    if v is None or v == "":
        return None
    return str(v)


# ---------------------------------------------------------------------------
# 事件归一化：把三种市场的异构字段变成统一结构
# ---------------------------------------------------------------------------
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


# ---------------------------------------------------------------------------
# Sink
# ---------------------------------------------------------------------------
class BaseSink:
    name = "base"

    def start(self):
        pass

    def write(self, n: dict):
        pass

    def close(self):
        pass


class JsonlSink(BaseSink):
    name = "jsonl"

    def __init__(self, path: str):
        self.path = path
        os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
        self.fh = open(path, "a", encoding="utf-8")

    def write(self, n: dict):
        self.fh.write(json.dumps({"ts": iso_from_ms(n["ts"]), "market": n["market"],
                                  "event": n["raw"]}, ensure_ascii=False) + "\n")
        self.fh.flush()

    def close(self):
        self.fh.close()


class CsvSink(BaseSink):
    name = "csv"

    def __init__(self, dirpath: str):
        self.dir = dirpath
        os.makedirs(dirpath, exist_ok=True)
        self._files: dict[str, tuple] = {}

    def _fh(self, etype: str):
        cols = CSV_COLUMNS.get(etype, OTHER_COLUMNS)
        path = os.path.join(self.dir, f"{etype}.csv")
        if path not in self._files:
            new = not os.path.exists(path) or os.path.getsize(path) == 0
            fh = open(path, "a", newline="", encoding="utf-8")
            w = csv.DictWriter(fh, fieldnames=cols, extrasaction="ignore")
            if new:
                w.writeheader()
            self._files[path] = (fh, w, cols)
        return self._files[path]

    def write(self, n: dict):
        etype = n["event_type"]
        fh, w, cols = self._fh(etype)
        row = {c: None for c in cols}
        row.update({"ts": iso_from_ms(n["ts"]), "market": n["market"], "event_type": etype,
                    "symbol": n.get("symbol")})
        o = n.get("order") or {}
        if o:
            row.update({
                "order_id": o.get("order_id"), "client_order_id": o.get("client_order_id"),
                "side": o.get("side"), "order_type": o.get("order_type"),
                "status": o.get("status"), "exec_type": (n["raw"].get("x") or
                                                          (n["raw"].get("o") or {}).get("x")),
                "price": o.get("price"), "orig_qty": o.get("orig_qty"),
                "executed_qty": o.get("executed_qty"), "last_qty": o.get("last_qty"),
                "last_price": o.get("last_price"), "avg_price": o.get("avg_price"),
                "commission": (n["fills"][0].get("commission") if n["fills"] else None),
                "commission_asset": (n["fills"][0].get("commission_asset") if n["fills"] else None),
                "realized_pnl": o.get("realized_pnl"),
                "is_maker": o.get("is_maker"),
                "trade_time": (iso_from_ms(n["fills"][0]["trade_time"]) if n["fills"] else None),
            })
        if n["balances"]:
            row["balances_json"] = json.dumps(n["balances"], ensure_ascii=False)
        if n["positions"]:
            row["positions_json"] = json.dumps(n["positions"], ensure_ascii=False)
        if n["event_type"] == "ACCOUNT_UPDATE":
            row["reason"] = n.get("reason")
        if n["event_type"] == "balanceUpdate":
            row["asset"] = n.get("asset")
            row["delta"] = n.get("delta")
        if n["event_type"] == "listStatus":
            row["order_list_id"] = n.get("order_list_id")
            row["list_status_type"] = n.get("list_status_type")
        if etype not in CSV_COLUMNS:
            row["raw_json"] = json.dumps(n["raw"], ensure_ascii=False)
        w.writerow(row)
        fh.flush()

    def close(self):
        for fh, _, _ in self._files.values():
            fh.close()


# --- SQL 方言 -------------------------------------------------------------
class SqlBackend:
    """同一套语义 SQL，按方言替换占位符/JSON 类型/upsert。"""
    name = "sql"
    ph = "?"
    json_type = "TEXT"
    ts_type = "TEXT"
    auto_pk = "INTEGER PRIMARY KEY AUTOINCREMENT"
    id_type = "INTEGER"

    def connect(self):
        raise NotImplementedError

    def ensure_schema(self, cur):
        cur.execute(f"""
            CREATE TABLE IF NOT EXISTS stream_events (
              id {self.auto_pk},
              ts {self.ts_type} NOT NULL,
              market TEXT NOT NULL,
              event_type TEXT NOT NULL,
              symbol TEXT,
              raw {self.json_type} NOT NULL
            )""")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_stream_events_ts ON stream_events(ts)")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_stream_events_type ON stream_events(market, event_type)")
        cur.execute(f"""
            CREATE TABLE IF NOT EXISTS orders (
              market TEXT NOT NULL, order_id BIGINT NOT NULL, symbol TEXT,
              client_order_id TEXT, side TEXT, order_type TEXT, status TEXT,
              price NUMERIC, orig_qty NUMERIC, executed_qty NUMERIC, avg_price NUMERIC,
              cum_quote NUMERIC, last_qty NUMERIC, last_price NUMERIC,
              realized_pnl NUMERIC, is_maker BOOLEAN, event_time {self.ts_type},
              updated_at {self.ts_type}, raw {self.json_type},
              PRIMARY KEY (market, order_id)
            )""")
        cur.execute(f"""
            CREATE TABLE IF NOT EXISTS fills (
              market TEXT NOT NULL, order_id BIGINT NOT NULL, trade_id BIGINT,
              symbol TEXT, side TEXT, price NUMERIC, qty NUMERIC, quote_qty NUMERIC,
              commission NUMERIC, commission_asset TEXT, is_maker BOOLEAN,
              realized_pnl NUMERIC, trade_time {self.ts_type} NOT NULL,
              PRIMARY KEY (market, order_id, trade_id, trade_time)
            )""")
        cur.execute(f"""
            CREATE TABLE IF NOT EXISTS balances (
              market TEXT NOT NULL, asset TEXT NOT NULL, free NUMERIC, locked NUMERIC,
              updated_at {self.ts_type}, PRIMARY KEY (market, asset)
            )""")
        cur.execute(f"""
            CREATE TABLE IF NOT EXISTS positions (
              market TEXT NOT NULL, symbol TEXT NOT NULL, position_amt NUMERIC,
              entry_price NUMERIC, unrealized_pnl NUMERIC, updated_at {self.ts_type},
              PRIMARY KEY (market, symbol)
            )""")
        cur.execute(f"""
            CREATE TABLE IF NOT EXISTS account_snapshots (
              id {self.auto_pk}, ts {self.ts_type}, market TEXT, kind TEXT, payload {self.json_type}
            )""")


class SqliteBackend(SqlBackend):
    name = "sqlite"

    def __init__(self, path: str):
        self.path = path

    def connect(self):
        os.makedirs(os.path.dirname(os.path.abspath(self.path)), exist_ok=True)
        return sqlite3.connect(self.path)


class PgBackend(SqlBackend):
    name = "pg"
    ph = "%s"
    json_type = "jsonb"
    ts_type = "TIMESTAMPTZ"
    auto_pk = "BIGSERIAL PRIMARY KEY"

    def __init__(self, dsn: str):
        self.dsn = dsn

    def connect(self):
        try:
            import psycopg  # type: ignore
        except ImportError as e:
            raise RuntimeError(
                "PostgreSQL 需要 psycopg3：\n"
                "  python3 -m venv .venv && .venv/bin/pip install 'psycopg[binary]'\n"
                "然后 .venv/bin/python tools/event_sink.py ..."
            ) from e
        return psycopg.connect(self.dsn)


class SqlSink(BaseSink):
    def __init__(self, backend: SqlBackend):
        self.b = backend
        self.conn = None
        self.cur = None

    @property
    def name(self):
        return self.b.name

    def start(self):
        self.conn = self.b.connect()
        self.cur = self.conn.cursor()
        self.b.ensure_schema(self.cur)
        self.conn.commit()

    def write(self, n: dict):
        ph = self.b.ph
        raw = json.dumps(n["raw"], ensure_ascii=False)
        ts = iso_from_ms(n["ts"])
        self.cur.execute(
            f"INSERT INTO stream_events (ts, market, event_type, symbol, raw) VALUES ({ph},{ph},{ph},{ph},{ph})",
            (ts, n["market"], n["event_type"], n.get("symbol"), raw))
        o = n.get("order")
        if o:
            self.cur.execute(
                f"""INSERT INTO orders (market, order_id, symbol, client_order_id, side, order_type,
                        status, price, orig_qty, executed_qty, avg_price, cum_quote, last_qty,
                        last_price, realized_pnl, is_maker, event_time, updated_at, raw)
                    VALUES ({','.join([ph]*19)})
                    ON CONFLICT (market, order_id) DO UPDATE SET
                        status=EXCLUDED.status, executed_qty=EXCLUDED.executed_qty,
                        avg_price=EXCLUDED.avg_price, cum_quote=EXCLUDED.cum_quote,
                        last_qty=EXCLUDED.last_qty, last_price=EXCLUDED.last_price,
                        realized_pnl=EXCLUDED.realized_pnl, updated_at=EXCLUDED.updated_at,
                        raw=EXCLUDED.raw""",
                (n["market"], int(o["order_id"]), n.get("symbol"), o.get("client_order_id"),
                 o.get("side"), o.get("order_type"), o.get("status"), o.get("price"),
                 o.get("orig_qty"), o.get("executed_qty"), o.get("avg_price"), o.get("cum_quote"),
                 o.get("last_qty"), o.get("last_price"), o.get("realized_pnl"),
                 bool(o.get("is_maker")) if o.get("is_maker") is not None else None,
                 iso_from_ms(o.get("event_time")), ts, raw))
        for f in n["fills"]:
            self.cur.execute(
                f"""INSERT INTO fills (market, order_id, trade_id, symbol, side, price, qty,
                        quote_qty, commission, commission_asset, is_maker, realized_pnl, trade_time)
                    VALUES ({','.join([ph]*13)})
                    ON CONFLICT (market, order_id, trade_id, trade_time) DO NOTHING""",
                (n["market"], int(f["order_id"]), int(f["trade_id"] or 0), n.get("symbol"),
                 (o or {}).get("side"), f.get("price"), f.get("qty"), f.get("quote_qty"),
                 f.get("commission"), f.get("commission_asset"),
                 bool(f.get("is_maker")) if f.get("is_maker") is not None else None,
                 f.get("realized_pnl"), iso_from_ms(f.get("trade_time"))))
        for b in n["balances"]:
            self.cur.execute(
                f"""INSERT INTO balances (market, asset, free, locked, updated_at)
                    VALUES ({','.join([ph]*5)})
                    ON CONFLICT (market, asset) DO UPDATE SET
                        free=COALESCE(EXCLUDED.free, balances.free),
                        locked=COALESCE(EXCLUDED.locked, balances.locked),
                        updated_at=EXCLUDED.updated_at""",
                (n["market"], b.get("asset"), b.get("free"), b.get("locked"), ts))
        for p in n["positions"]:
            self.cur.execute(
                f"""INSERT INTO positions (market, symbol, position_amt, entry_price, unrealized_pnl, updated_at)
                    VALUES ({','.join([ph]*6)})
                    ON CONFLICT (market, symbol) DO UPDATE SET
                        position_amt=EXCLUDED.position_amt, entry_price=EXCLUDED.entry_price,
                        unrealized_pnl=EXCLUDED.unrealized_pnl, updated_at=EXCLUDED.updated_at""",
                (n["market"], p.get("symbol"), p.get("position_amt"), p.get("entry_price"),
                 p.get("unrealized_pnl"), ts))
        if n["balances"] or n["positions"]:
            payload = json.dumps({"balances": n["balances"], "positions": n["positions"]}, ensure_ascii=False)
            kind = "ACCOUNT_UPDATE" if n["event_type"] == "ACCOUNT_UPDATE" else "BALANCE"
            self.cur.execute(
                f"INSERT INTO account_snapshots (ts, market, kind, payload) VALUES ({ph},{ph},{ph},{ph})",
                (ts, n["market"], kind, payload))
        self.conn.commit()

    def close(self):
        if self.conn:
            try:
                self.conn.close()
            except Exception:
                pass


# ---------------------------------------------------------------------------
# 策略信号引擎（示例：订单状态机 + 持仓变化 + 已实现盈亏）
# ---------------------------------------------------------------------------
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


# ---------------------------------------------------------------------------
# 组合 sink（一个事件写给多个目的地）
# ---------------------------------------------------------------------------
class MultiSink(BaseSink):
    def __init__(self, sinks: list[BaseSink]):
        self.sinks = sinks

    @property
    def name(self):
        return "multi"

    def start(self):
        for s in self.sinks:
            s.start()

    def write(self, n: dict):
        for s in self.sinks:
            s.write(n)

    def close(self):
        for s in self.sinks:
            try:
                s.close()
            except Exception:
                pass


def build_sinks(spec: str, out_dir: str, sqlite_path: str | None,
                pg_dsn: str | None, want_signals: bool, quiet: bool) -> list[BaseSink]:
    spec = (spec or "jsonl").lower()
    sinks: list[BaseSink] = []
    parts = [p.strip() for p in spec.split(",") if p.strip()]
    for p in parts:
        if p == "jsonl":
            ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
            sinks.append(JsonlSink(os.path.join(out_dir, f"user_stream_{ts}.jsonl")))
        elif p == "csv":
            sinks.append(CsvSink(os.path.join(out_dir, "csv")))
        elif p == "sqlite":
            sinks.append(SqlSink(SqliteBackend(sqlite_path or os.path.join(out_dir, "binance_stream.db"))))
        elif p == "pg":
            if not pg_dsn:
                raise SystemExit("--sink pg 需要 --pg-dsn")
            sinks.append(SqlSink(PgBackend(pg_dsn)))
        else:
            raise SystemExit(f"未知 sink: {p}（可选 jsonl,csv,sqlite,pg）")
    if want_signals:
        ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        sinks.append(SignalSink(os.path.join(out_dir, f"signals_{ts}.jsonl"), quiet=quiet))
    return sinks


# ---------------------------------------------------------------------------
# CLI：selftest / replay
# ---------------------------------------------------------------------------
FIXTURES = [
    # 现货：新订单 -> 部分成交 -> 全部成交（余额快照）
    {"e": "executionReport", "E": 1794000000000, "s": "BTCUSDT", "c": "demo-1",
     "S": "BUY", "o": "LIMIT", "q": "0.01000000", "p": "75000.00", "X": "NEW", "x": "NEW",
     "i": 1000001, "l": "0", "z": "0", "L": "0", "T": 1794000000000, "m": False},
    {"e": "executionReport", "E": 1794000001000, "s": "BTCUSDT", "c": "demo-1",
     "S": "BUY", "o": "LIMIT", "q": "0.01000000", "p": "75000.00", "X": "PARTIALLY_FILLED",
     "x": "TRADE", "i": 1000001, "l": "0.00400000", "z": "0.00400000", "L": "75000.00",
     "T": 1794000001000, "t": 9001, "n": "0.00000400", "N": "BTC", "m": False},
    {"e": "outboundAccountPosition", "E": 1794000001100, "u": 1794000001100,
     "B": [{"a": "BTC", "f": "0.00400000", "l": "0.00000000"},
           {"a": "USDT", "f": "699.99", "l": "0"}]},
    {"e": "executionReport", "E": 1794000002000, "s": "BTCUSDT", "c": "demo-1",
     "S": "BUY", "o": "LIMIT", "q": "0.01000000", "p": "75000.00", "X": "FILLED",
     "x": "TRADE", "i": 1000001, "l": "0.00600000", "z": "0.01000000", "L": "75000.00",
     "T": 1794000002000, "t": 9002, "n": "0.00000600", "N": "BTC", "m": False},
    {"e": "balanceUpdate", "E": 1794000002100, "a": "USDT", "d": "-750.00", "T": 1794000002100},
    # 合约：开仓 -> 加仓 -> 减仓（ACCOUNT_UPDATE 带持仓）
    {"e": "ORDER_TRADE_UPDATE", "E": 1794000010000, "T": 1794000010000,
     "o": {"s": "ETHUSDT", "c": "f-1", "S": "BUY", "o": "MARKET", "q": "0.500", "p": "0",
           "ap": "2500.0", "x": "NEW", "X": "NEW", "i": 2000001, "l": "0", "z": "0",
           "L": "0", "T": 1794000010000, "t": 0, "m": False, "rp": "0"}},
    {"e": "ORDER_TRADE_UPDATE", "E": 1794000011000, "T": 1794000011000,
     "o": {"s": "ETHUSDT", "c": "f-1", "S": "BUY", "o": "MARKET", "q": "0.500", "p": "0",
           "ap": "2500.0", "x": "TRADE", "X": "FILLED", "i": 2000001, "l": "0.500", "z": "0.500",
           "L": "2500.0", "T": 1794000011000, "t": 18001, "n": "0.05", "N": "USDT", "m": False,
           "rp": "0"}},
    {"e": "ACCOUNT_UPDATE", "E": 1794000011100, "T": 1794000011100,
     "a": {"m": "ORDER", "B": [{"a": "USDT", "wb": "4999.95", "cw": "4999.95", "bc": "0"}],
           "P": [{"s": "ETHUSDT", "pa": "0.500", "ep": "2500.0", "up": "0.0", "mt": "cross", "rw": "0"}]}},
    {"e": "ORDER_TRADE_UPDATE", "E": 1794000015000, "T": 1794000015000,
     "o": {"s": "ETHUSDT", "c": "f-2", "S": "SELL", "o": "MARKET", "q": "0.800", "p": "0",
           "ap": "2550.0", "x": "TRADE", "X": "FILLED", "i": 2000002, "l": "0.800", "z": "0.800",
           "L": "2550.0", "T": 1794000015000, "t": 18002, "n": "0.08", "N": "USDT", "m": False,
           "rp": "40.0"}},
    {"e": "ACCOUNT_UPDATE", "E": 1794000015100, "T": 1794000015100,
     "a": {"m": "ORDER", "B": [{"a": "USDT", "wb": "5040.15", "cw": "5040.15", "bc": "0"}],
           "P": [{"s": "ETHUSDT", "pa": "-0.300", "ep": "2550.0", "up": "0.0", "mt": "cross", "rw": "0"}]}},
    {"e": "listenKeyExpired", "E": 1794000020000},
]


def _fixture_lines():
    return [json.dumps(ev, ensure_ascii=False) for ev in FIXTURES]


def cmd_selftest(args) -> int:
    out = args.out
    os.makedirs(out, exist_ok=True)
    fx = os.path.join(out, "events_demo.jsonl")
    def fixture_market(ev):
        return "spot" if ev.get("e") in ("executionReport", "outboundAccountPosition",
                                         "balanceUpdate", "listStatus") else "um"

    with open(fx, "w", encoding="utf-8") as f:
        for ev in FIXTURES:
            f.write(json.dumps({"ts": iso_from_ms(ev.get("E")), "market": fixture_market(ev),
                                "event": ev}, ensure_ascii=False) + "\n")
    print(f"样例事件 {len(FIXTURES)} 条 -> {fx}")
    db_path = os.path.join(out, "binance_stream.db")
    if os.path.exists(db_path):
        os.remove(db_path)

    pg_before = {}
    if args.pg_dsn:
        try:
            import psycopg  # type: ignore
            with psycopg.connect(args.pg_dsn) as conn, conn.cursor() as cur:
                cur.execute("select to_regclass('public.stream_events')")
                if cur.fetchone()[0]:
                    for t in ("stream_events", "orders", "fills", "balances", "positions"):
                        cur.execute(f"select count(*) from {t}")
                        pg_before[t] = cur.fetchone()[0]
        except Exception as e:
            print("PostgreSQL 预检失败:", e)

    sinks = build_sinks("jsonl,csv,sqlite" + (",pg" if args.pg_dsn else ""),
                        out, db_path, args.pg_dsn,
                        want_signals=True, quiet=False)
    multi = MultiSink(sinks)
    multi.start()
    try:
        for ev in FIXTURES:
            market = "spot" if ev.get("e") in ("executionReport", "outboundAccountPosition",
                                               "balanceUpdate", "listStatus") else "um"
            multi.write(normalize(market, ev))
    finally:
        multi.close()

    # 校验 SQLite 行数
    db = sqlite3.connect(db_path)
    counts = {}
    for t in ("stream_events", "orders", "fills", "balances", "positions", "account_snapshots"):
        try:
            counts[t] = db.execute(f"select count(*) from {t}").fetchone()[0]
        except sqlite3.Error as e:
            counts[t] = f"ERR {e}"
    db.close()
    print("SQLite 行数:", counts)

    # PG 校验
    if args.pg_dsn:
        try:
            import psycopg  # type: ignore
            with psycopg.connect(args.pg_dsn) as conn:
                with conn.cursor() as cur:
                    pg = {}
                    for t in ("stream_events", "orders", "fills", "balances", "positions"):
                        cur.execute(f"select count(*) from {t}")
                        pg[t] = cur.fetchone()[0]
            delta = {t: pg[t] - pg_before.get(t, 0) for t in pg}
            print("PostgreSQL 行数:", pg, "本轮增量:", delta)
        except Exception as e:
            print("PostgreSQL 校验失败:", e)
            return 1

    ok = (counts.get("stream_events") == len(FIXTURES)
          and counts.get("orders") == 3
          and counts.get("fills") == 4)
    if args.pg_dsn:
        ok = ok and delta.get("stream_events") == len(FIXTURES)
        ok = ok and pg.get("orders", 0) >= 3 and pg.get("fills", 0) >= 4
    print("SELFTEST", "PASS" if ok else "FAIL")
    return 0 if ok else 1


def cmd_replay(args) -> int:
    out = args.out
    os.makedirs(out, exist_ok=True)
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    signal_path = os.path.join(out, f"signals_replay_{ts}.jsonl")
    sig_sink = SignalSink(signal_path, quiet=False)
    n = 0
    with open(args.file, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            rec = json.loads(line)
            ev = rec.get("event") or rec
            market = rec.get("market") or ("spot" if ev.get("e") in
                                           ("executionReport", "outboundAccountPosition",
                                            "balanceUpdate", "listStatus") else "um")
            sig_sink.write(normalize(market, ev))
            n += 1
    sig_sink.close()
    print(f"回放 {n} 条事件，信号 {sig_sink.count} 条 -> {signal_path}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="币安用户事件落库 + 策略信号示例")
    sub = p.add_subparsers(dest="cmd", required=True)
    sp = sub.add_parser("selftest", help="用内置样例验证 CSV/SQLite/PG + 信号")
    sp.add_argument("--out", default="work/signals/selftest")
    sp.add_argument("--pg-dsn", default=None)
    sp.set_defaults(func=cmd_selftest)
    sp = sub.add_parser("replay", help="回放 JSONL 并产出信号")
    sp.add_argument("--file", required=True)
    sp.add_argument("--out", default="work/signals")
    sp.set_defaults(func=cmd_replay)
    return p


def main() -> int:
    args = build_parser().parse_args()
    try:
        return args.func(args)
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    sys.exit(main())
