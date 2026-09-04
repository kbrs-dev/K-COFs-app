#!/bin/bash
# Double-click launcher for the KBRS Production Markup app.
cd "$(dirname "$0")"

# Grab the latest version from GitHub first, if this folder is a git repo and
# git is available -- keeps this Mac in sync with any updates made elsewhere.
# Never blocks launching the app if it fails (no internet, no git, etc.).
if [ -d .git ] && command -v git &> /dev/null; then
    echo "Checking for updates..."
    git pull --ff-only 2>&1 | tail -5
fi

if ! command -v python3 &> /dev/null; then
    echo "Python 3 isn't installed."
    echo "Get it free from https://www.python.org/downloads/ (or run: brew install python-tk)"
    read -p "Press Enter to close..."
    exit 1
fi

if ! python3 -c "import tkinter" &> /dev/null; then
    echo "Python's tkinter module is missing."
    echo "If you installed Python via Homebrew, run this once in Terminal:"
    echo "    brew install python-tk"
    read -p "Press Enter to close..."
    exit 1
fi

if ! python3 -c "import reportlab, pypdf, PIL" &> /dev/null; then
    echo "First-time setup: installing free, open-source PDF/image libraries (reportlab, pypdf, Pillow)..."
    python3 -m pip install --user --quiet reportlab pypdf Pillow
fi

if ! python3 -c "import tkinterdnd2" &> /dev/null; then
    echo "Installing free drag-and-drop support (tkinterdnd2)..."
    python3 -m pip install --user --quiet tkinterdnd2
fi

if ! python3 -c "import pypdfium2" &> /dev/null; then
    echo "Installing free PDF-preview support for the layout editor (pypdfium2)..."
    python3 -m pip install --user --quiet pypdfium2
fi

if ! python3 -c "import pikepdf" &> /dev/null; then
    echo "Installing free fillable-PDF flattening support (pikepdf)..."
    python3 -m pip install --user --quiet pikepdf
fi

if ! python3 -c "import numpy" &> /dev/null; then
    echo "Installing free image-processing support (numpy)..."
    python3 -m pip install --user --quiet numpy
fi

python3 app.py
