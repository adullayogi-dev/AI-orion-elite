$root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $root
& (Join-Path $root ".venv\Scripts\python.exe") -m streamlit run (Join-Path $root "apps\hud.py") @args
