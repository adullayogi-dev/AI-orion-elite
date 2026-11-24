<#
  ORION ELITE — one-time environment setup (idempotent).
  Run from PowerShell:  .\setup.ps1
#>
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $root

$venv = Join-Path $root ".venv"
$py   = Join-Path $venv "Scripts\python.exe"

Write-Host "`n=== ORION ELITE // SETUP ===" -ForegroundColor Cyan

if (-not (Test-Path $py)) {
  Write-Host "[1/5] Creating virtual environment ..." -ForegroundColor Yellow
  python -m venv $venv
} else {
  Write-Host "[1/5] Virtual environment already present." -ForegroundColor Green
}

Write-Host "[2/5] Upgrading pip ..." -ForegroundColor Yellow
& $py -m pip install --upgrade pip -q

Write-Host "[3/5] Installing dependencies (this can take a few minutes) ..." -ForegroundColor Yellow
& $py -m pip install -r (Join-Path $root "requirements.txt")
if ($LASTEXITCODE -ne 0) { throw "pip install failed." }

Write-Host "[4/5] Downloading OpenWakeWord ONNX models ..." -ForegroundColor Yellow
& $py -c "from openwakeword import utils; utils.download_models()"
if ($LASTEXITCODE -ne 0) { Write-Host "Wake model download skipped (keyword mode still works)." -ForegroundColor DarkYellow }

Write-Host "[5/5] Checking Ollama brain ..." -ForegroundColor Yellow
try {
  $models = & ollama list 2>$null
  if ($models -match "qwen3:4b-instruct") {
    Write-Host "      qwen3:4b-instruct already installed." -ForegroundColor Green
  } else {
    Write-Host "      Pulling qwen3:4b-instruct (~2.5 GB) ..." -ForegroundColor Yellow
    & ollama pull qwen3:4b-instruct
  }
} catch {
  Write-Host "      Ollama not found. Install it from https://ollama.com" -ForegroundColor Red
}

Write-Host "`n=== VERIFYING ===" -ForegroundColor Cyan
& $py -c "import numpy, sounddevice, faster_whisper, pyttsx3, ollama, streamlit, flask, psutil; print('CORE IMPORTS OK')"
& $py (Join-Path $root "apps\voice_assistant.py") --selftest

Write-Host "`nSetup complete. Start with:  .\run_voice.ps1" -ForegroundColor Green
