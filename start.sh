#!/usr/bin/env bash
# 术语训练启动器：带日志，方便排查为什么没窗口
set -u
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LOG="$HOME/.local/share/term-quiz/app.log"
mkdir -p "$(dirname "$LOG")"
echo "$(date '+%F %T')  launcher: cwd=$DIR python=$(command -v python3) session=${XDG_SESSION_TYPE:-?}" >> "$LOG"
cd "$DIR" || exit 1
exec python3 "$DIR/term_quiz.py" >> "$LOG" 2>&1
