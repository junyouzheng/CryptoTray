"""把价格、涨跌和市值格式化成界面上的中文文本。"""

from __future__ import annotations

from datetime import datetime, timezone


def _unit(currency: str) -> tuple[str, str]:
    if currency == "cny":
        return "¥", ""
    if currency == "usdt":
        return "", ""
    return "$", ""


def format_price(value: float | None, currency: str) -> str:
    if value is None:
        return "--"
    prefix, suffix = _unit(currency)
    magnitude = abs(value)
    if magnitude >= 1:
        body = f"{value:,.2f}"
    elif magnitude >= 0.01:
        body = f"{value:,.4f}"
    elif magnitude >= 0.0001:
        body = f"{value:,.6f}"
    else:
        body = f"{value:.8f}"
    return prefix + body + suffix


def format_change(value: float | None) -> str:
    if value is None:
        return "--"
    return f"{value:+.2f}%"


def format_compact(value: float | None, currency: str) -> str:
    if value is None:
        return "--"
    prefix, suffix = _unit(currency)
    magnitude = abs(value)
    if magnitude >= 1e12:
        body = f"{value / 1e12:.2f}万亿"
    elif magnitude >= 1e10:
        body = f"{value / 1e8:,.0f}亿"
    elif magnitude >= 1e8:
        body = f"{value / 1e8:.2f}亿"
    elif magnitude >= 1e4:
        body = f"{value / 1e4:.2f}万"
    else:
        body = f"{value:,.0f}"
    return prefix + body + suffix


def relative_time(moment: datetime | None, now: datetime | None = None) -> str:
    if moment is None:
        return ""
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    current = now or datetime.now(timezone.utc)
    if current.tzinfo is None:
        current = current.replace(tzinfo=timezone.utc)
    seconds = int((current - moment.astimezone(timezone.utc)).total_seconds())
    if seconds < 60:
        return "刚刚"
    if seconds < 3600:
        return f"{seconds // 60}分钟前"
    if seconds < 86400:
        return f"{seconds // 3600}小时前"
    local = moment.astimezone()
    return f"{local.month}月{local.day}日"
