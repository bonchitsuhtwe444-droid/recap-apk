#!/data/data/com.termux/files/usr/bin/bash

MARKER="$HOME/.recap_setup_done"
if [ -f "$MARKER" ]; then
    exit 0
fi

echo "======================================"
echo "  Movie Recap Tool — Setup"
echo "======================================"
echo "Packages install လုပ်နေပါတယ်..."
echo "Internet ချိတ်ထားပါ။"
echo ""

pkg update -y && pkg upgrade -y
pkg install -y python ffmpeg git cmake clang make
pip install requests python-dotenv edge-tts

touch "$MARKER"
echo ""
echo "✅ Setup ပြီးပါပြီ!"
