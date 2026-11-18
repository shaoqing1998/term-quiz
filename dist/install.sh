#!/usr/bin/env bash
# 用法：curl -fsSL https://你的域名/term-quiz/install.sh | bash
set -euo pipefail
BASE="${TERM_QUIZ_BASE:-https://example.com/term-quiz}"
VER="1.0.4"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT
echo "从 $BASE 下载 term-quiz-$VER.tar.gz …"
curl -fsSL "$BASE/term-quiz-$VER.tar.gz" -o "$TMP/pkg.tgz"
tar xzf "$TMP/pkg.tgz" -C "$TMP"
bash "$TMP/term-quiz-$VER/install.sh"
