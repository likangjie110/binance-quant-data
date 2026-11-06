"""P0 回归占位：多市场监听共享 DB 连接（TD-RUNTIME-001）。

当前缺陷未修（批次 1 修复），测试以 xfail(strict=True) 记录：
  - 现在：测试失败 → xfail，CI 通过；
  - 批次 1 修复后：测试应通过 → XPASS(strict) 会让 CI 失败，提醒把标记转正。
"""
import sqlite3
import threading

import pytest

import binance_user_stream as bus
import event_sink as es

pytestmark = pytest.mark.p0


@pytest.mark.xfail(strict=True, reason="TD-RUNTIME-001：跨线程共享 SQLite 连接，批次 1 修复后删除本标记")
def test_multi_market_concurrent_write(tmp_path):
    db = tmp_path / "binance_stream.db"
    sinks = es.build_sinks("sqlite", str(tmp_path), str(db), None, want_signals=False, quiet=True)
    writer = bus.StreamWriter(sinks, quiet=True)
    writer.start()  # 连接在主线程创建

    errors = []

    def worker(market, event_type):
        try:
            for ev in es.FIXTURES:
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

    assert errors == [], f"并发写入抛错：{errors[:2]}"
    db_conn = sqlite3.connect(db)
    try:
        rows = db_conn.execute("select count(*) from stream_events").fetchone()[0]
    finally:
        db_conn.close()
    assert rows == 6  # 3 条现货 executionReport + 3 条合约 ORDER_TRADE_UPDATE
