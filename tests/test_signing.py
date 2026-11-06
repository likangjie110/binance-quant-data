"""签名算法：对照币安官方测试向量（REST/WS API 通用规则）。"""
import pytest

from binance_user_stream import sign_rest

SECRET = "NhqPtmdSJYdKjVHjA7PZj4Mge3R5YNiP1e3UZjInClVN65XAbvqqM6A7H5fATj0j"
API_KEY = "vmPUZE6mv9SD5VNHk4HlWFsOr6aKE2zvsw0MuIgwCIPy6utIco14y7Ju91duEh8A"


def test_official_vector_ascii():
    params = {
        "apiKey": API_KEY,
        "price": "52000.00",
        "quantity": "0.01000000",
        "recvWindow": 100,
        "side": "SELL",
        "symbol": "BTCUSDT",
        "timeInForce": "GTC",
        "timestamp": 1645423376532,
        "type": "LIMIT",
    }
    assert sign_rest(SECRET, params) == (
        "aa1b5712c094bc4e57c05a1a5c1fd8d88dcd628338ea863fec7b88e59fe2db24"
    )


@pytest.mark.xfail(strict=True, reason="TD-SIGN-001：WS API 签名不应 percent-encode；批次 1 修复后删除标记")
def test_official_vector_non_ascii():
    params = {
        "apiKey": API_KEY,
        "price": "0.10000000",
        "quantity": "1.00000000",
        "recvWindow": 5000,
        "side": "BUY",
        "symbol": "１２３４５６",
        "timeInForce": "GTC",
        "timestamp": 1645423376532,
        "type": "LIMIT",
    }
    assert sign_rest(SECRET, params) == (
        "b33892ae8e687c939f4468c6268ddd4c40ac1af18ad19a064864c47bae0752cd"
    )


def test_signature_changes_with_payload():
    a = sign_rest(SECRET, {"timestamp": 1, "apiKey": API_KEY})
    b = sign_rest(SECRET, {"timestamp": 2, "apiKey": API_KEY})
    assert a != b


def test_signature_is_order_independent():
    """参数按名排序后签名，插入顺序不影响结果。"""
    a = sign_rest(SECRET, {"a": "1", "b": "2", "timestamp": 100})
    b = sign_rest(SECRET, {"timestamp": 100, "b": "2", "a": "1"})
    assert a == b
