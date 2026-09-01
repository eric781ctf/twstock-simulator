"""極短效期的即時報價快取，給「送出當下就要成交」的情境（市價單、盤後單、
停損單觸發成交）當緩解機制用——這些情境本來各自都要臨時打一次 mis.twse。

大部分時候要下市價單的股票，剛好都是使用者才剛在下單面板選過（會觸發
/stocks/{code}/quote）、或本來就在自選股/持股裡（每 7 秒的批次輪詢會定期
更新），這個快取讓這些情況可以直接沿用最近抓到的報價，不用再多打一次。
只有完全沒被查過的冷門股票才會真的觸發一次新的請求。

TTL 刻意設得比撮合輪詢間隔（預設 7 秒）稍長一點，確保「輪詢剛更新完」到
「使用者按下送出」這段時間內快取都還有效。"""

import time

from app.services.twse_client import fetch_quotes

_TTL_SECONDS = 8.0
_cache: dict[str, tuple[dict, float]] = {}


def store_many(quotes: dict[str, dict]) -> None:
    now = time.time()
    for code, quote in quotes.items():
        _cache[code] = (quote, now)


def _get_fresh(code: str) -> dict | None:
    entry = _cache.get(code)
    if entry is None:
        return None
    quote, ts = entry
    if time.time() - ts > _TTL_SECONDS:
        return None
    return quote


async def get_quotes_cached(codes_with_market: list[tuple[str, str]]) -> dict[str, dict]:
    """跟 fetch_quotes 回傳格式相同，但先看快取，只對「沒快取或過期」的股票
    真的打 API。"""
    result: dict[str, dict] = {}
    missing: list[tuple[str, str]] = []
    for code, market in codes_with_market:
        cached = _get_fresh(code)
        if cached is not None:
            result[code] = cached
        else:
            missing.append((code, market))

    if missing:
        fresh = await fetch_quotes(missing)
        store_many(fresh)
        result.update(fresh)

    return result
