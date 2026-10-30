# 币讯

Windows 托盘程序，用来看加密货币行情和中文快讯。

## 功能

- 只驻留系统托盘。左键点图标打开或隐藏弹窗，再点一次、按 Esc，或点到窗口外面，都会收起
- 窗口固定在工作区右下角，贴在任务栏上方，约 400×640，没有最小化、最大化和关闭按钮
- 弹窗里用「行情」「新闻」切换。价格是 OKX USDT 永续合约的最新价，单位一律是 USDT
- 行情固定显示 24 小时成交额最高的 10 个 USDT 永续合约，按成交额从高到低排列
- 搜索框按币种名称或代号查找，结果同样用合约价
- 价格大约每 2 秒更新。走势、总市值和恐惧贪婪指数大约每分钟更新
- 新闻只显示中文标题，打开时拉一次，之后点「刷新」再拉
- 右键菜单只有「开机自启」和「退出」。第一次运行默认打开开机自启
- 已经在运行时再打开一次，只会把现有窗口唤出来

合约名单、最新价、24 小时成交额和走势来自 OKX USDT 永续。总市值来自 CoinGecko，按 USDT 显示。恐惧贪婪指数来自 alternative.me，快讯来自 Google 新闻中文结果。请求走系统代理。

## 运行

需要 Python 3.12。

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe launch.py
```

检查接口是否可用：

```powershell
.\.venv\Scripts\python.exe -m crypto_tray --check
```

配置和日志在 `%APPDATA%\CryptoTray`。

## 打包

```powershell
.\build.ps1
```

生成 `dist\CryptoTray.exe`。打包前先退出正在运行的币讯，否则单实例端口仍被占用。
