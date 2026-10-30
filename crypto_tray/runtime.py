"""托盘弹窗、实时行情和快讯刷新。"""

from __future__ import annotations

import ctypes
import logging
import os
import socket
import sys
import threading
import time
from datetime import datetime

import customtkinter as ctk

from crypto_tray.config import autostart_enabled, data_dir, load_config, set_autostart, setup_logging
from crypto_tray.fetch import (
    Snapshot,
    fetch_news,
    fetch_snapshot,
    live_prices,
    load_cache,
    load_fear_greed,
    load_global,
    merge_cached,
    save_cache,
    search_market,
)
from crypto_tray.formatters import format_price
from crypto_tray.icons import draw_icon, save_ico
from crypto_tray.ui import AppRoot, Dashboard, UP

log = logging.getLogger("crypto_tray.runtime")

HOST = "127.0.0.1"
PORT = 47631
PRICE_MS = 2000
OVERVIEW_MS = 60 * 1000
POPUP_W = 400
POPUP_H = 640


class RECT(ctypes.Structure):
    _fields_ = [
        ("left", ctypes.c_long),
        ("top", ctypes.c_long),
        ("right", ctypes.c_long),
        ("bottom", ctypes.c_long),
    ]


def work_area() -> RECT:
    rect = RECT()
    if not ctypes.windll.user32.SystemParametersInfoW(0x0030, 0, ctypes.byref(rect), 0):
        rect.left, rect.top, rect.right, rect.bottom = 0, 0, 1280, 720
    return rect


def claim_instance() -> socket.socket | str:
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    try:
        sock.bind((HOST, PORT))
    except OSError:
        sock.close()
        try:
            with socket.create_connection((HOST, PORT), 1) as client:
                client.sendall(b"SHOW")
            return "existing"
        except OSError:
            return "unavailable"
    sock.listen(4)
    return sock


def _listen(sock: socket.socket, root: AppRoot, present) -> None:
    while True:
        try:
            conn, _addr = sock.accept()
        except OSError:
            return
        try:
            data = conn.recv(32)
        finally:
            conn.close()
        if data.startswith(b"SHOW"):
            root.after(0, present)


def place_popup(root: AppRoot) -> None:
    """把固定弹窗放在工作区右下角，贴着系统托盘，避开任务栏。"""
    area = work_area()
    scale = root._get_window_scaling() or 1
    avail_w = max(1, area.right - area.left - 8)
    avail_h = max(1, area.bottom - area.top - 8)
    width = min(POPUP_W, max(320, int(avail_w / scale)))
    height = min(POPUP_H, max(420, int(avail_h / scale)))
    physical_w = int(width * scale)
    physical_h = int(height * scale)
    x = max(area.left, area.right - physical_w - 4)
    y = max(area.top, area.bottom - physical_h - 4)
    root.geometry(f"{int(width)}x{int(height)}+{int(x)}+{int(y)}")


class TrayApp:
    def __init__(self, root: AppRoot):
        self.root = root
        self.config = load_config()
        self.dashboard = Dashboard(root, self.on_search, self.refresh_news)
        self.previous = load_cache()
        self.shown: list = []
        self.base_quotes: list = []
        self.search_text = ""
        self._view = 0
        self._search_gen = 0
        self.icon = None
        self.tray_ok = False
        self._lock = threading.Lock()
        self._price_busy = False
        self._price_after: str | None = None
        self._overview_after: str | None = None
        self._closing = False
        self._ignore_focus_until = 0.0
        root._hide = self.hide
        self._apply_window_icon()
        if self.previous is not None:
            self.base_quotes = list(self.previous.quotes)
            self.shown = list(self.previous.quotes)
            self.dashboard.set_snapshot(self.previous)
        root.bind("<FocusOut>", self._on_focus_out, add="+")
        self._start_tray()

    def _apply_window_icon(self) -> None:
        bundled = os.path.join(getattr(sys, "_MEIPASS", os.path.dirname(os.path.dirname(__file__))), "assets", "icon.ico")
        if os.path.exists(bundled):
            path = bundled
        else:
            path = str(data_dir() / "icon.ico")
            save_ico(path)
        try:
            self.root.iconbitmap(path)
        except Exception:
            log.exception("设置窗口图标失败")

    def _start_tray(self) -> None:
        try:
            import pystray
        except Exception:
            log.exception("无法加载托盘组件")
            self.dashboard.set_status("托盘不可用")
            return
        menu = pystray.Menu(
            pystray.MenuItem("打开", self._tray_open, default=True, visible=False),
            pystray.MenuItem("开机自启", self._tray_autostart, checked=lambda _item: autostart_enabled()),
            pystray.MenuItem("退出", self._tray_quit),
        )
        self.icon = pystray.Icon("CryptoTray", draw_icon(64), "币讯", menu)
        try:
            self.icon.run_detached(setup=self._tray_ready)
            self.tray_ok = True
        except Exception:
            log.exception("托盘图标启动失败")
            self.icon = None
            self.dashboard.set_status("托盘不可用")

    def _tray_ready(self, icon) -> None:
        icon.visible = True
        self.root.after(0, lambda: self._update_tray(self.shown))

    def _tray_open(self, _icon, _item) -> None:
        self.root.after(0, self.toggle)

    def _tray_autostart(self, icon, _item) -> None:
        enabled = not autostart_enabled()
        try:
            set_autostart(enabled)
        except OSError:
            log.exception("设置开机自启失败")
            return
        self.config.autostart = enabled
        try:
            self.config.save()
        except OSError:
            log.exception("保存开机自启失败")
        try:
            icon.update_menu()
        except Exception:
            log.exception("刷新托盘菜单失败")

    def _tray_quit(self, _icon, _item) -> None:
        self.root.after(0, self.shutdown)

    def toggle(self) -> None:
        if str(self.root.state()) == "withdrawn":
            self.present()
        else:
            self.hide()

    def present(self) -> None:
        place_popup(self.root)
        self._ignore_focus_until = time.time() + 0.35
        self.dashboard.present()

    def _on_focus_out(self, event) -> None:
        if event.widget is not self.root:
            return
        self.root.after(140, self._hide_if_inactive)

    def _hide_if_inactive(self) -> None:
        if self._closing or time.time() < self._ignore_focus_until:
            return
        if self.root.focus_get() is not None:
            return
        self.hide()

    def on_search(self, text: str) -> None:
        self.search_text = text
        self._search_gen += 1
        generation = self._search_gen
        if not text:
            self._show_quotes(self.base_quotes, generation)
            return
        self.dashboard.set_status("正在搜索…")

        def work() -> None:
            try:
                quotes = search_market(text)
                error = ""
            except Exception as exc:
                log.warning("搜索失败：%s", exc)
                quotes = []
                error = "搜索失败"
            self.root.after(0, lambda: self._show_quotes(quotes, generation, error or "没有匹配的币种"))

        threading.Thread(target=work, daemon=True).start()

    def _show_quotes(self, quotes, generation: int, empty_text: str = "没有匹配的币种", status: str = "行情实时更新") -> None:
        if generation != self._search_gen or self._closing:
            return
        self._view += 1
        self.shown = list(quotes)
        self.dashboard.set_quotes(self.shown, empty_text)
        if self.shown:
            self.dashboard.set_status(status, UP)
        self._update_tray(self.shown)

    def refresh_news(self) -> None:
        if self._closing:
            return
        self.dashboard.set_news_busy(True)

        def work() -> None:
            try:
                headlines, ok = fetch_news()
            except Exception:
                log.exception("快讯刷新失败")
                headlines, ok = [], False
            self.root.after(0, lambda: self._apply_news(headlines, ok))

        threading.Thread(target=work, daemon=True).start()

    def _apply_news(self, headlines, ok: bool) -> None:
        if self._closing:
            return
        if not headlines and self.previous is not None and self.previous.headlines:
            headlines = self.previous.headlines
            ok = False
        now = datetime.now().astimezone()
        self.dashboard.set_news(headlines, now if ok or headlines else None)
        if not ok and not headlines:
            self.dashboard.news_state.configure(text="快讯暂时不可用")
        if self.previous is None:
            self.previous = Snapshot(headlines=headlines, currency="usd", updated_at=datetime.now().astimezone())
        else:
            self.previous.headlines = headlines

    def refresh_overview(self) -> None:
        if self._closing:
            return

        def work() -> None:
            cap, change = load_global("usd")
            fear, fear_text = load_fear_greed()
            self.root.after(0, lambda: self._apply_overview(cap, change, fear, fear_text))

        threading.Thread(target=work, daemon=True).start()

    def _apply_overview(self, cap, change, fear, fear_text) -> None:
        if self._closing or self.previous is None:
            return
        if cap is not None:
            self.previous.market_cap = cap
            self.previous.market_change_24h = change
        if fear is not None:
            self.previous.fear_greed = fear
            self.previous.fear_text = fear_text
        self.dashboard._paint_summary(self.previous)

    def initial_load(self) -> None:
        if self._closing or not self._lock.acquire(blocking=False):
            return
        self.dashboard.set_status("正在获取行情…")

        def work() -> None:
            try:
                snapshot = fetch_snapshot(self.config)
            except Exception:
                log.exception("首次加载失败")
                snapshot = Snapshot(status="行情暂时不可用", currency="usd")
            finally:
                self._lock.release()
            self.root.after(0, lambda snap=snapshot: self._apply_initial(snap))

        threading.Thread(target=work, daemon=True).start()

    def _apply_initial(self, snapshot: Snapshot) -> None:
        if self._closing:
            return
        merged = merge_cached(snapshot, self.previous)
        self.previous = merged
        self.base_quotes = list(merged.quotes)
        if not self.search_text:
            self._view += 1
            self.shown = list(merged.quotes)
            self.dashboard.set_snapshot(merged)
            self._update_tray(self.shown)
        else:
            self.dashboard._paint_summary(merged)
            self.dashboard.set_news(merged.headlines, merged.updated_at)
        try:
            save_cache(merged)
        except OSError:
            log.exception("写入缓存失败")
        self._arm_prices()
        self._arm_overview()

    def _tick_prices(self) -> None:
        self._price_after = None
        if self._closing:
            return
        if self._price_busy:
            self._arm_prices()
            return
        self._price_busy = True
        view = self._view
        current = self.shown

        def work() -> None:
            try:
                fresh = live_prices(current)[1]
            except Exception:
                log.exception("实时行情失败")
                fresh = False
            self.root.after(0, lambda: self._apply_live(current, view, fresh))

        threading.Thread(target=work, daemon=True).start()
        self._arm_prices()

    def _apply_live(self, quotes, view: int, fresh: bool) -> None:
        self._price_busy = False
        if self._closing or view != self._view or not fresh:
            return
        self.shown = quotes
        if not self.search_text:
            self.base_quotes = quotes
        self.dashboard.update_prices(quotes)
        self.dashboard.set_status("行情实时更新", UP)
        self._update_tray(quotes)
        if self.previous is not None:
            self.previous.quotes = self.base_quotes

    def _arm_prices(self) -> None:
        if self._price_after is not None:
            self.root.after_cancel(self._price_after)
        self._price_after = self.root.after(PRICE_MS, self._tick_prices)

    def _arm_overview(self) -> None:
        if self._overview_after is not None:
            self.root.after_cancel(self._overview_after)
        self._overview_after = self.root.after(OVERVIEW_MS, self._overview_tick)

    def _overview_tick(self) -> None:
        self._overview_after = None
        self.refresh_overview()
        self._arm_overview()

    def _update_tray(self, quotes) -> None:
        if self.icon is None:
            return
        parts: list[str] = []
        for quote in quotes[:3]:
            if quote.price is None:
                continue
            change = "" if quote.change_24h is None else f" {quote.change_24h:+.1f}%"
            parts.append(f"{quote.symbol} {format_price(quote.price, 'usd')}{change}")
        title = (" · ".join(parts) or "币讯")[:127]
        if title != self.icon.title:
            self.icon.title = title

    def hide(self) -> None:
        if not self.tray_ok:
            self.shutdown()
            return
        self.root.withdraw()

    def shutdown(self) -> None:
        if self._closing:
            return
        self._closing = True
        for handle in (self._price_after, self._overview_after):
            if handle is not None:
                try:
                    self.root.after_cancel(handle)
                except Exception:
                    pass
        if self.icon is not None:
            try:
                self.icon.stop()
            except Exception:
                log.exception("停止托盘图标失败")
        self.root.destroy()


def _install_excepthook(log_path) -> None:
    def hook(exc_type, value, traceback) -> None:
        if issubclass(exc_type, KeyboardInterrupt):
            sys.__excepthook__(exc_type, value, traceback)
            return
        logging.getLogger("crypto_tray").error("未处理异常", exc_info=(exc_type, value, traceback))
        ctypes.windll.user32.MessageBoxW(None, f"币讯发生错误：{value}\n\n日志：{log_path}", "币讯", 0x10)

    sys.excepthook = hook


def run() -> None:
    log_path = setup_logging()
    _install_excepthook(log_path)
    log.info("启动币讯")
    claimed = claim_instance()
    if claimed == "existing":
        ctypes.windll.user32.MessageBoxW(None, "币讯已在运行。请点击任务栏右下角的托盘图标。", "币讯", 0x40)
        return
    ctk.CTk._deactivate_windows_window_header_manipulation = True
    ctk.set_appearance_mode("dark")
    ctk.set_default_color_theme("dark-blue")
    root = AppRoot()
    root.resizable(False, False)
    app = TrayApp(root)
    root.overrideredirect(True)
    root.attributes("-topmost", True)
    place_popup(root)
    if isinstance(claimed, socket.socket):
        threading.Thread(target=_listen, args=(claimed, root, app.present), daemon=True).start()
    root.after(200, app.initial_load)
    try:
        root.mainloop()
    finally:
        log.info("币讯已退出")
        if isinstance(claimed, socket.socket):
            claimed.close()
