# BARI setup script for Windows (PowerShell)
# Usage: powershell -ExecutionPolicy Bypass -File setup_windows.ps1

Write-Host "== BARI setup ==" -ForegroundColor Cyan

if (-not (Get-Command python -ErrorAction SilentlyContinue)) {
    Write-Host "Python not found on PATH. Install Python 3.11+ first." -ForegroundColor Red
    exit 1
}

Write-Host "Installing CPU-only PyTorch (smaller download; edit this script to install a CUDA build if you have GPU + disk headroom)..."
python -m pip install --no-cache-dir torch torchvision --index-url https://download.pytorch.org/whl/cpu

Write-Host "Installing project dependencies..."
python -m pip install --no-cache-dir -r requirements.txt

if (-not (Test-Path ".env")) {
    Copy-Item ".env.example" ".env"
    Write-Host "Created .env from .env.example"
}

New-Item -ItemType Directory -Force -Path "data/input", "data/output", "data/evidence" | Out-Null

Write-Host "== Setup complete ==" -ForegroundColor Green
Write-Host "Next steps:"
Write-Host "  1. python ml/datasets/prepare_dataset.py   (after downloading a dataset into ml/datasets/raw/)"
Write-Host "  2. python ml/training/train.py"
Write-Host "  3. python scripts/run_demo.py"
Write-Host "  4. python dashboard/app.py"
