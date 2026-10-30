$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

if (-not (Test-Path .venv\Scripts\python.exe)) {
    python -m venv .venv
}

$python = Join-Path $PSScriptRoot ".venv\Scripts\python.exe"
& $python -m pip install --upgrade pip
& $python -m pip install -r requirements.txt
New-Item -ItemType Directory -Force -Path assets | Out-Null
& $python -c "from crypto_tray.icons import save_ico; save_ico('assets/icon.ico')"
& $python -m PyInstaller --noconfirm --clean --windowed --onefile --name CryptoTray --icon assets/icon.ico --add-data "assets\icon.ico;assets" --collect-all customtkinter --hidden-import pystray._win32 --hidden-import PIL.Image --hidden-import PIL.ImageDraw --hidden-import PIL.ImageTk launch.py
Write-Output "Built dist\CryptoTray.exe"
