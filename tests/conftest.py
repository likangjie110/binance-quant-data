"""pytest 共享夹具：把仓库根加入 sys.path（包化后直接 import binance_tools）。"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
