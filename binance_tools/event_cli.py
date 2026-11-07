"""落库/信号 CLI：selftest 与 replay（由 tools/event_sink.py 与统一 CLI 调用）。"""
from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
from datetime import datetime, timezone

from .common import iso_from_ms
from .fixtures import FIXTURES
from .normalize import normalize
from .signals import SignalSink
from .sinks import MultiSink, build_sinks


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


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return args.func(args)
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    sys.exit(main())
