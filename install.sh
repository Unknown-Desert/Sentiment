#!/data/data/com.termux/files/usr/bin/bash
# ============================================
# SENTIMENT MONITOR - TERMUX LAUNCHER
# ============================================

echo "=========================================="
echo "  SENTIMENT MONITOR - TERMUX VERSION"
echo "=========================================="
echo ""

if ! command -v python3 &> /dev/null; then
    echo "[INFO] Python tidak ditemukan. Menginstal..."
    pkg update -y && pkg upgrade -y
    pkg install python -y
    echo "[OK] Python terinstal."
fi

if ! command -v git &> /dev/null; then
    echo "[INFO] Git tidak ditemukan. Menginstal..."
    pkg install git -y
    echo "[OK] Git terinstal."
fi

python3 -c "import requests" 2>/dev/null
if [ $? -ne 0 ]; then
    echo "[INFO] Library 'requests' belum ada. Menginstal..."
    pip install requests
    echo "[OK] requests terinstal."
fi

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
python3 "$SCRIPT_DIR/sentiment_termux.py"