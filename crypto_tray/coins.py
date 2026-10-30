"""可关注的币种。标识只使用固定目录，避免把用户输入拼进请求地址。"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Coin:
    coin_id: str
    symbol: str
    name: str
    binance: str
    badge: tuple[str, str]


def _coin(coin_id: str, symbol: str, name: str, binance: str, bg: str, fg: str) -> Coin:
    return Coin(coin_id, symbol, name, binance, (bg, fg))


CATALOG: dict[str, Coin] = {
    coin.coin_id: coin
    for coin in (
        _coin("bitcoin", "BTC", "比特币", "BTCUSDT", "#3A2E16", "#E2B15A"),
        _coin("ethereum", "ETH", "以太坊", "ETHUSDT", "#1A2744", "#8EB4FF"),
        _coin("solana", "SOL", "Solana", "SOLUSDT", "#2B1B3D", "#C9A0FF"),
        _coin("binancecoin", "BNB", "BNB", "BNBUSDT", "#3A3216", "#F0C14D"),
        _coin("ripple", "XRP", "瑞波币", "XRPUSDT", "#1A2C30", "#7ED0D6"),
        _coin("dogecoin", "DOGE", "狗狗币", "DOGEUSDT", "#3A2A16", "#E0B15A"),
        _coin("tron", "TRX", "波场", "TRXUSDT", "#3A1C1C", "#FF8B8B"),
        _coin("cardano", "ADA", "艾达币", "ADAUSDT", "#1C2438", "#9BB0E8"),
        _coin("avalanche-2", "AVAX", "Avalanche", "AVAXUSDT", "#3A2222", "#FF8A7A"),
        _coin("chainlink", "LINK", "Chainlink", "LINKUSDT", "#1A2A44", "#7EB0FF"),
        _coin("the-open-network", "TON", "TON", "TONUSDT", "#1E2A3A", "#9EC0E8"),
        _coin("sui", "SUI", "Sui", "SUIUSDT", "#1C2E3A", "#7ED6E0"),
        _coin("pepe", "PEPE", "PEPE", "PEPEUSDT", "#163222", "#7DDC9A"),
        _coin("hyperliquid", "HYPE", "Hyperliquid", "HYPEUSDT", "#2A2438", "#C4B5FD"),
        _coin("stellar", "XLM", "恒星币", "XLMUSDT", "#1A2830", "#8FD0E0"),
        _coin("litecoin", "LTC", "莱特币", "LTCUSDT", "#2E3138", "#D5D8DE"),
    )
}

CATALOG_ORDER: list[str] = list(CATALOG)
BY_SYMBOL: dict[str, Coin] = {coin.symbol: coin for coin in CATALOG.values()}
