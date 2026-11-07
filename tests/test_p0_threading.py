"""P0 回归：多市场监听共享 DB 连接（TD-RUNTIME-001，批次 1 已修复）。

修复方式：监听线程只入队，单写线程独占 sink 连接与信号状态。
本测试并发写入 6 条事件，要求 0 异常、0 写入失败、落库条数正确。
"""
import sqlite3
import threading

from binance_tools import private as bus
from binance_tools import sinks as es
from binance_tools.fixtures import FIXTURES


def test_multi_market_concurrent_write(tmp_path):
    db = tmp_path / "binance_stream.db"

    def factory():
        return es.build_sinks("sqlite", str(tmp_path), str(db),
                              None, want_signals=False, quiet=True)

    writer = bus.StreamWriter(factory, quiet=True)
    writer.start()

    errors = []

    def worker(market, event_type):
        try:
            for ev in FIXTURES:
                if ev.get("e") == event_type:
                    writer.write(market, ev)
        except Exception as exc:  # noqa: BLE001 - 记录线程内异常用于断言
            errors.append(exc)

    threads = [threading.Thread(target=worker, args=("spot", "executionReport")),
               threading.Thread(target=worker, args=("um", "ORDER_TRADE_UPDATE"))]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    writer.close()

    assert errors == []
    assert writer.sink_errors == 0
    assert writer.count == 6
    db_conn = sqlite3.connect(db)
    try:
        rows = db_conn.execute("select count(*) from stream_events").fetchone()[0]
    finally:
        db_conn.close()
    assert rows == 6


def test_close_drains_queue(tmp_path):
    db = tmp_path / "drain.db"

    def factory():
        return es.build_sinks("sqlite", str(tmp_path), str(db),
                              None, want_signals=False, quiet=True)

    writer = bus.StreamWriter(factory, quiet=True)
    writer.start()
    for ev in FIXTURES:
        market = "spot" if ev.get("e") in ("executionReport", "outboundAccountPosition",
                                          "balanceUpdate", "listStatus") else "um"
        writer.write(market, ev)
    writer.close()
    assert writer.count == len(FIXTURES)
    assert writer.dropped == 0
