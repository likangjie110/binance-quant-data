"""sink 落库语义：计数、幂等、CSV 产物。"""
import json
import sqlite3

import event_sink as es


def _feed(sinks, markets=None):
    multi = es.MultiSink(sinks)
    multi.start()
    try:
        for ev in es.FIXTURES:
            etype = ev.get("e")
            market = "spot" if etype in ("executionReport", "outboundAccountPosition",
                                         "balanceUpdate", "listStatus") else "um"
            multi.write(es.normalize(market, ev))
    finally:
        multi.close()


def _counts(db_path):
    db = sqlite3.connect(db_path)
    try:
        return {t: db.execute(f"select count(*) from {t}").fetchone()[0]
                for t in ("stream_events", "orders", "fills", "balances", "positions", "account_snapshots")}
    finally:
        db.close()


def test_sqlite_counts(tmp_path):
    db = tmp_path / "binance_stream.db"
    sinks = es.build_sinks("sqlite", str(tmp_path), str(db), None, want_signals=False, quiet=True)
    _feed(sinks)
    counts = _counts(db)
    assert counts["stream_events"] == len(es.FIXTURES)
    assert counts["orders"] == 3
    assert counts["fills"] == 4
    assert counts["balances"] == 3
    assert counts["positions"] == 1
    assert counts["account_snapshots"] == 3


def test_sqlite_idempotent_on_replay(tmp_path):
    db = tmp_path / "binance_stream.db"
    for _ in range(2):
        sinks = es.build_sinks("sqlite", str(tmp_path), str(db), None, want_signals=False, quiet=True)
        _feed(sinks)
    counts = _counts(db)
    assert counts["stream_events"] == 2 * len(es.FIXTURES)   # 原始事件追加
    assert counts["orders"] == 3                             # 订单 upsert
    assert counts["fills"] == 4                              # 成交去重
    assert counts["positions"] == 1


def test_jsonl_and_csv_outputs(tmp_path):
    sinks = es.build_sinks("jsonl,csv", str(tmp_path), None, None, want_signals=False, quiet=True)
    _feed(sinks)
    jsonl = list(tmp_path.glob("user_stream_*.jsonl"))
    assert len(jsonl) == 1
    rows = [json.loads(line) for line in jsonl[0].read_text(encoding="utf-8").splitlines()]
    assert len(rows) == len(es.FIXTURES)
    assert rows[0]["market"] in ("spot", "um")

    csv_dir = tmp_path / "csv"
    files = {p.name for p in csv_dir.glob("*.csv")}
    assert {"executionReport.csv", "ORDER_TRADE_UPDATE.csv", "ACCOUNT_UPDATE.csv"} <= files
    header = (csv_dir / "executionReport.csv").read_text(encoding="utf-8").splitlines()[0]
    assert "order_id" in header and "executed_qty" in header
