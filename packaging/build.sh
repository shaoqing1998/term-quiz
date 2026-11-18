#!/usr/bin/env bash
# 打两个包：
#   dist/term-quiz-<ver>.tar.gz   用户级安装（免 sudo）
#   dist/term-quiz_<ver>_all.deb  系统级安装（双击即可）
set -euo pipefail

PROJ="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VER="1.0.12"
PKG="term-quiz"
DIST="$PROJ/dist"
STAGE="$DIST/.stage"

rm -rf "$DIST"
mkdir -p "$DIST" "$STAGE"

# ---------------------------------------------------------------- tar.gz
TDIR="$STAGE/$PKG-$VER"
mkdir -p "$TDIR"
cp "$PROJ/term_quiz.py" "$PROJ/words.json" "$TDIR/"
cp "$PROJ/packaging/install-user.sh" "$TDIR/install.sh"
chmod +x "$TDIR/install.sh"
tar -czf "$DIST/$PKG-$VER.tar.gz" -C "$STAGE" "$PKG-$VER"
echo "✓ $DIST/$PKG-$VER.tar.gz"

# ---------------------------------------------------------------- deb
DR="$STAGE/deb"
mkdir -p "$DR/DEBIAN" "$DR/usr/bin" "$DR/usr/share/$PKG" "$DR/usr/share/applications"
cp "$PROJ/term_quiz.py" "$PROJ/words.json" "$DR/usr/share/$PKG/"

cat > "$DR/usr/bin/$PKG" <<'EOF'
#!/bin/sh
exec python3 /usr/share/term-quiz/term_quiz.py "$@"
EOF
chmod 755 "$DR/usr/bin/$PKG"

cat > "$DR/usr/share/applications/io.github.termquiz.desktop" <<'EOF'
[Desktop Entry]
Version=1.0
Type=Application
Name=术语训练
Comment=术语题库与练习
Exec=term-quiz
Icon=accessories-dictionary
Terminal=false
StartupNotify=false
StartupWMClass=io.github.termquiz
Categories=Education;
EOF
chmod 644 "$DR/usr/share/applications/io.github.termquiz.desktop"

cat > "$DR/DEBIAN/control" <<EOF
Package: $PKG
Version: $VER
Section: education
Priority: optional
Architecture: all
Depends: python3, python3-gi, gir1.2-gtk-3.0
Maintainer: Kornel Jiang <kornel.jiang@localhost>
Description: 术语训练 - 本地术语题库与练习
 题库 / 答题 / 记录 三页；词库和历史记录保存在 ~/.local/share/term-quiz，
 卸载不会删除用户数据。
EOF

cat > "$DR/DEBIAN/postinst" <<'EOF'
#!/bin/sh
set -e
update-desktop-database /usr/share/applications >/dev/null 2>&1 || true
exit 0
EOF
chmod 755 "$DR/DEBIAN/postinst"

cat > "$DR/DEBIAN/postrm" <<'EOF'
#!/bin/sh
set -e
update-desktop-database /usr/share/applications >/dev/null 2>&1 || true
exit 0
EOF
chmod 755 "$DR/DEBIAN/postrm"

dpkg-deb --build --root-owner-group "$DR" "$DIST/${PKG}_${VER}_all.deb" >/dev/null
echo "✓ $DIST/${PKG}_${VER}_all.deb"

# ---------------------------------------------------------------- 服务器一键脚本
cat > "$DIST/install.sh" <<'EOF'
#!/usr/bin/env bash
# 用法：curl -fsSL https://你的域名/term-quiz/install.sh | bash
set -euo pipefail
BASE="${TERM_QUIZ_BASE:-https://example.com/term-quiz}"
VER="1.0.12"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT
echo "从 $BASE 下载 term-quiz-$VER.tar.gz …"
curl -fsSL "$BASE/term-quiz-$VER.tar.gz" -o "$TMP/pkg.tgz"
tar xzf "$TMP/pkg.tgz" -C "$TMP"
bash "$TMP/term-quiz-$VER/install.sh"
EOF
chmod +x "$DIST/install.sh"
echo "✓ $DIST/install.sh"

rm -rf "$STAGE"
echo
echo "打包完成："
ls -lh "$DIST"
