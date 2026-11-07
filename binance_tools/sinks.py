"""落库适配器：JSONL / CSV / SQLite / PostgreSQL（统一 build_sinks 工厂）。

写入语义：orders upsert、fills 去重、balances/positions upsert、stream_events 追加。
"""
from __future__ import annotations

import csv
import json
import os
import sqlite3
from datetime import datetime, timezone

from .common import iso_from_ms


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
        from .signals import SignalSink  # 延迟导入：signals 依赖 sinks.BaseSink，避免循环
        ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        sinks.append(SignalSink(os.path.join(out_dir, f"signals_{ts}.jsonl"), quiet=quiet))
    return sinks
