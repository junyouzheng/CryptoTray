"""配置、自启动和本机数据目录。"""

from __future__ import annotations

import json
import logging
import os
import sys
import threading
import winreg
from dataclasses import dataclass, field
from pathlib import Path

from crypto_tray.coins import CATALOG

log = logging.getLogger("crypto_tray.config")

APP_NAME = "CryptoTray"
RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
DEFAULT_COINS = [
    "bitcoin",
    "ethereum",
    "solana",
    "binancecoin",
    "ripple",
    "dogecoin",
]
MAX_COINS = 8


def data_dir() -> Path:
    root = os.environ.get("APPDATA")
    base = Path(root) if root else Path.home()
    path = base / "CryptoTray"
    path.mkdir(parents=True, exist_ok=True)
    return path


def setup_logging() -> Path:
    path = data_dir() / "app.log"
    if path.exists() and path.stat().st_size > 512_000:
        path.write_text("", encoding="utf-8")
    logging.basicConfig(
        filename=path,
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
        encoding="utf-8",
        force=True,
    )
    return path


def launch_command() -> str:
    if getattr(sys, "frozen", False):
        return f'"{sys.executable}"'
    python = Path(sys.executable)
    pythonw = python.with_name("pythonw.exe")
    exe = pythonw if pythonw.exists() else python
    launch = Path(__file__).resolve().parent.parent / "launch.py"
    return f'"{exe}" "{launch}"'


def set_autostart(enabled: bool) -> None:
    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_SET_VALUE) as key:
        if enabled:
            winreg.SetValueEx(key, APP_NAME, 0, winreg.REG_SZ, launch_command())
        else:
            try:
                winreg.DeleteValue(key, APP_NAME)
            except FileNotFoundError:
                pass


def autostart_enabled() -> bool:
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_QUERY_VALUE) as key:
            winreg.QueryValueEx(key, APP_NAME)
            return True
    except FileNotFoundError:
        return False


@dataclass
class Config:
    currency: str = "usdt"
    autostart: bool = True
    coins: list[str] = field(default_factory=lambda: list(DEFAULT_COINS))
    path: Path = field(default_factory=lambda: data_dir() / "config.json")
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    def save(self) -> None:
        payload = {
            "autostart": self.autostart,
            "coins": self.coins,
        }
        text = json.dumps(payload, ensure_ascii=False, indent=2)
        with self._lock:
            tmp = self.path.with_suffix(".json.tmp")
            tmp.write_text(text, encoding="utf-8")
            tmp.replace(self.path)


def load_config() -> Config:
    path = data_dir() / "config.json"
    raw: dict = {}
    if path.exists():
        try:
            loaded = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(loaded, dict):
                raw = loaded
        except (OSError, json.JSONDecodeError):
            log.exception("读取配置失败，改用默认值")

    coins_raw = raw.get("coins")
    coins: list[str] = []
    if isinstance(coins_raw, list):
        for item in coins_raw:
            if isinstance(item, str) and item in CATALOG and item not in coins:
                coins.append(item)
    if not coins:
        coins = list(DEFAULT_COINS)
    coins = coins[:MAX_COINS]

    cfg = Config(
        currency="usdt",
        autostart=bool(raw.get("autostart", True)),
        coins=coins,
        path=path,
    )
    if cfg.autostart != autostart_enabled():
        try:
            set_autostart(cfg.autostart)
        except OSError:
            log.exception("同步开机自启失败")
    return cfg


