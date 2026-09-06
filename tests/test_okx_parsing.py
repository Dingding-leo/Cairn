from cairn.models import InstrumentType
from cairn.okx import OKXPublicClient


class FixtureClient(OKXPublicClient):
    def __init__(self, responses):
        super().__init__()
        self.responses = responses

    def _get(self, path, params):
        key = (path, tuple(sorted(params.items())))
        return self.responses[key]


def test_instruments_normalize_spot_contract():
    client = FixtureClient({
        ("/api/v5/public/instruments", (("instType", "SPOT"),)): [
            {"instId":"BTC-USDT","state":"live","baseCcy":"BTC","quoteCcy":"USDT","tickSz":"0.1","lotSz":"0.00000001","minSz":"0.00001"}
        ]
    })
    rows = client.instruments(InstrumentType.SPOT)
    assert rows[0].inst_id == "BTC-USDT"
    assert rows[0].quote_ccy == "USDT"


def test_tickers_drop_stale_quotes():
    now = 2_000_000
    client = FixtureClient({
        ("/api/v5/market/tickers", (("instType", "SPOT"),)): [
            {"instId":"BTC-USDT","ts":str(now),"last":"100","bidPx":"99","askPx":"101","bidSz":"2","askSz":"2","vol24h":"5","volCcy24h":"500"},
            {"instId":"ETH-USDT","ts":"1","last":"10","bidPx":"9","askPx":"11","bidSz":"2","askSz":"2","vol24h":"5","volCcy24h":"50"}
        ]
    })
    rows = client.tickers(InstrumentType.SPOT, now_ms=now)
    assert [row.inst_id for row in rows] == ["BTC-USDT"]


def test_candles_remove_unconfirmed_and_sort():
    client = FixtureClient({
        ("/api/v5/market/history-candles", (("bar", "1H"), ("instId", "BTC-USDT"), ("limit", "3"))): [
            ["7200001","2","3","1","2","10","0","0","0"],
            ["3600001","1","2","1","2","10","0","0","1"],
            ["1","1","1","1","1","10","0","0","1"]
        ]
    })
    rows = client.candles("BTC-USDT", limit=3)
    assert [row.ts_ms for row in rows] == [1, 3600001]


def test_order_book_requires_single_snapshot():
    client = FixtureClient({
        ("/api/v5/market/books", (("instId", "BTC-USDT"), ("sz", "20"))): [
            {"bids":[["99","1","0","1"]],"asks":[["101","1","0","1"]],"ts":"1"}
        ]
    })
    book = client.order_book("BTC-USDT")
    assert book["bids"][0][0] == "99"
