#!/usr/bin/env bash
# 在线一键安装（免 sudo）
#   curl -fsSL https://raw.githubusercontent.com/shaoqing1998/term-quiz/main/install-online.sh | bash
set -euo pipefail

REPO="shaoqing1998/term-quiz"
VER="1.0.2"
BASE="https://github.com/${REPO}/releases/download/v${VER}"

TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

echo "下载 term-quiz ${VER} …"
curl -fsSL "${BASE}/term-quiz-${VER}.tar.gz" -o "${TMP}/pkg.tgz"
tar xzf "${TMP}/pkg.tgz" -C "${TMP}"
bash "${TMP}/term-quiz-${VER}/install.sh"
