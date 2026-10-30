"""拉取行情、恐慌贪婪指数和新闻。任何一个来源失败都不会丢掉其余数据。"""

from __future__ import annotations

import json
import logging
import re
import time
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from html import unescape

from crypto_tray.coins import BY_SYMBOL
from crypto_tray.config import Config, data_dir

log = logging.getLogger("crypto_tray.fetch")

UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36 CryptoTray/1.0"
)
CACHE_VERSION = 2
MARKET_COUNT = 6

FNG_ZH = {
    "Extreme Fear": "极度恐惧",
    "Fear": "恐惧",
    "Neutral": "中性",
    "Greed": "贪婪",
    "Extreme Greed": "极度贪婪",
}

_CHINESE = re.compile(r"[\u4e00-\u9fff]")
_NEWS_FEEDS = (
    (
        "https://news.google.com/rss/search?"
        + urllib.parse.urlencode(
            {
                "q": "(比特币 OR 以太坊 OR 加密货币 OR 稳定币) when:2d",
                "hl": "zh-CN",
                "gl": "CN",
                "ceid": "CN:zh-Hans",
            }
        ),
        "快讯",
    ),
)


class FetchError(Exception):
    pass


@dataclass
class Quote:
    coin_id: str
    symbol: str
    name: str
    price: float | None
    change_24h: float | None
    change_1h: float | None
    volume: float | None
    sparkline: list[float]
    currency: str
    pair: str = ""


@dataclass
class Headline:
    title: str
    url: str
    source: str
    published: datetime | None


@dataclass
class Snapshot:
    quotes: list[Quote] = field(default_factory=list)
    headlines: list[Headline] = field(default_factory=list)
    fear_greed: int | None = None
    fear_text: str = ""
    market_cap: float | None = None
    market_change_24h: float | None = None
    currency: str = "cny"
    updated_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    price_source: str = ""
    live: bool = False
    status: str = ""


def http_get(url: str, timeout: float = 15) -> bytes:
    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": UA,
            "Accept": "application/json, application/rss+xml, text/xml, */*",
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return response.read(2_000_000)
    except urllib.error.HTTPError as exc:
        raise FetchError(f"HTTP {exc.code}") from exc
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        reason = getattr(exc, "reason", exc)
        raise FetchError(f"网络错误 {reason}") from exc


def http_json(url: str, timeout: float = 15) -> object:
    raw = http_get(url, timeout=timeout)
    try:
        return json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise FetchError("返回的数据无法解析") from exc


def _num(value: object) -> float | None:
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value)
        except ValueError:
            return None
    return None


def downsample(prices: list[float], count: int = 40) -> list[float]:
    if len(prices) <= count:
        return prices
    step = (len(prices) - 1) / (count - 1)
    return [prices[round(i * step)] for i in range(count)]


def _utc(moment: datetime | None) -> datetime | None:
    if moment is None:
        return None
    if moment.tzinfo is None:
        return moment.replace(tzinfo=timezone.utc)
    return moment.astimezone(timezone.utc)


def _swap_base(inst: str) -> str:
    suffix = "-USDT-SWAP"
    if not inst.endswith(suffix):
        return ""
    base = inst[: -len(suffix)]
    if base.isalnum():
        return base
    return ""


def _quote_volume_usdt(row: dict) -> float | None:
    """OKX 永续的 volCcy24h 是基础币数量，乘最新价得到 USDT 成交额。"""
    last = _num(row.get("last"))
    base_volume = _num(row.get("volCcy24h"))
    if last is None or last <= 0 or base_volume is None or base_volume < 0:
        return None
    return base_volume * last


def _change_24h(row: dict, last: float) -> float | None:
    open_price = _num(row.get("open24h"))
    if open_price is None or open_price <= 0:
        return None
    return (last - open_price) / open_price * 100


def quote_from_swap(row: dict, volume: float, sparkline: list[float] | None = None) -> Quote | None:
    inst = str(row.get("instId") or "")
    base = _swap_base(inst)
    last = _num(row.get("last"))
    if not base or last is None:
        return None
    known = BY_SYMBOL.get(base)
    return Quote(
        coin_id=inst.lower(),
        symbol=base,
        name=known.name if known is not None else base,
        price=last,
        change_24h=_change_24h(row, last),
        change_1h=None,
        volume=volume,
        sparkline=list(sparkline or []),
        currency="usdt",
        pair=inst,
    )


def ranked_swaps(rows: object) -> list[tuple[dict, float]]:
    ranked: list[tuple[dict, float]] = []
    if not isinstance(rows, list):
        return ranked
    for row in rows:
        if not isinstance(row, dict) or not _swap_base(str(row.get("instId") or "")):
            continue
        volume = _quote_volume_usdt(row)
        if volume is None:
            continue
        ranked.append((row, volume))
    ranked.sort(key=lambda item: item[1], reverse=True)
    return ranked


def board_from_rows(rows: object, sparks: dict[str, list[float]] | None = None, limit: int = MARKET_COUNT) -> list[Quote]:
    sparks = sparks or {}
    quotes: list[Quote] = []
    for row, volume in ranked_swaps(rows)[:limit]:
        inst = str(row.get("instId") or "")
        quote = quote_from_swap(row, volume, sparks.get(inst))
        if quote is not None and quote.price is not None:
            quotes.append(quote)
    return quotes


_swap_backoff_until = 0.0
_swap_warned = False


def fetch_swap_rows() -> list[dict]:
    global _swap_backoff_until, _swap_warned
    now = time.monotonic()
    if now < _swap_backoff_until:
        raise FetchError("合约行情冷却中")
    try:
        payload = http_json("https://www.okx.com/api/v5/market/tickers?instType=SWAP", timeout=12)
    except FetchError as exc:
        _swap_backoff_until = time.monotonic() + 30
        if not _swap_warned:
            log.warning("合约行情失败：%s", exc)
            _swap_warned = True
        raise
    rows = payload.get("data") if isinstance(payload, dict) else None
    ranked = ranked_swaps(rows)
    if not ranked:
        _swap_backoff_until = time.monotonic() + 30
        raise FetchError("合约行情结果是空的")
    _swap_warned = False
    return [row for row, _volume in ranked]


def _candle_closes(inst: str) -> list[float]:
    query = urllib.parse.urlencode({"instId": inst, "bar": "4H", "limit": "42"})
    try:
        payload = http_json("https://www.okx.com/api/v5/market/candles?" + query, timeout=8)
    except FetchError:
        return []
    rows = payload.get("data") if isinstance(payload, dict) else None
    if not isinstance(rows, list):
        return []
    closes: list[float] = []
    for row in reversed(rows):
        if isinstance(row, list) and len(row) >= 5:
            price = _num(row[4])
            if price is not None:
                closes.append(price)
    return downsample(closes)


def load_sparklines(quotes: list[Quote]) -> dict[str, list[float]]:
    inst_ids = [item.pair for item in quotes if item.pair]
    if not inst_ids:
        return {}
    found: dict[str, list[float]] = {}
    with ThreadPoolExecutor(max_workers=6) as pool:
        futures = {pool.submit(_candle_closes, inst): inst for inst in inst_ids}
        for future in as_completed(futures):
            found[futures[future]] = future.result()
    return found


def _with_sparklines(quotes: list[Quote]) -> list[Quote]:
    sparks = load_sparklines(quotes)
    for item in quotes:
        item.sparkline = sparks.get(item.pair, [])
    return quotes


def load_quotes(_config: Config) -> tuple[list[Quote], str, str, bool, str]:
    """按 OKX USDT 永续合约 24 小时成交额取前 6。价格是合约最新价。"""
    try:
        quotes = _with_sparklines(board_from_rows(fetch_swap_rows()))
    except FetchError as exc:
        log.warning("合约榜失败：%s", exc)
        return [], "", "usdt", False, "行情暂时不可用"
    if not quotes:
        return [], "", "usdt", False, "行情暂时不可用"
    return quotes, "OKX", "usdt", True, ""


def load_global(currency: str) -> tuple[float | None, float | None]:
    try:
        payload = http_json("https://api.coingecko.com/api/v3/global", timeout=15)
    except FetchError as exc:
        log.warning("总市值失败：%s", exc)
        return None, None
    if not isinstance(payload, dict):
        return None, None
    data = payload.get("data") if isinstance(payload.get("data"), dict) else {}
    caps = data.get("total_market_cap") if isinstance(data.get("total_market_cap"), dict) else {}
    cap = _num(caps.get(currency))
    change = _num(data.get("market_cap_change_percentage_24h_usd"))
    return cap, change


def load_fear_greed() -> tuple[int | None, str]:
    try:
        payload = http_json("https://api.alternative.me/fng/?limit=1", timeout=12)
    except FetchError as exc:
        log.warning("恐慌贪婪指数失败：%s", exc)
        return None, ""
    if not isinstance(payload, dict):
        return None, ""
    rows = payload.get("data")
    if not isinstance(rows, list) or not rows or not isinstance(rows[0], dict):
        return None, ""
    value = _num(rows[0].get("value"))
    if value is None:
        return None, ""
    label = FNG_ZH.get(str(rows[0].get("value_classification") or ""), "")
    return int(round(value)), label


def parse_rss(raw: bytes, default_source: str) -> list[Headline]:
    if raw.startswith(b"\xef\xbb\xbf"):
        raw = raw[3:]
    try:
        root = ET.fromstring(raw)
    except ET.ParseError as exc:
        raise FetchError("新闻源不是有效的 RSS") from exc
    headlines: list[Headline] = []
    for item in root.findall(".//item"):
        title = unescape(item.findtext("title") or "")
        title = re.sub(r"\s+", " ", title).strip()
        url = (item.findtext("link") or "").strip()
        source_el = item.find("source")
        source = default_source
        if source_el is not None and source_el.text:
            source = source_el.text.strip() or default_source
        suffix = f" - {source}"
        if title.endswith(suffix):
            title = title[: -len(suffix)].strip()
        published = None
        pub = item.findtext("pubDate")
        if pub:
            try:
                published = _utc(parsedate_to_datetime(pub))
            except (TypeError, ValueError, IndexError):
                published = None
        parsed = urllib.parse.urlparse(url)
        if title and parsed.scheme in ("http", "https"):
            headlines.append(Headline(title, url, source, published))
    return headlines


def _headline_key(title: str) -> str:
    compact = re.sub(r"\s+", "", title).lower()
    compact = re.sub(r"[^\w\u4e00-\u9fff]+", "", compact)
    return compact[:40]


def fetch_news() -> tuple[list[Headline], bool]:
    url, source = _NEWS_FEEDS[0]
    try:
        found = parse_rss(http_get(url, 20), source)
    except Exception as exc:
        log.warning("新闻源 %s 失败：%s", source, exc)
        return [], False
    seen: set[str] = set()
    unique: list[Headline] = []
    for item in sorted(found, key=lambda row: _utc(row.published) or datetime.min.replace(tzinfo=timezone.utc), reverse=True):
        key = _headline_key(item.title)
        if not key or key in seen or not _CHINESE.search(item.title):
            continue
        seen.add(key)
        unique.append(item)
        if len(unique) >= 30:
            break
    return unique, bool(unique)


def search_market(query: str) -> list[Quote]:
    text = query.strip().casefold()
    if not text:
        return []
    exact: list[Quote] = []
    partial: list[Quote] = []
    for row, volume in ranked_swaps(fetch_swap_rows()):
        inst = str(row.get("instId") or "")
        base = _swap_base(inst)
        known = BY_SYMBOL.get(base)
        fields = [base.casefold()]
        if known is not None:
            fields.extend((known.symbol.casefold(), known.name.casefold(), known.coin_id.casefold()))
        quote = quote_from_swap(row, volume)
        if quote is None:
            continue
        if base.casefold() == text or (known is not None and known.name.casefold() == text):
            exact.append(quote)
        elif any(text in field for field in fields):
            partial.append(quote)
    matched = (exact + partial)[:MARKET_COUNT]
    return _with_sparklines(matched) if matched else []


def _swap_index() -> dict[str, tuple[dict, float]]:
    return {str(row.get("instId") or ""): (row, volume) for row, volume in ranked_swaps(fetch_swap_rows())}


def refresh_board(existing: list[Quote]) -> tuple[list[Quote], bool]:
    """重新取成交额前 6，并沿用已有走势。"""
    try:
        sparks = {item.pair: item.sparkline for item in existing}
        quotes = board_from_rows(fetch_swap_rows(), sparks)
    except FetchError:
        return existing, False
    if not quotes:
        return existing, False
    return quotes, True


def live_prices(quotes: list[Quote]) -> tuple[list[Quote], bool]:
    """用同一批 USDT 永续行情刷新指定合约，不改动名单顺序。"""
    try:
        by_inst = _swap_index()
    except FetchError:
        return quotes, False
    fresh = False
    for item in quotes:
        found = by_inst.get(item.pair)
        if found is None:
            continue
        row, volume = found
        last = _num(row.get("last"))
        if last is None:
            continue
        item.price = last
        item.change_24h = _change_24h(row, last)
        item.volume = volume
        item.currency = "usdt"
        fresh = True
    return quotes, fresh


def fetch_snapshot(config: Config) -> Snapshot:
    with ThreadPoolExecutor(max_workers=4) as pool:
        quotes_future = pool.submit(load_quotes, config)
        global_future = pool.submit(load_global, "usd")
        fear_future = pool.submit(load_fear_greed)
        news_future = pool.submit(fetch_news)
        quotes, source, currency, live, note = quotes_future.result()
        market_cap, market_change = global_future.result()
        fear_value, fear_text = fear_future.result()
        headlines, news_ok = news_future.result()

    status = note
    if not live:
        status = "行情暂时不可用"
    elif not news_ok:
        status = status or "快讯暂时不可用"
    return Snapshot(
        quotes=quotes,
        headlines=headlines,
        fear_greed=fear_value,
        fear_text=fear_text,
        market_cap=market_cap,
        market_change_24h=market_change,
        currency=currency,
        updated_at=datetime.now(timezone.utc),
        price_source=source,
        live=live,
        status=status,
    )


def merge_cached(current: Snapshot, previous: Snapshot | None) -> Snapshot:
    if previous is None:
        return current
    if not current.live and previous.quotes and any(item.price is not None for item in previous.quotes):
        current.quotes = previous.quotes
        current.market_cap = previous.market_cap
        current.market_change_24h = previous.market_change_24h
        current.currency = previous.currency
        current.price_source = previous.price_source
        current.updated_at = previous.updated_at
        current.status = "行情更新失败，显示上次数据"
        if current.fear_greed is None:
            current.fear_greed = previous.fear_greed
            current.fear_text = previous.fear_text
    if not current.headlines and previous.headlines:
        current.headlines = previous.headlines
        if current.live:
            current.status = current.status or "快讯更新失败，显示上次内容"
    if current.fear_greed is None and previous.fear_greed is not None:
        current.fear_greed = previous.fear_greed
        current.fear_text = previous.fear_text
    if (
        current.market_cap is None
        and previous.market_cap is not None
        and current.currency == previous.currency
    ):
        current.market_cap = previous.market_cap
        current.market_change_24h = previous.market_change_24h
    return current


def _moment(value: object) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    return _utc(parsed)


def snapshot_to_dict(snapshot: Snapshot) -> dict:
    payload = asdict(snapshot)
    payload["updated_at"] = snapshot.updated_at.isoformat()
    for item in payload["headlines"]:
        published = item.get("published")
        item["published"] = published.isoformat() if isinstance(published, datetime) else None
    return payload


def _cached_swap(item: object) -> bool:
    if not isinstance(item, dict):
        return False
    coin_id = item.get("coin_id")
    pair = str(item.get("pair") or "")
    symbol = str(item.get("symbol") or "")
    return (
        isinstance(coin_id, str)
        and re.fullmatch(r"[a-z0-9-]{1,48}", coin_id) is not None
        and pair.endswith("-USDT-SWAP")
        and symbol.isalnum()
    )


def snapshot_from_dict(payload: dict) -> Snapshot | None:
    if payload.get("version") != CACHE_VERSION or not isinstance(payload.get("snapshot"), dict):
        return None
    raw = payload["snapshot"]
    try:
        quotes = [
            Quote(
                coin_id=item["coin_id"],
                symbol=item["symbol"],
                name=item["name"],
                price=_num(item.get("price")),
                change_24h=_num(item.get("change_24h")),
                change_1h=_num(item.get("change_1h")),
                volume=_num(item.get("volume")),
                sparkline=[n for n in (_num(v) for v in item.get("sparkline") or []) if n is not None],
                currency="usdt",
                pair=str(item.get("pair") or ""),
            )
            for item in raw.get("quotes") or []
            if _cached_swap(item)
        ]
        headlines = [
            Headline(
                title=str(item.get("title") or ""),
                url=str(item.get("url") or ""),
                source=str(item.get("source") or ""),
                published=_moment(item.get("published")),
            )
            for item in raw.get("headlines") or []
            if isinstance(item, dict) and str(item.get("url") or "").startswith("http")
        ]
    except (KeyError, TypeError):
        return None
    updated = _moment(raw.get("updated_at")) or datetime.now(timezone.utc)
    return Snapshot(
        quotes=quotes,
        headlines=headlines,
        fear_greed=(None if _num(raw.get("fear_greed")) is None else int(round(_num(raw.get("fear_greed")) or 0))),
        fear_text=str(raw.get("fear_text") or ""),
        market_cap=_num(raw.get("market_cap")),
        market_change_24h=_num(raw.get("market_change_24h")),
        currency="usdt",
        updated_at=updated,
        price_source=str(raw.get("price_source") or ""),
        live=False,
        status="显示上次数据",
    )


def cache_path():
    return data_dir() / "cache.json"


def load_cache() -> Snapshot | None:
    path = cache_path()
    if not path.exists():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(payload, dict):
        return None
    return snapshot_from_dict(payload)


def save_cache(snapshot: Snapshot) -> None:
    if not any(item.price is not None for item in snapshot.quotes) and not snapshot.headlines:
        return
    path = cache_path()
    payload = {"version": CACHE_VERSION, "snapshot": snapshot_to_dict(snapshot)}
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    tmp.replace(path)


_SAMPLE_RSS = b"""<?xml version="1.0"?>
<rss><channel><item>
<title>&#x6BD4;&#x7279;&#x5E01;&#x4E0B;&#x8DCC; - Example</title>
<link>https://example.com/a</link>
<pubDate>Fri, 30 Oct 2026 00:00:00 GMT</pubDate>
<source>Example</source>
</item></channel></rss>"""


def run_check() -> int:
    """给打包前使用：确认解析和实时数据都可用。"""
    import sys

    sys.stdout.reconfigure(encoding="utf-8")
    from datetime import timedelta

    from crypto_tray.formatters import format_change, format_compact, format_price, relative_time

    assert format_price(1000, "usd") == "$1,000.00"
    assert format_price(1000, "usdt") == "1,000.00"
    assert format_price(None, "cny") == "--"
    assert format_change(1.2) == "+1.20%"
    assert format_change(-4.489) == "-4.49%"
    assert format_compact(1.32e13, "cny") == "¥13.20万亿"
    assert format_compact(1.33e10, "usdt") == "133亿"
    sample_rows = [
        {"instId": "AAA-USDT-SWAP", "last": "2", "volCcy24h": "10", "open24h": "1"},
        {"instId": "BBB-USDT-SWAP", "last": "3", "volCcy24h": "10", "open24h": "3"},
        {"instId": "BTC-USD-SWAP", "last": "100", "volCcy24h": "999", "open24h": "100"},
    ]
    ranked = board_from_rows(sample_rows)
    assert [item.symbol for item in ranked] == ["BBB", "AAA"]
    assert ranked[0].volume == 30
    assert ranked[0].currency == "usdt"
    assert ranked[0].pair == "BBB-USDT-SWAP"
    assert ranked[1].change_24h == 100
    sample = parse_rss(_SAMPLE_RSS, "Fallback")
    assert len(sample) == 1
    assert sample[0].title == "比特币下跌"
    assert sample[0].source == "Example"
    assert relative_time(datetime.now(timezone.utc)) == "刚刚"
    assert relative_time(datetime.now(timezone.utc) - timedelta(minutes=5)) == "5分钟前"
    print("parser ok")

    config = Config()
    snapshot = fetch_snapshot(config)
    priced = [item for item in snapshot.quotes if item.price is not None]
    print(f"source={snapshot.price_source or '-'} live={snapshot.live} prices={len(priced)} news={len(snapshot.headlines)}")
    print(f"fear={snapshot.fear_greed} {snapshot.fear_text} cap={snapshot.market_cap} status={snapshot.status}")
    volumes = [item.volume or -1 for item in snapshot.quotes]
    if priced and volumes != sorted(volumes, reverse=True):
        print("volume rank is out of order")
        return 1
    if len(priced) != MARKET_COUNT:
        print(f"expected {MARKET_COUNT} contracts")
        return 1
    for item in priced:
        print(
            f"{item.symbol} {format_price(item.price, item.currency)} "
            f"{format_change(item.change_24h)} vol={format_compact(item.volume, item.currency)} "
            f"spark={len(item.sparkline)}"
        )
    for item in snapshot.headlines[:5]:
        print(f"- [{item.source}] {item.title}")
    if not priced or not snapshot.headlines:
        print("check failed")
        return 1
    print("check ok")
    return 0
