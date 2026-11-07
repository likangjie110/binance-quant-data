"""签名：REST 与实际发送 query 一致；WS API 用 UTF-8 原值（官方规则）。"""
from __future__ import annotations

import hashlib
import hmac
import urllib.parse


def sign_payload(secret: str, payload: str) -> str:
    """对给定 payload 做 HMAC-SHA256（十六进制）。"""
    return hmac.new(secret.encode("utf-8"), payload.encode("utf-8"), hashlib.sha256).hexdigest()


def sign_rest(secret: str, params: dict) -> str:
    """REST 签名：参数名 ASCII 排序，值 percent-encode 后拼 key=value&...（与发送的 query 一致）。"""
    payload = "&".join(
        f"{k}={urllib.parse.quote(str(v), safe='')}" for k, v in sorted(params.items())
    )
    return sign_payload(secret, payload)


def sign_ws(secret: str, params: dict) -> str:
    """WS API 签名：参数名排序，值用 UTF-8 原值（官方规则不做 percent-encode）。"""
    payload = "&".join(f"{k}={v}" for k, v in sorted(params.items()))
    return sign_payload(secret, payload)
