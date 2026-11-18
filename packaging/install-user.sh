#!/usr/bin/env bash
# 用户级安装（不需要 sudo）
# 装到 ~/.local/share/term-quiz，并在应用菜单建好启动项
set -euo pipefail

SRC="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DEST="$HOME/.local/share/term-quiz"
APPS="$HOME/.local/share/applications"

if ! command -v python3 >/dev/null 2>&1; then
    echo "缺少 python3，请先：sudo apt install -y python3" >&2
    exit 1
fi

if ! python3 -c "import gi; gi.require_version('Gtk','3.0'); from gi.repository import Gtk" 2>/dev/null; then
    echo "缺少 GTK 依赖，请先运行：" >&2
    echo "  sudo apt install -y python3-gi gir1.2-gtk-3.0" >&2
    exit 1
fi

mkdir -p "$DEST" "$APPS"

cp "$SRC/term_quiz.py" "$DEST/"
# 不覆盖已有词库，避免装新版本时把学过的数据冲掉
if [ ! -f "$DEST/words.json" ]; then
    cp "$SRC/words.json" "$DEST/words.json"
else
    echo "检测到已有词库，保留不覆盖：$DEST/words.json"
fi

cat > "$DEST/start.sh" <<EOF
#!/usr/bin/env bash
exec python3 "$DEST/term_quiz.py" "\$@"
EOF
chmod +x "$DEST/start.sh"

cat > "$APPS/io.github.termquiz.desktop" <<EOF
[Desktop Entry]
Version=1.0
Type=Application
Name=术语训练
Comment=术语题库与练习
Exec=$DEST/start.sh
Icon=accessories-dictionary
Terminal=false
StartupNotify=false
StartupWMClass=io.github.termquiz
Categories=Education;
EOF
chmod +x "$APPS/io.github.termquiz.desktop"

update-desktop-database "$APPS" >/dev/null 2>&1 || true

echo "✅ 安装完成：$DEST"
echo "   打开方式：按 Super 键搜索「术语训练」，或终端运行："
echo "   $DEST/start.sh"
