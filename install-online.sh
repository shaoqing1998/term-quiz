#!/usr/bin/env bash
# 在线一键安装（免 sudo）
#   curl -fsSL https://raw.githubusercontent.com/shaoqing1998/term-quiz/main/install-online.sh | bash
set -euo pipefail

REPO="shaoqing1998/term-quiz"
VER="1.1.0"
REL="https://github.com/${REPO}/releases/download/v${VER}"
RAW="https://raw.githubusercontent.com/${REPO}/main/dist"

TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

echo "下载 term-quiz ${VER} …"
if ! curl -fsSL --connect-timeout 15 "${REL}/term-quiz-${VER}.tar.gz" -o "${TMP}/pkg.tgz" 2>/dev/null; then
    echo "Release 下载失败，改用 raw 源…"
    curl -fsSL --connect-timeout 15 "${RAW}/term-quiz-${VER}.tar.gz" -o "${TMP}/pkg.tgz"
fi

tar xzf "${TMP}/pkg.tgz" -C "${TMP}"
bash "${TMP}/term-quiz-${VER}/install.sh"
