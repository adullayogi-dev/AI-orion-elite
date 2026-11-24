$root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $root
& (Join-Path $root ".venv\Scripts\python.exe") (Join-Path $root "apps\voice_assistant.py") @args
