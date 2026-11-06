"""CLI 冒烟：三个脚本的 --help 必须可执行（保证导入/依赖没有断）。"""
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize("script", [
    "tools/binance_pull.py",
    "tools/binance_user_stream.py",
    "tools/event_sink.py",
])
def test_cli_help(script):
    proc = subprocess.run([sys.executable, script, "--help"],
                          cwd=ROOT, capture_output=True, text=True, timeout=60)
    assert proc.returncode == 0, proc.stderr
    assert "usage:" in proc.stdout
