#!/usr/bin/env bash
# BARI setup script for Linux/macOS
# Usage: bash setup.sh
set -e

echo "== BARI setup =="

if ! command -v python3 &> /dev/null; then
    echo "python3 not found on PATH. Install Python 3.11+ first."
    exit 1
fi

echo "Installing CPU-only PyTorch (edit this script to install a CUDA build if you have GPU + disk headroom)..."
python3 -m pip install --no-cache-dir torch torchvision --index-url https://download.pytorch.org/whl/cpu

echo "Installing project dependencies..."
python3 -m pip install --no-cache-dir -r requirements.txt

if [ ! -f .env ]; then
    cp .env.example .env
    echo "Created .env from .env.example"
fi

mkdir -p data/input data/output data/evidence

echo "== Setup complete =="
echo "Next steps:"
echo "  1. python3 ml/datasets/prepare_dataset.py   (after downloading a dataset into ml/datasets/raw/)"
echo "  2. python3 ml/training/train.py"
echo "  3. python3 scripts/run_demo.py"
echo "  4. python3 dashboard/app.py"
