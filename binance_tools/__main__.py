"""支持 python3 -m binance_tools <命令>（无需安装）。"""
import sys

from .cli import main

if __name__ == "__main__":
    sys.exit(main())
