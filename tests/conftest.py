"""pytest 共享夹具：把 tools/ 挂到 sys.path（批次 2 包化后改为包导入）。"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TOOLS = ROOT / "tools"
if str(TOOLS) not in sys.path:
    sys.path.insert(0, str(TOOLS))
