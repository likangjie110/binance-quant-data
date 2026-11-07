#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""私有实时推送（兼容入口）：转发到 binance_tools（批次 2 包化后的薄壳，保证旧命令可用）。

优先使用统一入口：
    binance-tools <命令> ...
或（无需安装）：
    python3 -m binance_tools <命令> ...
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from binance_tools.cli import private_main  # noqa: E402

if __name__ == "__main__":
    sys.exit(private_main())
