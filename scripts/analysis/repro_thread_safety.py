#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
repro_thread_safety.py —— 复现 `listen --markets spot,um --sink sqlite` 的并发写缺陷

背景：
  tools/binance_user_stream.py 的 cmd_listen 用 ThreadPoolExecutor 给每个市场起一个监听线程，
  这些线程共享同一个 StreamWriter（进而共享同一个 SQLite/PostgreSQL 连接）。
  Python sqlite3 默认 check_same_thread=True：连接在主线程创建，工作线程写入即抛异常。

本脚本只读复现，不修改业务代码：
  python3 scripts/analysis/repro_thread_safety.py
退出码：0 = 成功复现（缺陷仍在）；1 = 未复现（已修复/需复核）
"""
import os
import sys
import tempfile
import traceback
from concurrent.futures import ThreadPoolExecutor

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)

from binance_tools import private as bus  # noqa: E402
from binance_tools import sinks as es  # noqa: E402
from binance_tools.fixtures import FIXTURES  # noqa: E402


def main() -> int:
    tmp = tempfile.mkdtemp(prefix="repro-ts-")
    db = os.path.join(tmp, "binance_stream.db")
    def sink_factory():
        return es.build_sinks("sqlite", tmp, db, None, want_signals=True, quiet=True)

    writer = bus.StreamWriter(sink_factory, quiet=True)
    writer.start()  # sink 在 writer 线程创建（批次 1 修复后）

    errors = []

    def worker(market, etype):
        try:
            for ev in FIXTURES[:4]:
                if ev.get("e") != etype:
                    continue
                writer.write(market, ev)
        except Exception as e:  # noqa: BLE001
            errors.append((market, type(e).__name__, str(e)[:200], traceback.format_exc()[:800]))

    # 模拟 spot / um 两个监听线程同时写入
    with ThreadPoolExecutor(max_workers=2) as ex:
        futs = [ex.submit(worker, "spot", "executionReport"),
                ex.submit(worker, "um", "ORDER_TRADE_UPDATE")]
        for f in futs:
            f.result()
    writer.close()

    print(f"临时目录: {tmp}")
    print(f"writer: 写入 {writer.count} 条，丢弃 {writer.dropped} 条，失败 {writer.sink_errors} 条")
    if errors:
        print(f"复现成功：{len(errors)} 个线程写入抛错")
        for market, etype, msg, tb in errors:
            print(f"- [{market}] {etype}: {msg}")
        print("\n根因：cmd_listen 的多个监听线程共享同一个 SqlSink 连接"
              "（sqlite3 连接默认只能创建线程使用；psycopg 连接同样不支持并发使用）。")
        return 0
    print("未复现：并发写入无异常（P0 已修复，退出码 1）")
    return 1


if __name__ == "__main__":
    sys.exit(main())
