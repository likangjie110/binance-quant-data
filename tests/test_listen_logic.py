"""监听循环的纯逻辑单测（不碰网络）。"""
from binance_tools.private import _idle_expired


def test_idle_expired_boundary():
    assert _idle_expired(100.0, 180.0, now=200.0) is False
    assert _idle_expired(100.0, 180.0, now=281.0) is True
    assert _idle_expired(100.0, 0, now=10 ** 9) is False   # 0 = 禁用
