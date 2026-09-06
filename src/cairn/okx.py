from __future__ import annotations

import json
import re
import ssl
import time
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlencode, urlsplit
from urllib.request import Request, build_opener, HTTPSHandler

from .models import Candle, InstrumentType, MarketQuote, OKXInstrument

_ALLOWED_HOSTS = frozenset({"openapi.okx.com", "www.okx.com", "eea.okx.com"})
_INST_ID = re.compile(r"^[A-Z0-9][A-Z0-9._-]{1,79}$")


class OKXError(RuntimeError):
    pass


@dataclass(frozen=True)
class OKXPolicy:
    host: str = "openapi.okx.com"
    timeout_seconds: float = 10.0
    max_response_bytes: int = 5_000_000
    max_quote_age_ms: int = 120_000

    def __post_init__(self) -> None:
        if self.host not in _ALLOWED_HOSTS:
            raise ValueError(f"unapproved OKX host: {self.host}")
        if not (0 < self.timeout_seconds <= 30):
            raise ValueError("timeout must be in (0, 30]")
        if not (1_000 <= self.max_response_bytes <= 20_000_000):
            raise ValueError("response limit outside allowed range")


class _NoRedirect:
    def redirect_request(self, req: Any, fp: Any, code: int, msg: str, headers: Any, newurl: str):
        raise OKXError(f"redirect refused: {code} {newurl}")


class OKXPublicClient:
    """Small, read-only OKX REST client.

    This client deliberately implements public GET surfaces only. It has no API-key,
    signature, private endpoint, order, transfer, or withdrawal path.
    """

    def __init__(self, policy: OKXPolicy | None = None) -> None:
        self.policy = policy or OKXPolicy()
        context = ssl.create_default_context()
        self._opener = build_opener(HTTPSHandler(context=context))

    def _get(self, path: str, params: dict[str, str]) -> list[dict[str, Any]]:
        if not path.startswith("/api/v5/") or ".." in path:
            raise OKXError("invalid OKX path")
        query = urlencode(params)
        url = f"https://{self.policy.host}{path}" + (f"?{query}" if query else "")
        split = urlsplit(url)
        if split.scheme != "https" or split.hostname != self.policy.host:
            raise OKXError("request escaped configured host")
        request = Request(
            url,
            method="GET",
            headers={
                "Accept": "application/json",
                "Accept-Encoding": "identity",
                "User-Agent": "Cairn/0.5 research-only",
            },
        )
        try:
            with self._opener.open(request, timeout=self.policy.timeout_seconds) as response:
                if response.status != 200:
                    raise OKXError(f"HTTP {response.status}")
                length = response.headers.get("Content-Length")
                if length and int(length) > self.policy.max_response_bytes:
                    raise OKXError("response exceeds configured size limit")
                raw = response.read(self.policy.max_response_bytes + 1)
        except OKXError:
            raise
        except Exception as exc:  # network boundary
            raise OKXError(f"OKX request failed: {type(exc).__name__}") from exc
        if len(raw) > self.policy.max_response_bytes:
            raise OKXError("response exceeds configured size limit")
        try:
            payload = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise OKXError("invalid OKX JSON response") from exc
        if not isinstance(payload, dict) or payload.get("code") != "0":
            raise OKXError(f"OKX error response: {payload.get('code') if isinstance(payload, dict) else '?'}")
        data = payload.get("data")
        if not isinstance(data, list):
            raise OKXError("OKX data field is not a list")
        return data

    @staticmethod
    def _type(value: str) -> InstrumentType:
        try:
            return InstrumentType(value)
        except ValueError as exc:
            raise OKXError(f"unsupported instrument type: {value}") from exc

    def instruments(self, inst_type: InstrumentType) -> list[OKXInstrument]:
        rows = self._get("/api/v5/public/instruments", {"instType": inst_type.value})
        result: list[OKXInstrument] = []
        for row in rows:
            inst_id = str(row.get("instId", ""))
            if not _INST_ID.fullmatch(inst_id):
                raise OKXError("invalid instrument identity in provider response")
            expiry = str(row.get("expTime", "") or "")
            result.append(
                OKXInstrument(
                    inst_id=inst_id,
                    inst_type=inst_type,
                    state=str(row.get("state", "unknown")),
                    base_ccy=str(row.get("baseCcy", "") or "") or None,
                    quote_ccy=str(row.get("quoteCcy", "") or "") or None,
                    settle_ccy=str(row.get("settleCcy", "") or "") or None,
                    tick_sz=str(row.get("tickSz", "") or "") or None,
                    lot_sz=str(row.get("lotSz", "") or "") or None,
                    min_sz=str(row.get("minSz", "") or "") or None,
                    ct_val=str(row.get("ctVal", "") or "") or None,
                    ct_val_ccy=str(row.get("ctValCcy", "") or "") or None,
                    expiry_ms=int(expiry) if expiry.isdigit() else None,
                )
            )
        return result

    def tickers(self, inst_type: InstrumentType, *, now_ms: int | None = None) -> list[MarketQuote]:
        rows = self._get("/api/v5/market/tickers", {"instType": inst_type.value})
        current = now_ms if now_ms is not None else int(time.time() * 1000)
        quotes: list[MarketQuote] = []
        for row in rows:
            ts_text = str(row.get("ts", ""))
            if not ts_text.isdigit():
                raise OKXError("ticker timestamp missing")
            ts = int(ts_text)
            if ts > current + 5_000:
                raise OKXError("future ticker refused")
            if current - ts > self.policy.max_quote_age_ms:
                continue
            quotes.append(
                MarketQuote(
                    inst_id=str(row["instId"]),
                    inst_type=inst_type,
                    ts_ms=ts,
                    last=str(row["last"]),
                    bid=str(row.get("bidPx", "") or "") or None,
                    ask=str(row.get("askPx", "") or "") or None,
                    bid_sz=str(row.get("bidSz", "") or "") or None,
                    ask_sz=str(row.get("askSz", "") or "") or None,
                    vol_24h=str(row.get("vol24h", "") or "") or None,
                    vol_ccy_24h=str(row.get("volCcy24h", "") or "") or None,
                    source="OKX_PUBLIC",
                )
            )
        return quotes

    def candles(self, inst_id: str, *, bar: str = "1H", limit: int = 200) -> list[Candle]:
        if not _INST_ID.fullmatch(inst_id):
            raise ValueError("invalid inst_id")
        if bar != "1H":
            raise ValueError("v0.5 market diagnostics are intentionally fixed to 1H")
        if not (2 <= limit <= 300):
            raise ValueError("candle limit must be between 2 and 300")
        rows = self._get(
            "/api/v5/market/history-candles",
            {"instId": inst_id, "bar": bar, "limit": str(limit)},
        )
        candles: list[Candle] = []
        for row in rows:
            if not isinstance(row, list) or len(row) < 9:
                raise OKXError("malformed candle")
            candles.append(
                Candle(
                    inst_id=inst_id,
                    ts_ms=int(row[0]),
                    open=str(row[1]),
                    high=str(row[2]),
                    low=str(row[3]),
                    close=str(row[4]),
                    volume=str(row[5]),
                    confirm=str(row[8]) == "1",
                )
            )
        candles.sort(key=lambda x: x.ts_ms)
        return [c for c in candles if c.confirm]

    def order_book(self, inst_id: str, depth: int = 20) -> dict[str, Any]:
        if not _INST_ID.fullmatch(inst_id):
            raise ValueError("invalid inst_id")
        if depth not in {5, 10, 20, 50}:
            raise ValueError("unsupported depth")
        rows = self._get("/api/v5/market/books", {"instId": inst_id, "sz": str(depth)})
        if len(rows) != 1:
            raise OKXError("expected one order-book snapshot")
        book = rows[0]
        if not isinstance(book.get("bids"), list) or not isinstance(book.get("asks"), list):
            raise OKXError("malformed order book")
        return book
