"""统一 CLI 入口（console_scripts: binance-tools）。"""
from __future__ import annotations

import sys

from . import event_cli, private, public

PUBLIC_CMDS = ("klines", "ticker24h", "depth", "exchangeinfo", "symbols")
PRIVATE_CMDS = ("selftest", "check", "snapshot", "listen")

USAGE = """binance-tools <命令> [参数]

公开行情：klines | ticker24h | depth | exchangeinfo | symbols
私有推送：selftest | check | snapshot | listen
落库/信号：replay | sink-selftest

示例：
  binance-tools klines --market spot --symbol BTCUSDT --interval 1h --limit 24
  binance-tools listen --markets spot --sink jsonl,csv --signals --out work/private
  binance-tools replay --file work/private/user_stream_x.jsonl --out work/signals
"""


def main(argv=None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if not argv or argv[0] in ("-h", "--help"):
        print(USAGE)
        return 0
    cmd = argv[0]
    if cmd in PUBLIC_CMDS:
        return public.main(argv)
    if cmd in PRIVATE_CMDS:
        return private.main(argv)
    if cmd == "replay":
        return event_cli.main(argv)
    if cmd == "sink-selftest":
        return event_cli.main(["selftest"] + argv[1:])
    print(f"未知命令：{cmd}\n")
    print(USAGE)
    return 1


def pull_main(argv=None) -> int:
    """兼容入口：tools/binance_pull.py。"""
    return public.main(argv)


def private_main(argv=None) -> int:
    """兼容入口：tools/binance_user_stream.py。"""
    return private.main(argv)


def event_main(argv=None) -> int:
    """兼容入口：tools/event_sink.py。"""
    return event_cli.main(argv)
