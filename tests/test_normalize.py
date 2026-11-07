"""事件归一化：三类市场异构字段 → 统一结构。"""
from binance_tools.fixtures import FIXTURES
from binance_tools.normalize import normalize


def _fixture(event_type):
    return next(e for e in FIXTURES if e.get("e") == event_type)


def test_spot_execution_report_trade():
    ev = next(e for e in FIXTURES
              if e.get("e") == "executionReport" and e.get("x") == "TRADE" and e.get("t") == 9001)
    n = normalize("spot", ev)
    assert n["market"] == "spot"
    assert n["event_type"] == "executionReport"
    assert n["symbol"] == "BTCUSDT"
    assert n["order"]["order_id"] == 1000001
    assert n["order"]["status"] == "PARTIALLY_FILLED"
    assert n["order"]["executed_qty"] == "0.00400000"
    assert len(n["fills"]) == 1
    fill = n["fills"][0]
    assert fill["trade_id"] == 9001
    assert fill["price"] == "75000.00"
    assert fill["commission_asset"] == "BTC"


def test_futures_order_trade_update():
    ev = next(e for e in FIXTURES
              if e.get("e") == "ORDER_TRADE_UPDATE" and e["o"].get("X") == "FILLED")
    n = normalize("um", ev)
    assert n["symbol"] == "ETHUSDT"
    assert n["order"]["avg_price"] == "2500.0"
    assert n["order"]["realized_pnl"] == "0"
    assert len(n["fills"]) == 1
    assert n["fills"][0]["qty"] == "0.500"


def test_account_update_positions_and_balances():
    ev = next(e for e in FIXTURES if e.get("e") == "ACCOUNT_UPDATE")
    n = normalize("um", ev)
    assert n["reason"] == "ORDER"
    assert n["balances"][0]["asset"] == "USDT"
    assert n["balances"][0]["free"] == "4999.95"
    assert n["positions"][0]["symbol"] == "ETHUSDT"
    assert n["positions"][0]["position_amt"] == "0.500"


def test_outbound_account_position():
    ev = _fixture("outboundAccountPosition")
    n = normalize("spot", ev)
    assets = {b["asset"]: b for b in n["balances"]}
    assert assets["BTC"]["free"] == "0.00400000"
    assert assets["USDT"]["free"] == "699.99"


def test_balance_update():
    ev = _fixture("balanceUpdate")
    n = normalize("spot", ev)
    assert n["asset"] == "USDT"
    assert n["delta"] == "-750.00"


def test_unknown_event_is_safe():
    n = normalize("spot", {"e": "somethingNew", "E": 1})
    assert n["event_type"] == "somethingNew"
    assert n["order"] is None
    assert n["fills"] == []
