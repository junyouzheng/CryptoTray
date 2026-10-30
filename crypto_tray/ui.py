"""贴着托盘的固定弹窗。行情和新闻用导航切换。"""

from __future__ import annotations

import tkinter as tk
import urllib.parse
import webbrowser
from typing import Callable

import customtkinter as ctk

from crypto_tray import __version__
from crypto_tray.coins import BY_SYMBOL, CATALOG
from crypto_tray.fetch import Headline, Quote, Snapshot
from crypto_tray.formatters import format_change, format_compact, format_price, relative_time
from crypto_tray.icons import draw_icon

BG = "#0E1116"
SURFACE = "#171C24"
SURFACE_2 = "#212938"
LINE = "#2C3544"
TEXT = "#F3F6F8"
MUTED = "#93A0B2"
GOLD = "#E2B15A"
UP = "#3DDC97"
DOWN = "#FF6B81"
UP_BG = "#14281E"
DOWN_BG = "#2C151B"
AMBER = "#E2B15A"
_BADGES = (
    ("#3A2E16", "#E2B15A"),
    ("#1A2744", "#8EB4FF"),
    ("#2B1B3D", "#C9A0FF"),
    ("#163222", "#7DDC9A"),
    ("#3A1C1C", "#FF8B8B"),
)


def open_http(url: str) -> None:
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme in ("http", "https"):
        webbrowser.open(url)


def tone(value: float | None) -> str:
    if value is None:
        return MUTED
    if value < 25:
        return DOWN
    if value < 45:
        return "#F0A36B"
    if value < 55:
        return GOLD
    if value < 75:
        return "#8FDC7A"
    return UP


def badge_colors(coin_id: str, symbol: str) -> tuple[str, str]:
    known = CATALOG.get(coin_id) or BY_SYMBOL.get(symbol)
    if known is not None:
        return known.badge
    return _BADGES[sum(ord(char) for char in symbol) % len(_BADGES)]


def _bind_tree(widget: tk.Misc, sequence: str, callback) -> None:
    widget.bind(sequence, callback)
    for child in widget.winfo_children():
        _bind_tree(child, sequence, callback)


def draw_sparkline(canvas: tk.Canvas, prices: list[float]) -> None:
    canvas.delete("all")
    width = int(canvas["width"])
    height = int(canvas["height"])
    if len(prices) < 2:
        return
    low = min(prices)
    high = max(prices)
    color = DOWN if prices[-1] < prices[0] else UP
    points: list[float] = []
    last = len(prices) - 1
    for index, price in enumerate(prices):
        x = 1 + index / last * (width - 2)
        y = height / 2 if high == low else height - 2 - (price - low) / (high - low) * (height - 4)
        points.extend((x, y))
    canvas.create_line(*points, fill=color, width=1.6, smooth=True)


def draw_meter(canvas: tk.Canvas, value: int | None) -> None:
    canvas.delete("all")
    width = int(canvas["width"])
    height = int(canvas["height"])
    canvas.create_rectangle(0, 0, width, height, fill="#2A3340", outline="")
    if value is None:
        return
    clamped = max(0, min(100, value))
    canvas.create_rectangle(0, 0, max(2, width * clamped / 100), height, fill=tone(clamped), outline="")


class CoinRow(ctk.CTkFrame):
    def __init__(self, master, quote: Quote, fonts: dict[str, ctk.CTkFont]):
        super().__init__(master, fg_color=SURFACE, corner_radius=10, border_width=1, border_color=LINE)
        self.grid_columnconfigure(1, weight=1)
        bg, fg = badge_colors(quote.coin_id, quote.symbol)
        badge = ctk.CTkFrame(self, width=42, height=42, corner_radius=10, fg_color=bg)
        badge.grid(row=0, column=0, rowspan=3, padx=(8, 6), pady=10)
        badge.grid_propagate(False)
        ctk.CTkLabel(badge, text=quote.symbol[:4], text_color=fg, font=fonts["badge"]).place(relx=0.5, rely=0.5, anchor="center")

        name_line = ctk.CTkFrame(self, fg_color="transparent")
        name_line.grid(row=0, column=1, sticky="w", padx=(0, 96), pady=(10, 0))
        ctk.CTkLabel(name_line, text=quote.name, text_color=TEXT, font=fonts["name"]).pack(side="left")
        ctk.CTkLabel(name_line, text=quote.symbol, text_color=MUTED, font=fonts["meta"]).pack(side="left", padx=(6, 0))

        self.price = ctk.CTkLabel(self, text="--", text_color=TEXT, font=fonts["price"], anchor="w")
        self.price.grid(row=1, column=1, sticky="w", padx=(0, 96), pady=(2, 0))
        self.sub = ctk.CTkLabel(
            self, text="", text_color=MUTED, font=fonts["meta"], anchor="w", justify="left", wraplength=240
        )
        self.sub.grid(row=2, column=1, sticky="ew", padx=(0, 92), pady=(2, 10))
        self.pill = ctk.CTkLabel(self, text="--", width=84, height=24, corner_radius=8, font=fonts["pill"], text_color=MUTED, fg_color=SURFACE_2)
        self.pill.place(relx=1.0, x=-8, y=10, anchor="ne")
        self.spark = tk.Canvas(self, width=76, height=22, bg=SURFACE, highlightthickness=0, bd=0)
        self.spark.place(relx=1.0, x=-8, y=38, anchor="ne")
        self._price_text = ""
        self._sub_text = ""
        self._pill_text = ""
        self._spark_data: list[float] | None = None
        self.update_quote(quote)

    def update_quote(self, quote: Quote) -> None:
        price_text = format_price(quote.price, quote.currency)
        if price_text != self._price_text:
            self._price_text = price_text
            self.price.configure(text=price_text)
        parts: list[str] = []
        if quote.change_1h is not None:
            parts.append(f"1小时 {quote.change_1h:+.2f}%")
        if quote.volume is not None:
            parts.append(f"24h成交额 {format_compact(quote.volume, quote.currency)}")
        sub_text = "  ·  ".join(parts) if parts else " "
        if sub_text != self._sub_text:
            self._sub_text = sub_text
            self.sub.configure(text=sub_text)
        if quote.change_24h is None:
            pill_text = "--"
            pill_color = MUTED
            pill_bg = SURFACE_2
        else:
            rising = quote.change_24h >= 0
            pill_text = f"{quote.change_24h:+.2f}%"
            pill_color = UP if rising else DOWN
            pill_bg = UP_BG if rising else DOWN_BG
        if pill_text != self._pill_text:
            self._pill_text = pill_text
            self.pill.configure(text=pill_text, text_color=pill_color, fg_color=pill_bg)
        if quote.sparkline is not self._spark_data:
            self._spark_data = quote.sparkline
            draw_sparkline(self.spark, quote.sparkline)


class NewsRow(ctk.CTkFrame):
    def __init__(self, master, item: Headline, wrap: int, fonts: dict[str, ctk.CTkFont]):
        super().__init__(master, fg_color="transparent", corner_radius=8)
        self.url = item.url
        self.title_label = ctk.CTkLabel(
            self, text=item.title, text_color=TEXT, font=fonts["news"], anchor="w", justify="left", wraplength=wrap
        )
        self.title_label.pack(fill="x", padx=8, pady=(7, 0))
        self.meta = ctk.CTkLabel(self, text="", text_color=MUTED, font=fonts["meta"], anchor="w")
        self.meta.pack(fill="x", padx=8, pady=(0, 7))
        self.update_item(item)
        _bind_tree(self, "<Button-1>", lambda _event: open_http(self.url))
        _bind_tree(self, "<Enter>", self._on_enter)
        _bind_tree(self, "<Leave>", self._on_leave)

    def update_item(self, item: Headline) -> None:
        self.url = item.url
        self.title_label.configure(text=item.title)
        stamp = relative_time(item.published)
        self.meta.configure(text=f"{item.source}  ·  {stamp}" if stamp else item.source)

    def set_wrap(self, wrap: int) -> None:
        self.title_label.configure(wraplength=wrap)

    def _on_enter(self, event) -> None:
        self.configure(fg_color=SURFACE_2)
        try:
            event.widget.configure(cursor="hand2")
        except tk.TclError:
            pass

    def _contains(self, widget: tk.Misc | None) -> bool:
        while widget is not None:
            if widget is self:
                return True
            widget = getattr(widget, "master", None)
        return False

    def _on_leave(self, _event) -> None:
        hovered = self.winfo_containing(*self.winfo_pointerxy())
        if not self._contains(hovered):
            self.configure(fg_color="transparent")


class Dashboard:
    def __init__(self, root: ctk.CTk, on_search: Callable[[str], None], on_news_refresh: Callable[[], None]):
        self.root = root
        self.on_search = on_search
        self.on_news_refresh = on_news_refresh
        self.snapshot: Snapshot | None = None
        self.rows: dict[str, CoinRow] = {}
        self.row_ids: list[str] | None = None
        self.news_rows: list[NewsRow] = []
        self.news_keys: list[str] | None = None
        self.wrap = 320
        self._search_after: str | None = None

        ui_family = _pick_font(("Microsoft YaHei UI", "Microsoft YaHei", "微软雅黑", "Segoe UI"))
        mono_family = _pick_font(("Cascadia Mono", "Consolas", "Courier New"))
        self.fonts = {
            "title": ctk.CTkFont(family=ui_family, size=20, weight="bold"),
            "name": ctk.CTkFont(family=ui_family, size=14, weight="bold"),
            "news": ctk.CTkFont(family=ui_family, size=13),
            "meta": ctk.CTkFont(family=ui_family, size=11),
            "body": ctk.CTkFont(family=ui_family, size=13),
            "badge": ctk.CTkFont(family=mono_family, size=11, weight="bold"),
            "price": ctk.CTkFont(family=mono_family, size=16),
            "pill": ctk.CTkFont(family=mono_family, size=12),
            "button": ctk.CTkFont(family=ui_family, size=12),
        }

        root.title("币讯")
        root.configure(fg_color=BG)
        self.host = ctk.CTkFrame(root, fg_color=BG, corner_radius=0, border_width=1, border_color=LINE)
        self.host.pack(fill="both", expand=True)
        self.host.grid_columnconfigure(0, weight=1)
        self.host.grid_rowconfigure(3, weight=1)
        self._build_header()
        self._build_summary()
        self._build_nav()
        self._build_pages()
        self.set_logo()
        root.bind("<Escape>", lambda _event: root.request_hide() if hasattr(root, "request_hide") else None)
        root.bind("<Configure>", self._on_resize, add="+")

    def _build_header(self) -> None:
        header = ctk.CTkFrame(self.host, fg_color=BG, corner_radius=0)
        header.grid(row=0, column=0, sticky="ew", padx=14, pady=(12, 2))
        self.logo = ctk.CTkLabel(header, text="")
        self.logo.pack(side="left", padx=(0, 8))
        titles = ctk.CTkFrame(header, fg_color="transparent")
        titles.pack(side="left")
        ctk.CTkLabel(titles, text="币讯", text_color=TEXT, font=self.fonts["title"]).pack(anchor="w")
        line = ctk.CTkFrame(titles, fg_color="transparent")
        line.pack(anchor="w")
        self.dot = tk.Canvas(line, width=12, height=12, bg=BG, highlightthickness=0, bd=0)
        self.dot.pack(side="left", padx=(0, 4))
        self.state_label = ctk.CTkLabel(line, text="正在连接", text_color=MUTED, font=self.fonts["meta"])
        self.state_label.pack(side="left")
        ctk.CTkLabel(header, text=f"v{__version__}", text_color=MUTED, font=self.fonts["meta"]).pack(side="right")
        self._paint_dot(GOLD)

    def _build_summary(self) -> None:
        card = ctk.CTkFrame(self.host, fg_color=SURFACE, corner_radius=12, border_width=1, border_color=LINE)
        card.grid(row=1, column=0, sticky="ew", padx=14, pady=(6, 4))
        top = ctk.CTkFrame(card, fg_color="transparent")
        top.pack(fill="x", padx=12, pady=(8, 0))
        self.fear_label = ctk.CTkLabel(top, text="恐慌贪婪  --", text_color=TEXT, font=self.fonts["body"])
        self.fear_label.pack(side="left")
        self.meter = tk.Canvas(top, width=110, height=8, bg=SURFACE, highlightthickness=0, bd=0)
        self.meter.pack(side="right", pady=6)
        draw_meter(self.meter, None)
        bottom = ctk.CTkFrame(card, fg_color="transparent")
        bottom.pack(fill="x", padx=12, pady=(2, 8))
        self.cap_label = ctk.CTkLabel(bottom, text="总市值 --", text_color=MUTED, font=self.fonts["meta"])
        self.cap_label.pack(side="left")
        self.cap_change = ctk.CTkLabel(bottom, text="", text_color=MUTED, font=self.fonts["meta"])
        self.cap_change.pack(side="left", padx=(8, 0))

    def _build_nav(self) -> None:
        self.nav = ctk.CTkSegmentedButton(
            self.host,
            values=["行情", "新闻"],
            command=self._switch,
            font=self.fonts["body"],
            height=32,
            selected_color="#3A2E16",
            selected_hover_color="#4A3B1C",
            unselected_color=SURFACE,
            unselected_hover_color=SURFACE_2,
            text_color=TEXT,
            fg_color=SURFACE,
        )
        self.nav.grid(row=2, column=0, sticky="ew", padx=14, pady=(6, 4))
        self.nav.set("行情")

    def _build_pages(self) -> None:
        self.market_page = ctk.CTkFrame(self.host, fg_color=BG, corner_radius=0)
        self.news_page = ctk.CTkFrame(self.host, fg_color=BG, corner_radius=0)
        for page in (self.market_page, self.news_page):
            page.grid(row=3, column=0, sticky="nsew", padx=6, pady=(0, 8))
            page.grid_columnconfigure(0, weight=1)
            page.grid_rowconfigure(1, weight=1)
        self.news_page.grid_remove()

        self.search = ctk.CTkEntry(
            self.market_page,
            placeholder_text="搜索合约，例如 BTC、SOL",
            height=34,
            fg_color=SURFACE,
            border_color=LINE,
            text_color=TEXT,
            placeholder_text_color=MUTED,
            font=self.fonts["body"],
        )
        self.search.grid(row=0, column=0, sticky="ew", padx=8, pady=(4, 4))
        self.search.bind("<KeyRelease>", self._search_changed)
        self.search.bind("<<Paste>>", self._search_changed)
        self.market = self._scroller(self.market_page)
        self.market.grid(row=1, column=0, sticky="nsew")
        self.market._parent_canvas.bind("<Configure>", lambda _event: self._fit_rows(), add="+")
        self._show_placeholder(self.market, "正在获取行情…")

        bar = ctk.CTkFrame(self.news_page, fg_color="transparent")
        bar.grid(row=0, column=0, sticky="ew", padx=8, pady=(4, 2))
        self.news_state = ctk.CTkLabel(bar, text="中文快讯", text_color=MUTED, font=self.fonts["meta"])
        self.news_state.pack(side="left")
        self.news_button = ctk.CTkButton(
            bar,
            text="刷新",
            width=64,
            height=28,
            corner_radius=8,
            fg_color=SURFACE,
            hover_color=SURFACE_2,
            text_color=TEXT,
            border_width=1,
            border_color=LINE,
            font=self.fonts["button"],
            command=self.on_news_refresh,
        )
        self.news_button.pack(side="right")
        self.news = self._scroller(self.news_page)
        self.news.grid(row=1, column=0, sticky="nsew")
        self._show_placeholder(self.news, "正在获取快讯…")

    def _scroller(self, parent) -> ctk.CTkScrollableFrame:
        return ctk.CTkScrollableFrame(
            parent,
            fg_color="transparent",
            corner_radius=0,
            scrollbar_button_color=LINE,
            scrollbar_button_hover_color=MUTED,
        )

    def _show_placeholder(self, parent, text: str) -> None:
        ctk.CTkLabel(parent, text=text, text_color=MUTED, font=self.fonts["body"]).pack(anchor="w", padx=10, pady=16)

    def _clear(self, parent) -> None:
        for child in parent.winfo_children():
            child.destroy()

    def _switch(self, value: str) -> None:
        if value == "新闻":
            self.market_page.grid_remove()
            self.news_page.grid()
        else:
            self.news_page.grid_remove()
            self.market_page.grid()

    def _search_changed(self, _event=None) -> None:
        if self._search_after is not None:
            self.root.after_cancel(self._search_after)
        self._search_after = self.root.after(350, self._emit_search)

    def _emit_search(self) -> None:
        self._search_after = None
        self.on_search(self.search.get().strip())

    def set_logo(self) -> None:
        image = draw_icon(64)
        self._logo_ref = ctk.CTkImage(light_image=image, dark_image=image, size=(28, 28))
        self.logo.configure(image=self._logo_ref, text="")

    def set_status(self, text: str, color: str = AMBER) -> None:
        if self.state_label.cget("text") == text:
            return
        self.state_label.configure(text=text, text_color=color)
        self._paint_dot(color if color != MUTED else GOLD)

    def set_news_busy(self, busy: bool) -> None:
        self.news_button.configure(state="disabled" if busy else "normal")
        if busy:
            self.news_state.configure(text="正在刷新快讯…")

    def set_snapshot(self, snapshot: Snapshot) -> None:
        self.snapshot = snapshot
        self._paint_summary(snapshot)
        self.set_quotes(snapshot.quotes)
        self.set_news(snapshot.headlines, snapshot.updated_at)
        if snapshot.live:
            self.set_status("合约行情实时更新", UP)
        elif snapshot.status:
            self.set_status(snapshot.status, AMBER)

    def _paint_summary(self, snapshot: Snapshot) -> None:
        if snapshot.fear_greed is None:
            self.fear_label.configure(text="恐慌贪婪  --", text_color=TEXT)
        else:
            self.fear_label.configure(
                text=f"恐慌贪婪  {snapshot.fear_greed}  {snapshot.fear_text}",
                text_color=tone(snapshot.fear_greed),
            )
        draw_meter(self.meter, snapshot.fear_greed)
        self.cap_label.configure(text=f"总市值 {format_compact(snapshot.market_cap, snapshot.currency or 'usdt')}")
        if snapshot.market_change_24h is None:
            self.cap_change.configure(text="")
        else:
            rising = snapshot.market_change_24h >= 0
            self.cap_change.configure(
                text=f"24h {format_change(snapshot.market_change_24h)}",
                text_color=UP if rising else DOWN,
            )

    def set_quotes(self, quotes: list[Quote], empty_text: str = "没有匹配的币种", scroll: bool = True) -> None:
        ids = [item.coin_id for item in quotes]
        if ids == self.row_ids and self.rows:
            self.update_prices(quotes)
            return
        self._clear(self.market)
        self.rows = {}
        self.row_ids = ids
        if not quotes:
            self._show_placeholder(self.market, empty_text)
            return
        for quote in quotes:
            row = CoinRow(self.market, quote, self.fonts)
            row.pack(fill="x", padx=6, pady=4)
            self.rows[quote.coin_id] = row
        self._fit_rows()
        self.root.after(200, self._fit_rows)
        if scroll:
            self._scroll_top(self.market)

    def _fit_rows(self) -> None:
        width = self.market._parent_canvas.winfo_width()
        if width < 120 or width == getattr(self, "_row_width", None):
            return
        self._row_width = width
        inner = width - 8
        # 右侧留给涨跌幅和走势，成交额留在左边一行里。
        sub_wrap = max(140, inner - 160)
        for row in self.rows.values():
            row.sub.configure(wraplength=sub_wrap)
            row.update_idletasks()
            height = max(108, row.winfo_reqheight())
            row.grid_propagate(False)
            tk.Frame.configure(row, width=inner, height=height)

    def update_prices(self, quotes: list[Quote]) -> None:
        if [item.coin_id for item in quotes] != self.row_ids:
            return
        for quote in quotes:
            row = self.rows.get(quote.coin_id)
            if row is not None:
                row.update_quote(quote)

    def set_news(self, headlines: list[Headline], updated_at=None) -> None:
        keys = [item.url for item in headlines]
        if keys == self.news_keys:
            for row, item in zip(self.news_rows, headlines):
                row.update_item(item)
        else:
            self._clear(self.news)
            self.news_rows = []
            self.news_keys = keys
            if not headlines:
                self._show_placeholder(self.news, "暂时没有中文快讯")
            else:
                for item in headlines:
                    row = NewsRow(self.news, item, self.wrap, self.fonts)
                    row.pack(fill="x", padx=4, pady=1)
                    self.news_rows.append(row)
                self._scroll_top(self.news)
        if updated_at is not None:
            local = updated_at.astimezone()
            self.news_state.configure(text=f"中文快讯 · {local:%H:%M} 更新")
        self.news_button.configure(state="normal")

    def _paint_dot(self, color: str) -> None:
        self.dot.delete("all")
        self.dot.create_oval(2, 2, 10, 10, fill=color, outline="")

    def _scroll_top(self, frame: ctk.CTkScrollableFrame) -> None:
        frame.update_idletasks()
        frame._parent_canvas.yview_moveto(0)

    def _on_resize(self, event) -> None:
        if event.widget is not self.root or event.width < 200:
            return
        scale = self.root._get_window_scaling() or 1
        wrap = max(180, int(event.width / scale) - 64)
        self._row_width = None
        self._fit_rows()
        if wrap == self.wrap:
            return
        self.wrap = wrap
        for row in self.news_rows:
            row.set_wrap(wrap)

    def present(self) -> None:
        self.root.deiconify()
        self.root.lift()
        self.root.attributes("-topmost", True)
        self.root.focus_force()


class AppRoot(ctk.CTk):
    def __init__(self):
        super().__init__()
        self._hide: Callable[[], None] | None = None
        self.protocol("WM_DELETE_WINDOW", self.request_hide)

    def _on_closing(self):
        self.request_hide()

    def request_hide(self):
        if self._hide is not None:
            self._hide()
        else:
            self.destroy()


def _pick_font(candidates: tuple[str, ...]) -> str:
    import tkinter.font as tkfont

    families = set(tkfont.families())
    for name in candidates:
        if name in families:
            return name
    return candidates[-1]
