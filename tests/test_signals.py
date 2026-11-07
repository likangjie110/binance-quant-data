"""策略信号引擎：订单状态机、持仓变化、已实现盈亏。"""
import json

from binance_tools.fixtures import FIXTURES
from binance_tools.normalize import normalize
from binance_tools.signals import SignalSink


def _signals(tmp_path):
    path = tmp_path / "signals.jsonl"
    sink = SignalSink(str(path), quiet=True)
    for ev in FIXTURES:
        etype = ev.get("e")
        market = "spot" if etype in ("executionReport", "outboundAccountPosition",
                                     "balanceUpdate", "listStatus") else "um"
        sink.write(normalize(market, ev))
    sink.close()
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def test_signal_sequence(tmp_path):
    sigs = _signals(tmp_path)
    names = [s["signal"] for s in sigs]

    assert names[0] == "ORDER_PLACED"
    assert "FILL" in names
    assert "POSITION_OPENED" in names
    assert "POSITION_INCREASED" in names
    assert "POSITION_FLIPPED" in names
    assert "ORDER_FILLED" in names
    assert "BALANCE_CHANGED" in names


def test_position_tracking(tmp_path):
    sigs = _signals(tmp_path)
    fills = [s for s in sigs if s["signal"] == "FILL"]
    assert fills[0]["position_before"] == 0.0
    assert fills[0]["position_after"] == 0.004
    # 最后一笔为卖出 0.8，持仓从 0.5 翻到 -0.3
    last = fills[-1]
    assert last["position_before"] == 0.5
    assert last["position_after"] == -0.3


def test_realized_pnl(tmp_path):
    sigs = _signals(tmp_path)
    pnl = [s for s in sigs if s["signal"] == "PNL_REALIZED"]
    assert len(pnl) == 1
    assert pnl[0]["delta"] == 40.0
    assert pnl[0]["cumulative"] == 40.0
