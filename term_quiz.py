#!/usr/bin/env python3
"""术语训练 · 桌面版

三页：题库（看知识）/ 答题（主动点击开始）/ 记录（正确率统计）。
不再有通知和定时器。

用法：
    term_quiz.py            打开桌面应用
    term_quiz.py quiz       终端里答一道（应急用）
    term_quiz.py add TERM 'English Full' '中文' ['读法']
    term_quiz.py install    安装桌面启动项，并关掉旧的定时通知
    term_quiz.py --smoke    自检：构建界面后立即退出（不弹窗）
"""
from __future__ import annotations

import json
import os
import random
import re
import shutil
import subprocess
import sys
import unicodedata
from collections import Counter, defaultdict
from datetime import datetime
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parent
TZ = ZoneInfo("Asia/Shanghai")

USER_DIR = Path.home() / ".local/share/term-quiz"
HISTORY_PATH = USER_DIR / "history.jsonl"
SYSTEM_WORDS = ROOT / "words.json"
USER_WORDS = USER_DIR / "words.json"


def words_path() -> Path:
    """用户词库优先；没有就把系统自带的复制一份到用户目录。"""
    if USER_WORDS.exists():
        return USER_WORDS
    if SYSTEM_WORDS.exists():
        try:
            USER_DIR.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(SYSTEM_WORDS, USER_WORDS)
            return USER_WORDS
        except Exception:
            return SYSTEM_WORDS
    return USER_WORDS

APP_ID = "io.github.termquiz"
APP_NAME = "术语训练"
LOG_PATH = USER_DIR / "app.log"


def log(msg: str) -> None:
    try:
        LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
        with LOG_PATH.open("a", encoding="utf-8") as f:
            f.write(f"{datetime.now(TZ).isoformat(timespec='seconds')}  {msg}\n")
    except Exception:
        pass

TYPES = ("en_full", "zh", "pronounce", "relation")
TYPE_LABEL = {
    "en_full": "写出英文全称",
    "zh": "写出中文意思",
    "pronounce": "选出正确读法",
    "relation": "板卡关系四选一",
}

# 逐词释义：短义 + 一句解释（点开气泡时显示）
WORD_BOOK = {
    "proof": ("验证", "工程里的 proof 不是数学证明，而是「能做出东西证明这条路走得通」。"),
    "of": ("的", "结构助词，只起连接作用，本身没有技术含义。"),
    "concept": ("概念", "还停留在想法阶段的方案；POC 就是把这个想法先做成能跑的东西。"),
    "open": ("开放的", "指规范公开、任何厂商都能照着做，不等于开源。"),
    "pluggable": ("可插拔的", "像积木一样插进插槽就能用，不用焊接或改线。"),
    "specification": ("规范", "规定尺寸、引脚、电气参数这类硬指标的文档，照它做才能互通。"),
    "smart": ("智能的", "偏营销词，通常只说「带处理器、能跑系统」，不是指 AI。"),
    "mobility": ("移动性", "体积小、功耗低，能装进移动设备或嵌入式设备。"),
    "architecture": ("架构", "芯片内部的组织方式（核、缓存、总线怎么排），不是建筑。"),
    "baseband": ("基带", "负责无线通信的底层信号处理，和 AP（应用处理器）是两套东西。"),
    "processor": ("处理器", "执行指令的芯片；AP 跑系统，BP 跑通信。"),
    "module": ("模组", "把芯片、内存、电源做在一块小板上，直接贴到主板上用。"),
    "board": ("板", "承载元器件的 PCB，按功能分核心板、底板、载板。"),
    "interface": ("接口", "两个部件之间约定好的连接方式，分物理接口和软件接口。"),
    "serial": ("串行", "数据一位一位传，线少、距离长，调试口常用。"),
    "debug": ("调试", "定位问题的过程；调试口通常是串口或 USB。"),
    "boot": ("启动", "从上电到系统跑起来的过程，涉及 bootloader、kernel、init。"),
    "kernel": ("内核", "操作系统的核心，管进程、内存、驱动。"),
    "driver": ("驱动", "让内核认识硬件的那层代码。"),
    "display": ("显示", "出图通路；常涉及 DP/HDMI 和 DRM 框架。"),
    "audio": ("音频", "声音通路；Android 上走 AudioFlinger 和 HAL。"),
}


def split_words(text: str) -> list[str]:
    return [w for w in (text or "").split() if w]


# 多词短语：优先整体匹配，不再逐词拆
PHRASES = {
    "proof of": ("对……的验证", "proof of 是固定搭配，整体表示「对……的证明 / 验证」，一般不拆开逐字理解。"),
    "point of contact": ("对接人", "项目里的联系人 / 对接人。"),
    "plug and play": ("即插即用", "插上就能用，不需要额外配置驱动。"),
}


def segment_words(text: str) -> list[dict[str, Any]]:
    """按「短语优先」切分，返回 [{text, zh, note}]。zh 为空表示没有解释。"""
    toks = split_words(text)
    out: list[dict[str, Any]] = []
    i = 0
    while i < len(toks):
        hit = None
        for n in (3, 2):
            if i + n <= len(toks):
                cand = " ".join(toks[i:i + n])
                if cand.lower() in PHRASES:
                    zh, note = PHRASES[cand.lower()]
                    hit = (cand, zh, note, n)
                    break
        if hit:
            cand, zh, note, n = hit
            out.append({"text": cand, "zh": zh, "note": note})
            i += n
            continue
        tok = toks[i]
        zh, note = word_info(tok)
        out.append({"text": tok, "zh": zh, "note": note})
        i += 1
    return out


def word_info(token: str):
    """返回 (中文短义, 详细解释) 或 (None, None)。"""
    key = "".join(ch for ch in token.lower() if ch.isalpha() or ch == "-")
    if key in WORD_BOOK:
        return WORD_BOOK[key]
    if "-" in key:
        parts = [WORD_BOOK.get(p) for p in key.split("-")]
        if all(parts):
            return ("".join(x[0] for x in parts), "复合词：" + "；".join(x[1] for x in parts))
    return (None, None)


# ---------------------------------------------------------------- 数据

def load_db() -> dict[str, Any]:
    return json.loads(words_path().read_text(encoding="utf-8"))


def save_db(db: dict[str, Any]) -> None:
    words_path().write_text(
        json.dumps(db, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


def load_history() -> list[dict[str, Any]]:
    if not HISTORY_PATH.exists():
        return []
    rows = []
    for line in HISTORY_PATH.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return rows


def append_history(row: dict[str, Any]) -> None:
    HISTORY_PATH.parent.mkdir(parents=True, exist_ok=True)
    with HISTORY_PATH.open("a", encoding="utf-8") as f:
        f.write(json.dumps(row, ensure_ascii=False) + "\n")


# ---------------------------------------------------------------- 判分

def normalize(text: str) -> str:
    text = unicodedata.normalize("NFKC", text or "")
    text = text.strip().lower()
    text = text.replace("—", "-").replace("–", "-")
    text = re.sub(r"[/_,;:()（）【】\[\]{}'\"`.]", " ", text)
    text = re.sub(r"\s+", " ", text)
    return text


def token_set(text: str) -> set[str]:
    return {
        t
        for t in re.split(r"[\s\-]+", normalize(text))
        if t and t not in {"of", "the", "a", "an", "and", "或"}
    }


def heuristic_grade(kind: str, word: dict[str, Any], answer: str) -> tuple[bool, str]:
    n = normalize(answer)
    if not n:
        return False, "空答案。"

    if kind == "en_full":
        targets = [word["en_full"], *word.get("en_aliases", [])]
        for t in targets:
            if normalize(t) == n:
                return True, f"对，标准写法是 {word['en_full']}。"
            if SequenceMatcher(None, normalize(t), n).ratio() >= 0.82:
                return True, f"接近标准写法 {word['en_full']}，算过。"
            if token_set(t) <= token_set(answer) or token_set(answer) <= token_set(t):
                if len(token_set(answer) & token_set(t)) >= max(2, len(token_set(t)) - 1):
                    return True, f"关键词够了：{word['en_full']}。"
        return False, f"更标准的是：{word['en_full']}"

    if kind == "zh":
        targets = [word["zh"], *word.get("zh_aliases", [])]
        for t in targets:
            nt = normalize(t)
            if nt in n or n in nt:
                return True, f"可以。参考：{word['zh']}"
            if SequenceMatcher(None, nt, n).ratio() >= 0.62:
                return True, f"意思对得上。参考：{word['zh']}"
        for t in targets:
            chars = set(re.findall(r"[\u4e00-\u9fff]", t))
            ac = set(re.findall(r"[\u4e00-\u9fff]", answer))
            if chars and len(chars & ac) / len(chars) >= 0.5:
                return True, f"意思接近。参考：{word['zh']}"
        return False, f"参考意思：{word['zh']}"

    targets = [word.get("pronounce", ""), *word.get("pronounce_accept", [])]
    for t in targets:
        if SequenceMatcher(None, normalize(t), n).ratio() >= 0.72:
            return True, f"读法可接受。参考：{word.get('pronounce')}"
    return False, f"参考读法：{word.get('pronounce')}"


def ollama_grade(kind: str, word: dict[str, Any], answer: str) -> tuple[bool, str] | None:
    """本机有 Ollama 就让它复核一遍；没有就返回 None。"""
    prompt = (
        "你在批改工程师的术语小测。只回复一行中文：先写「通过」或「不通过」，再写一句理由。\n"
        "意思对、读音接近、全称差一两个虚词都算通过。不要太严。\n"
        f"术语: {word['term']}\n"
        f"题型: {TYPE_LABEL[kind]}\n"
        f"参考英文全称: {word['en_full']}\n"
        f"参考中文: {word['zh']}\n"
        f"参考读法: {word.get('pronounce', '')}\n"
        f"学员答案: {answer}\n"
    )
    try:
        proc = subprocess.run(
            [
                "curl", "-sS", "-m", "8",
                "http://127.0.0.1:11434/api/generate",
                "-H", "Content-Type: application/json",
                "-d", json.dumps({
                    "model": os.environ.get("TERM_QUIZ_OLLAMA_MODEL", "qwen2.5:7b"),
                    "prompt": prompt,
                    "stream": False,
                    "options": {"temperature": 0.1},
                }),
            ],
            capture_output=True,
            text=True,
            timeout=10,
        )
        if proc.returncode != 0 or not proc.stdout.strip():
            return None
        data = json.loads(proc.stdout)
        text = (data.get("response") or "").strip()
        if not text:
            return None
        ok = text.startswith("通过") or text.upper().startswith("PASS")
        why = text.replace("PASS", "通过", 1).replace("FAIL", "不通过", 1)
        if not why.startswith(("通过", "不通过")):
            why = ("通过" if ok else "不通过") + "。" + why
        return ok, why
    except Exception:
        return None


def grade(kind: str, word: dict[str, Any], answer: str) -> tuple[bool, str, str]:
    h_ok, h_why = heuristic_grade(kind, word, answer)
    ai = ollama_grade(kind, word, answer)
    if ai:
        ok, why = ai
        if h_ok and not ok:
            return True, h_why + "（本机模型偏严，按宽松规则通过）", "规则匹配"
        return ok, why, "本机模型"
    return h_ok, h_why, "规则匹配"


# ---------------------------------------------------------------- 统计

def accuracy_rows(history: list[dict[str, Any]], field: str) -> list[tuple[str, int, int]]:
    total: Counter[str] = Counter()
    ok: Counter[str] = Counter()
    for r in history:
        key = r.get(field) or "?"
        total[key] += 1
        if r.get("ok"):
            ok[key] += 1
    rows = [(k, ok[k], total[k]) for k in total]
    rows.sort(key=lambda x: (x[1] / x[2] if x[2] else 0, -x[2]))
    return rows


def overall(history: list[dict[str, Any]]) -> tuple[int, int]:
    return sum(1 for r in history if r.get("ok")), len(history)


def smart_weights(history: list[dict[str, Any]]) -> dict[tuple[str, str], float]:
    """(术语, 题型) → 权重。错得多的权重高。"""
    total: Counter[tuple[str, str]] = Counter()
    ok: Counter[tuple[str, str]] = Counter()
    for r in history:
        key = (r.get("term") or "?", r.get("kind") or "?")
        total[key] += 1
        if r.get("ok"):
            ok[key] += 1
    weights: dict[tuple[str, str], float] = {}
    for key, n in total.items():
        acc = ok[key] / n if n else 0.0
        weights[key] = 1.0 + (1.0 - acc) * 2.0
    return weights


# ---------------------------------------------------------------- 出题

def build_pool(db: dict[str, Any], kinds: set[str]) -> list[dict[str, Any]]:
    pool: list[dict[str, Any]] = []
    for w in db.get("words") or []:
        for k in ("en_full", "zh", "pronounce"):
            if k not in kinds:
                continue
            if k == "pronounce" and not w.get("pronounce_choices"):
                continue
            pool.append({"mode": "term", "word": w, "kind": k})
    if "relation" in kinds:
        for m in db.get("mcqs") or []:
            pool.append({"mode": "mcq", "q": m, "kind": "relation"})
    return pool


def shuffle_weighted(pool: list[dict[str, Any]], weights: dict[tuple[str, str], float]) -> list[dict[str, Any]]:
    keyed = []
    for item in pool:
        name = item["word"]["term"] if item["mode"] == "term" else "板卡关系"
        w = weights.get((name, item["kind"]), 1.0)
        u = random.random() or 1e-9
        keyed.append((u ** (1.0 / max(w, 1e-9)), item))
    keyed.sort(key=lambda x: -x[0])
    return [item for _, item in keyed]


def build_session(db: dict[str, Any], kinds: set[str], count: int, smart: bool) -> list[dict[str, Any]]:
    pool = build_pool(db, kinds)
    if not pool:
        return []
    weights = smart_weights(load_history()) if smart else {}
    ordered = shuffle_weighted(pool, weights)
    if count <= 0 or count >= len(ordered):
        return ordered
    return ordered[:count]


# ---------------------------------------------------------------- 界面

def pango_esc(text: str) -> str:
    return (text or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _span(color: str, text: str) -> str:
    if not text:
        return ""
    return f'<span foreground="{color}">{pango_esc(text)}</span>'


def align_markup(correct: str, given: str) -> tuple[str, str, int]:
    a, b = correct or "", given or ""
    green, red = "#1b8a3a", "#d32f2f"
    ca: list[str] = []
    cb: list[str] = []
    sm = SequenceMatcher(a=a.lower(), b=b.lower())
    for tag, i1, i2, j1, j2 in sm.get_opcodes():
        if tag == "equal":
            ca.append(_span(green, a[i1:i2]))
            cb.append(_span(green, b[j1:j2]))
        elif tag == "replace":
            ca.append(_span(red, a[i1:i2]))
            cb.append(_span(red, b[j1:j2]))
        elif tag == "delete":
            ca.append(_span(red, a[i1:i2]))
        elif tag == "insert":
            cb.append(_span(red, b[j1:j2]))
    return ("".join(ca) or _span(red, "（空）"),
            "".join(cb) or _span(red, "（空）"),
            int(round(sm.ratio() * 100)))


CSS = """
.hero { font-size: 30px; font-weight: 700; }
.big-number { font-size: 26px; font-weight: 700; }
.card { background-color: alpha(currentColor, 0.05); border-radius: 10px; padding: 14px; }
.muted { opacity: 0.7; }
        .detail-view, .detail-view text, .detail-view border {
            background-color: transparent;
        }
        .plain-list, .plain-list row, .plain-list viewport, .plain-list list {
            background-color: transparent;
        }
        .plain-list row:selected {
            background-color: @theme_selected_bg_color;
        }
.term-name { font-weight: 700; font-size: 15px; }
.badge-ok { background-color: #2e7d32; color: #ffffff; border-radius: 8px; padding: 6px 16px; font-weight: 700; }
.badge-bad { background-color: #c62828; color: #ffffff; border-radius: 8px; padding: 6px 16px; font-weight: 700; }
.badge-neutral { background-color: alpha(currentColor, 0.15); border-radius: 8px; padding: 6px 16px; font-weight: 700; }
.question { font-size: 19px; }
.answer { font-size: 17px; }
"""


def install_css() -> None:
    import gi

    gi.require_version("Gtk", "3.0")
    gi.require_version("Gdk", "3.0")
    from gi.repository import Gdk, Gtk

    provider = Gtk.CssProvider()
    provider.load_from_data(CSS.encode("utf-8"))
    screen = Gdk.Screen.get_default()
    if screen is not None:
        Gtk.StyleContext.add_provider_for_screen(
            screen, provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION
        )


def label(text: str = "", markup: bool = False, **kw) -> "Any":
    from gi.repository import Gtk

    lb = Gtk.Label(xalign=kw.pop("xalign", 0), yalign=kw.pop("yalign", 0.5))
    lb.set_line_wrap(True)
    lb.set_selectable(kw.pop("selectable", True))
    if markup:
        lb.set_markup(text)
    else:
        lb.set_text(text)
    for k, v in kw.items():
        getattr(lb, k)(v)
    return lb


class LibraryPage:
    def __init__(self, win):
        from gi.repository import Gtk

        self.win = win
        self.db = load_db()
        self.history = load_history()
        self._links: list[dict[str, Any]] = []
        self._popover = None

        self.box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=0)

        # ---------------- 左栏：搜索 + 列表 ----------------
        left = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        left.set_size_request(340, -1)

        self.search = Gtk.SearchEntry()
        self.search.set_placeholder_text("搜术语 / 英文全称 / 中文")
        self.search.set_margin_start(14)
        self.search.set_margin_end(14)
        self.search.set_margin_top(12)
        self.search.set_margin_bottom(4)
        self.search.connect("search-changed", lambda *_: self.refresh_list())
        left.pack_start(self.search, False, False, 0)

        self.list = Gtk.ListBox()
        self.list.set_selection_mode(Gtk.SelectionMode.SINGLE)
        self.list.connect("row-selected", self.on_select)
        self.list.get_style_context().add_class("plain-list")
        sw = Gtk.ScrolledWindow()
        sw.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        sw.get_style_context().add_class("plain-list")
        sw.set_margin_top(6)
        sw.add(self.list)
        left.pack_start(sw, True, True, 0)

        self.count_label = label("", False)
        self.count_label.get_style_context().add_class("muted")
        self.count_label.set_margin_start(14)
        self.count_label.set_margin_end(14)
        self.count_label.set_margin_top(8)
        self.count_label.set_margin_bottom(10)
        left.pack_start(Gtk.Separator(orientation=Gtk.Orientation.HORIZONTAL), False, False, 0)
        left.pack_start(self.count_label, False, False, 0)

        # ---------------- 右栏：可自由选择的文本视图 ----------------
        self.detail = Gtk.TextView()
        self.detail.set_editable(False)
        self.detail.set_cursor_visible(False)
        self.detail.set_wrap_mode(Gtk.WrapMode.WORD_CHAR)
        self.detail.set_left_margin(28)
        self.detail.set_right_margin(24)
        self.detail.set_top_margin(20)
        self.detail.set_bottom_margin(20)
        self.detail.get_style_context().add_class("detail-view")
        self.detail.connect("button-press-event", self.on_detail_press)
        self.detail.connect("button-release-event", self.on_detail_release)
        self._press_xy = (0.0, 0.0)
        self.buf = self.detail.get_buffer()
        self._make_tags()

        sw2 = Gtk.ScrolledWindow()
        sw2.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        sw2.get_style_context().add_class("plain-list")
        sw2.add(self.detail)

        self.box.pack_start(left, False, False, 0)
        self.box.pack_start(Gtk.Separator(orientation=Gtk.Orientation.VERTICAL), False, False, 0)
        self.box.pack_start(sw2, True, True, 0)

        self.refresh_list()

    # ---------------- 文本标签 ----------------
    def _make_tags(self) -> None:
        from gi.repository import Pango
        b = self.buf
        b.create_tag("term", size=24 * Pango.SCALE, weight=Pango.Weight.BOLD)
        b.create_tag("chip", size=9 * Pango.SCALE, foreground="#8a8a8a")
        b.create_tag("section", size=9 * Pango.SCALE, weight=Pango.Weight.BOLD,
                     foreground="#8a8a8a", pixels_above_lines=14, pixels_below_lines=3)
        b.create_tag("body", size=11 * Pango.SCALE)
        b.create_tag("muted", size=9 * Pango.SCALE, foreground="#8a8a8a")
        b.create_tag("fullname", size=13 * Pango.SCALE, weight=Pango.Weight.BOLD)
        b.create_tag("ipa", size=12 * Pango.SCALE, family="DejaVu Sans")
        b.create_tag("link", size=13 * Pango.SCALE, weight=Pango.Weight.BOLD,
                     foreground="#1c71d8", underline=Pango.Underline.SINGLE)
        b.create_tag("action", size=11 * Pango.SCALE,
                     foreground="#1c71d8", underline=Pango.Underline.SINGLE)

    # ---------------- 列表 ----------------
    def refresh_list(self) -> None:
        from gi.repository import Gtk

        for row in self.list.get_children():
            self.list.remove(row)

        q = normalize(self.search.get_text())
        per_term: dict[str, list[int]] = defaultdict(lambda: [0, 0])
        for r in self.history:
            if r.get("term"):
                per_term[r["term"]][1] += 1
                if r.get("ok"):
                    per_term[r["term"]][0] += 1

        shown = 0
        for idx, w in enumerate(self.db.get("words") or []):
            hay = normalize(f"{w['term']} {w.get('en_full','')} {w.get('zh','')}")
            if q and q not in hay:
                continue
            row = Gtk.ListBoxRow()
            row.term_index = idx
            inner = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
            inner.set_margin_start(14)
            inner.set_margin_end(14)
            inner.set_margin_top(7)
            inner.set_margin_bottom(7)

            col = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
            name = label("", True, selectable=False)
            name.set_markup(f"<span size='large' weight='bold'>{pango_esc(w['term'])}</span>")
            col.pack_start(name, False, False, 0)
            sub = label(f"{w.get('en_full','')}", False, selectable=False)
            sub.get_style_context().add_class("muted")
            sub.set_ellipsize(3)
            col.pack_start(sub, False, False, 0)
            inner.pack_start(col, True, True, 0)

            ok, total = per_term.get(w["term"], [0, 0])
            if total:
                chip = label("", True, xalign=1, selectable=False)
                chip.set_markup(f"<span size='small'>{ok}/{total}</span>")
                chip.set_valign(0.5)
                inner.pack_end(chip, False, False, 0)
            row.add(inner)
            self.list.add(row)
            shown += 1

        self.count_label.set_text(f"共 {len(self.db.get('words') or [])} 条，显示 {shown} 条")
        first = self.list.get_row_at_index(0)
        if first:
            self.list.select_row(first)
        else:
            self.show_empty()

    def show_empty(self) -> None:
        self.buf.set_text("没有匹配的术语。")

    def on_select(self, _lb, row) -> None:
        if row is None:
            return
        self.show_detail(self.db["words"][row.term_index])

    # ---------------- 详情 ----------------
    def show_detail(self, w: dict[str, Any]) -> None:
        b = self.buf
        b.set_text("")
        self._links = []

        def ins(text: str, *tags: str) -> None:
            end = b.get_end_iter()
            if tags:
                b.insert_with_tags_by_name(end, text, *tags)
            else:
                b.insert(end, text)

        ok, total = 0, 0
        for r in self.history:
            if r.get("term") == w["term"]:
                total += 1
                if r.get("ok"):
                    ok += 1

        ins(w["term"], "term")
        if total:
            pct = int(round(ok / total * 100))
            ins(f"\n历史正确率 {pct}%（{ok}/{total}）", "chip")

        def sec(title: str) -> None:
            ins("\n", "body")
            ins(title, "section")
            ins("\n", "body")

        # 英文全称（词可点）
        sec("英文全称")
        segs = segment_words(w.get("en_full", ""))
        for i, seg in enumerate(segs):
            start = b.get_char_count()
            if seg["zh"]:
                ins(seg["text"], "link")
                self._links.append({"start": start, "end": b.get_char_count(),
                                    "kind": "word", **seg})
            else:
                ins(seg["text"], "fullname")
            if i < len(segs) - 1:
                ins(" ")

        sec("中文意思")
        ins(w.get("zh", "") or "—", "body")

        if w.get("pronounce"):
            sec("读法")
            raw = w["pronounce"]
            main, variant = raw, ""
            if "（" in raw:
                cut = raw.index("（")
                main = raw[:cut].strip()
                variant = raw[cut + 1:].rstrip("）").strip()
            ins(main, "ipa")
            if variant:
                ins("\n", "body")
                ins(variant, "muted")

        if w.get("en_aliases"):
            sec("英文别名")
            ins("、".join(w["en_aliases"]), "body")

        if w.get("zh_aliases"):
            sec("中文别名")
            ins("、".join(w["zh_aliases"]), "body")

        rel = [m for m in (self.db.get("mcqs") or [])
               if w["term"].lower() in json.dumps(m, ensure_ascii=False).lower()]

        def action_link(text: str, kind: str, payload) -> None:
            ins("\n", "body")
            start = b.get_char_count()
            ins(text, "action")
            self._links.append({"start": start, "end": b.get_char_count(),
                                "kind": kind, "text": text, "payload": payload})

        if rel:
            action_link(f"▸ 相关题目（{len(rel)}）", "mcq", rel)

        action_link(f"▸ 维基百科：{w.get('en_full') or w['term']}", "wiki",
                    {"term": w["term"], "en_full": w.get("en_full") or w["term"]})

        self.detail.scroll_to_mark(b.get_insert(), 0, False, 0, 0)


    # ---------------- 相关题目弹窗 ----------------
    def open_mcq_dialog(self, rel) -> None:
        from gi.repository import Gtk

        dlg = Gtk.Dialog(title="相关题目", transient_for=self.win.window, flags=0)
        dlg.set_default_size(640, 540)
        dlg.add_button("关闭", Gtk.ResponseType.CLOSE)

        area = dlg.get_content_area()
        area.set_spacing(10)
        area.set_border_width(16)

        sw = Gtk.ScrolledWindow()
        sw.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=14)
        box.set_margin_end(6)

        for m in rel:
            card = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
            card.get_style_context().add_class("card")
            q = label("", True)
            q.set_markup(f"<b>{pango_esc(m['prompt'])}</b>")
            card.pack_start(q, False, False, 0)
            for i, c in enumerate(m["choices"]):
                row = label(("✔ " if i == 0 else "· ") + c, False)
                if i == 0:
                    row.get_style_context().add_class("right-answer")
                card.pack_start(row, False, False, 0)
            if m.get("explain"):
                ex = label(m["explain"], False)
                ex.get_style_context().add_class("muted")
                card.pack_start(ex, False, False, 0)
            box.pack_start(card, False, False, 0)

        sw.add(box)
        area.pack_start(sw, True, True, 0)
        dlg.show_all()
        dlg.run()
        dlg.destroy()

    # ---------------- 内嵌维基百科 ----------------
    def open_wiki(self, term: str, en_full: str) -> None:
        from urllib.parse import quote
        from gi.repository import Gtk

        zh = "https://zh.wikipedia.org/w/index.php?search=" + quote(en_full or term)
        en = "https://en.wikipedia.org/w/index.php?search=" + quote(en_full or term)

        dlg = Gtk.Dialog(title=f"维基百科 · {term}",
                         transient_for=self.win.window, flags=0)
        dlg.set_default_size(980, 720)
        dlg.add_button("关闭", Gtk.ResponseType.CLOSE)
        area = dlg.get_content_area()

        view = None
        try:
            import gi
            gi.require_version("WebKit2", "4.1")
            from gi.repository import WebKit2
            view = WebKit2.WebView()
        except Exception:
            view = None

        bar = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        bar.set_margin_start(10)
        bar.set_margin_end(10)
        bar.set_margin_top(8)
        bar.set_margin_bottom(6)

        if view is not None:
            b_zh = Gtk.Button(label="中文维基")
            b_en = Gtk.Button(label="English")
            b_br = Gtk.Button(label="用浏览器打开")
            b_zh.connect("clicked", lambda *_: view.load_uri(zh))
            b_en.connect("clicked", lambda *_: view.load_uri(en))
            b_br.connect("clicked", lambda *_: Gtk.show_uri_on_window(
                dlg, zh, Gtk.get_current_event_time()))
            for b in (b_zh, b_en, b_br):
                bar.pack_start(b, False, False, 0)
            area.pack_start(bar, False, False, 0)
            area.pack_start(view, True, True, 0)
            view.load_uri(zh)

            def _failed(_v, _ev, uri, err):
                self.win.toast("维基加载失败，可能没有网络")
                return False

            view.connect("load-failed", _failed)
        else:
            info = Gtk.Label(xalign=0)
            info.set_line_wrap(True)
            info.set_margin_start(18)
            info.set_margin_end(18)
            info.set_margin_top(18)
            info.set_text(
                "系统里没有 WebKitGTK，无法内嵌网页。\n\n"
                f"可以手动打开：\n{zh}\n\n"
                "安装内嵌组件：\nsudo apt install gir1.2-webkit2-4.1"
            )
            area.pack_start(info, True, True, 0)

        dlg.show_all()
        dlg.run()
        dlg.destroy()

    # ---------------- 点词弹气泡 ----------------
    def on_detail_press(self, tv, event):
        if event.button == 1:
            self._press_xy = (event.x, event.y)
        return False  # 不拦截，拖选照常

    def on_detail_release(self, tv, event):
        from gi.repository import Gdk, Gtk
        if event.button != 1:
            return False
        px, py = getattr(self, "_press_xy", (event.x, event.y))
        if abs(event.x - px) + abs(event.y - py) > 6:
            return False  # 移动超过 6px，视为拖选
        bx, by = tv.window_to_buffer_coords(Gtk.TextWindowType.WIDGET,
                                            int(event.x), int(event.y))
        hit, it = tv.get_iter_at_location(bx, by)
        if not hit:
            return False
        off = it.get_offset()
        for link in self._links:
            if link["start"] <= off < link["end"]:
                if link.get("kind") == "mcq":
                    self.open_mcq_dialog(link["payload"])
                    return True
                if link.get("kind") == "wiki":
                    self.open_wiki(link["payload"]["term"], link["payload"]["en_full"])
                    return True
                r = tv.get_iter_location(it)
                wx, wy = tv.buffer_to_window_coords(Gtk.TextWindowType.WIDGET, r.x, r.y)
                rect = Gdk.Rectangle()
                rect.x, rect.y = wx, wy
                rect.width, rect.height = max(r.width, 1), max(r.height, 1)
                self.pop_word(tv, rect, link)
                return True
        return False

    def pop_word(self, anchor, rect, link) -> bool:
        from gi.repository import Gtk

        old = self._popover
        if old is not None:
            try:
                old.popdown()
                old.destroy()
            except Exception:
                pass
            self._popover = None

        pop = Gtk.Popover()
        pop.set_relative_to(anchor)
        pop.set_pointing_to(rect)          # 指向具体那个词
        pop.set_position(Gtk.PositionType.BOTTOM)
        pop.set_modal(True)                # 点外面自动收起

        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        box.set_margin_start(10)
        box.set_margin_end(10)
        box.set_margin_top(8)
        box.set_margin_bottom(8)
        box.set_size_request(260, -1)

        head = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        wt = Gtk.Label(xalign=0)
        wt.set_markup(f"<span size='large' weight='bold'>{pango_esc(link['text'])}</span>")
        zt = Gtk.Label(xalign=0)
        zt.set_text(link["zh"])
        zt.get_style_context().add_class("muted")
        head.pack_start(wt, False, False, 0)
        head.pack_start(zt, False, False, 0)
        box.pack_start(head, False, False, 0)

        body = Gtk.Label(xalign=0)
        body.set_line_wrap(True)
        body.set_max_width_chars(32)
        body.set_text(link.get("note") or link["zh"])
        box.pack_start(body, False, False, 0)

        pop.add(box)
        box.show_all()
        self._popover = pop
        pop.connect("closed", lambda *_: setattr(self, "_popover", None))
        pop.popup()
        return True

class QuizPage:
    """答题：开始 → 作答 → 结果。"""

    def __init__(self, win):
        from gi.repository import Gtk

        self.win = win
        self.db = load_db()
        self.session: list[dict[str, Any]] = []
        self.index = 0
        self.correct = 0
        self.answered = 0
        self.current: dict[str, Any] | None = None
        self.revealed = False
        self.summary_mode = False

        self.box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        self.box.set_margin_start(24)
        self.box.set_margin_end(24)
        self.box.set_margin_top(20)
        self.box.set_margin_bottom(20)

        self.stack = Gtk.Stack()
        self.stack.set_transition_type(Gtk.StackTransitionType.CROSSFADE)
        self.box.pack_start(self.stack, True, True, 0)

        self.stack.add_named(self.build_start(), "start")
        self.stack.add_named(self.build_question(), "question")
        self.stack.add_named(self.build_result(), "result")
        self.stack.set_visible_child_name("start")

    # --- 开始页
    def build_start(self):
        from gi.repository import Gtk

        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=14)
        box.set_valign(Gtk.Align.CENTER)
        box.set_halign(Gtk.Align.CENTER)

        title = label("", True, xalign=0.5)
        title.set_markup("<span size='xx-large' weight='bold'>开始一组练习</span>")
        box.pack_start(title, False, False, 0)

        ok, total = overall(load_history())
        hint = label(
            f"历史：共 {total} 题，正确 {ok} 题" + (f"，正确率 {int(round(ok / total * 100))}%" if total else ""),
            False, xalign=0.5,
        )
        hint.get_style_context().add_class("muted")
        box.pack_start(hint, False, False, 0)

        # 题型
        kinds_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=14)
        kinds_box.set_halign(Gtk.Align.CENTER)
        self.kind_checks: dict[str, Any] = {}
        for k in TYPES:
            cb = Gtk.CheckButton(label=TYPE_LABEL[k])
            cb.set_active(True)
            if k == "relation" and not (self.db.get("mcqs") or []):
                cb.set_sensitive(False)
                cb.set_active(False)
            kinds_box.pack_start(cb, False, False, 0)
            self.kind_checks[k] = cb
        box.pack_start(kinds_box, False, False, 0)

        # 题量
        count_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        count_box.set_halign(Gtk.Align.CENTER)
        count_box.pack_start(label("题量", False), False, False, 0)
        self.count_combo = Gtk.ComboBoxText()
        for txt in ("10 题", "20 题", "30 题", "全部"):
            self.count_combo.append_text(txt)
        self.count_combo.set_active(0)
        count_box.pack_start(self.count_combo, False, False, 0)
        box.pack_start(count_box, False, False, 0)

        self.smart_check = Gtk.CheckButton(label="优先出我错得多的题")
        self.smart_check.set_active(True)
        self.smart_check.set_halign(Gtk.Align.CENTER)
        box.pack_start(self.smart_check, False, False, 0)

        start = Gtk.Button(label="开始答题")
        start.get_style_context().add_class("suggested-action")
        start.set_size_request(200, 44)
        start.set_halign(Gtk.Align.CENTER)
        start.connect("clicked", lambda *_: self.start_session())
        box.pack_start(start, False, False, 8)

        tip = label("答完会自动记录，可在「记录」页看正确率。", False, xalign=0.5)
        tip.get_style_context().add_class("muted")
        box.pack_start(tip, False, False, 0)
        return box

    # --- 答题页
    def build_question(self):
        from gi.repository import Gtk

        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=14)
        box.set_valign(Gtk.Align.START)

        top = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        self.progress_label = label("", False)
        self.progress_label.get_style_context().add_class("muted")
        top.pack_start(self.progress_label, True, True, 0)
        self.live_label = label("", True, xalign=1)
        self.live_label.get_style_context().add_class("muted")
        top.pack_end(self.live_label, False, False, 0)
        box.pack_start(top, False, False, 0)

        self.question_label = label("", True)
        self.question_label.get_style_context().add_class("question")
        box.pack_start(self.question_label, False, False, 0)

        self.input_area = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        box.pack_start(self.input_area, False, False, 0)

        btns = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        self.reveal_btn = Gtk.Button(label="不知道")
        self.reveal_btn.connect("clicked", lambda *_: self.do_submit(reveal=True))
        self.skip_btn = Gtk.Button(label="跳过")
        self.skip_btn.connect("clicked", lambda *_: self.next_question())
        self.submit_btn = Gtk.Button(label="提交")
        self.submit_btn.get_style_context().add_class("suggested-action")
        self.submit_btn.connect("clicked", self.on_submit_clicked)
        btns.pack_start(self.reveal_btn, False, False, 0)
        btns.pack_start(self.skip_btn, False, False, 0)
        btns.pack_end(self.submit_btn, False, False, 0)
        box.pack_start(btns, False, False, 0)

        self.entry: Any = None
        self.radios: list[Any] = []
        return box

    # --- 结果页
    def build_result(self):
        from gi.repository import Gtk

        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        box.set_valign(Gtk.Align.START)

        self.badge = Gtk.Label(xalign=0)
        box.pack_start(self.badge, False, False, 0)

        self.result_correct = label("", True)
        self.result_correct.get_style_context().add_class("answer")
        box.pack_start(self.result_correct, False, False, 0)

        self.result_yours = label("", True)
        self.result_yours.get_style_context().add_class("answer")
        box.pack_start(self.result_yours, False, False, 0)

        self.result_why = label("", False)
        self.result_why.get_style_context().add_class("muted")
        box.pack_start(self.result_why, False, False, 0)

        self.result_hist = label("", False)
        self.result_hist.get_style_context().add_class("muted")
        box.pack_start(self.result_hist, False, False, 0)

        self.next_btn = Gtk.Button(label="下一题")
        self.next_btn.get_style_context().add_class("suggested-action")
        self.next_btn.set_size_request(160, 40)
        self.next_btn.connect("clicked", lambda *_: self.next_question())
        box.pack_start(self.next_btn, False, False, 10)
        return box

    # --- 流程
    def start_session(self) -> None:
        kinds = {k for k, cb in self.kind_checks.items() if cb.get_active()}
        if not kinds:
            self.win.toast("至少选一种题型")
            return
        idx = self.count_combo.get_active()
        count = {0: 10, 1: 20, 2: 30, 3: 0}.get(idx, 10)
        self.session = build_session(self.db, kinds, count, self.smart_check.get_active())
        if not self.session:
            self.win.toast("题库是空的")
            return
        self.index = 0
        self.correct = 0
        self.answered = 0
        self.summary_mode = False
        self.reveal_btn.show()
        self.skip_btn.show()
        self.submit_btn.set_label("提交")
        self.show_question()

    def show_question(self) -> None:
        from gi.repository import Gtk

        if self.index >= len(self.session):
            self.show_summary()
            return
        self.current = self.session[self.index]
        self.revealed = False
        item = self.current

        self.progress_label.set_text(f"第 {self.index + 1} / {len(self.session)} 题")
        live = f"已答 {self.answered}"
        if self.answered:
            live += f" · 正确率 {int(round(self.correct / self.answered * 100))}%"
        self.live_label.set_markup(f"<span size='small'>{pango_esc(live)}</span>")

        for c in self.input_area.get_children():
            self.input_area.remove(c)
        self.entry = None
        self.radios = []

        if item["mode"] == "mcq":
            q = item["q"]
            self.question_label.set_markup(
                f"<b>{pango_esc(q['prompt'])}</b>\n<span size='small'>（四选一）</span>"
            )
            choices = list(q["choices"])
            random.shuffle(choices)
            group = None
            for c in choices:
                rb = Gtk.RadioButton.new_with_label_from_widget(group, c)
                if group is None:
                    group = rb
                self.input_area.pack_start(rb, False, False, 0)
                self.radios.append(rb)
            self.radios[0].set_active(True)
        else:
            w = item["word"]
            kind = item["kind"]
            if kind == "pronounce":
                self.question_label.set_markup(
                    f"<b>「{pango_esc(w['term'])}」</b>的英文全称，哪个音标更合适？\n"
                    "<span size='small'>（四选一）</span>"
                )
                choices = list(w["pronounce_choices"])
                random.shuffle(choices)
                group = None
                for c in choices:
                    rb = Gtk.RadioButton.new_with_label_from_widget(group, c)
                    if group is None:
                        group = rb
                    self.input_area.pack_start(rb, False, False, 0)
                    self.radios.append(rb)
                self.radios[0].set_active(True)
            else:
                self.question_label.set_markup(
                    f"<b>「{pango_esc(w['term'])}」</b> · {TYPE_LABEL[kind]}\n"
                    "<span size='small'>用自己的话写，意思对就算</span>"
                )
                self.entry = Gtk.Entry()
                self.entry.set_placeholder_text("输入答案后回车")
                self.entry.connect("activate", lambda *_: self.do_submit())
                self.input_area.pack_start(self.entry, False, False, 0)

        self.input_area.show_all()
        self.stack.set_visible_child_name("question")
        if self.entry is not None:
            self.entry.grab_focus()

    def on_submit_clicked(self, *_args) -> None:
        if self.summary_mode:
            self.back_to_start()
        else:
            self.do_submit()

    def _current_answer(self) -> str:
        if self.radios:
            for rb in self.radios:
                if rb.get_active():
                    return rb.get_label()
            return ""
        if self.entry is not None:
            return self.entry.get_text()
        return ""

    def _expected(self, item: dict[str, Any]) -> str:
        if item["mode"] == "mcq":
            return item["q"]["choices"][0]
        w = item["word"]
        if item["kind"] == "en_full":
            return w["en_full"]
        if item["kind"] == "zh":
            return w["zh"]
        return w["pronounce_choices"][0]

    def do_submit(self, reveal: bool = False) -> None:
        from gi.repository import Gtk

        item = self.current
        if not item:
            return
        answer = "" if reveal else self._current_answer().strip()
        expected = self._expected(item)

        if not reveal and not answer:
            self.win.toast("还没写答案")
            return

        engine = "查看答案" if reveal else "四选一对照"
        ok = False
        why = ""

        if reveal:
            ok = False
        elif item["mode"] == "mcq":
            ok = answer == item["q"]["choices"][0]
            engine = "四选一对照"
            why = item["q"].get("explain", "")
        elif item["kind"] == "pronounce":
            ok = answer == item["word"]["pronounce_choices"][0]
            if not ok:
                accepts = {normalize(x) for x in item["word"].get("pronounce_accept", [])}
                if normalize(answer) in accepts:
                    ok, engine = True, "可接受读法"
            why = f"标准读法：{item['word'].get('pronounce', '')}"
        else:
            ok, why, engine = grade(item["kind"], item["word"], answer)

        term = item["word"]["term"] if item["mode"] == "term" else "板卡关系"
        pct = align_markup(expected, answer)[2] if item["mode"] == "term" and item["kind"] in ("en_full", "zh") and not reveal else (100 if ok else 0)

        append_history({
            "ts": datetime.now(TZ).isoformat(timespec="seconds"),
            "term": term,
            "kind": item["kind"],
            "answer": answer,
            "ok": ok,
            "engine": engine,
            "pct": pct,
            "reveal": reveal,
        })

        self.answered += 1
        if ok:
            self.correct += 1

        self.show_result(item, ok, answer, expected, why, reveal, term, pct)

    def show_result(self, item, ok, answer, expected, why, reveal, term, pct) -> None:
        from gi.repository import Gtk

        ctx = self.badge.get_style_context()
        for c in ("badge-ok", "badge-bad", "badge-neutral"):
            ctx.remove_class(c)
        if reveal:
            ctx.add_class("badge-neutral")
            self.badge.set_text("看答案")
        elif ok:
            ctx.add_class("badge-ok")
            self.badge.set_text("通过")
        else:
            ctx.add_class("badge-bad")
            self.badge.set_text("再记一下")

        if item["mode"] == "term" and item["kind"] in ("en_full", "zh") and not reveal:
            correct_mk, given_mk, p = align_markup(expected, answer)
            self.result_correct.set_markup(f"<b>正确：</b>{correct_mk}    <span size='small'>（{p}%）</span>")
            self.result_yours.set_markup(f"<b>你的：</b>{given_mk}")
        else:
            self.result_correct.set_markup(f"<b>正确：</b>{pango_esc(expected)}")
            self.result_yours.set_markup(f"<b>你的：</b>{pango_esc(answer) if answer else '（未作答）'}")

        self.result_why.set_text(why or "")

        ok_n, total = 0, 0
        for r in load_history():
            if r.get("term") == term:
                total += 1
                if r.get("ok"):
                    ok_n += 1
        if total:
            self.result_hist.set_text(f"「{term}」累计 {ok_n}/{total}，正确率 {int(round(ok_n / total * 100))}%")

        self.next_btn.set_label("看总结" if self.index + 1 >= len(self.session) else "下一题")
        self.stack.set_visible_child_name("result")
        self.next_btn.grab_focus()

    def next_question(self) -> None:
        self.index += 1
        if self.index >= len(self.session):
            self.show_summary()
        else:
            self.show_question()

    def show_summary(self) -> None:
        from gi.repository import Gtk

        for c in self.input_area.get_children():
            self.input_area.remove(c)
        self.entry = None
        self.radios = []

        pct = int(round(self.correct / self.answered * 100)) if self.answered else 0
        self.progress_label.set_text("本组结束")
        self.live_label.set_markup("")
        self.question_label.set_markup(
            f"<span size='xx-large' weight='bold'>{pct}%</span>\n"
            f"<span size='large'>答对 {self.correct} / {self.answered} 题</span>"
        )
        self.reveal_btn.hide()
        self.skip_btn.hide()
        self.submit_btn.set_label("再来一组")
        self.summary_mode = True
        self.stack.set_visible_child_name("question")
        self.win.refresh_stats()

    def back_to_start(self) -> None:
        self.summary_mode = False
        self.reveal_btn.show()
        self.skip_btn.show()
        self.submit_btn.set_label("提交")
        self.stack.set_visible_child_name("start")


class StatsPage:
    """记录：总览 + 分题型 + 分术语 + 最近记录。"""

    def __init__(self, win):
        from gi.repository import Gtk

        self.win = win
        sw = Gtk.ScrolledWindow()
        sw.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        self.box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=16)
        self.box.set_margin_start(24)
        self.box.set_margin_end(24)
        self.box.set_margin_top(20)
        self.box.set_margin_bottom(20)
        sw.add(self.box)
        self.widget = sw
        self.refresh()

    def _clear(self) -> None:
        for c in self.box.get_children():
            self.box.remove(c)

    def refresh(self) -> None:
        from gi.repository import Gtk

        self._clear()
        history = load_history()
        ok, total = overall(history)

        head = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        t = label("", True)
        t.set_markup("<span size='xx-large' weight='bold'>答题记录</span>")
        head.pack_start(t, True, True, 0)
        refresh_btn = Gtk.Button(label="刷新")
        refresh_btn.connect("clicked", lambda *_: self.refresh())
        head.pack_end(refresh_btn, False, False, 0)
        self.box.pack_start(head, False, False, 0)

        if not total:
            self.box.pack_start(label("还没有记录。去「答题」页做一组。", False), False, False, 0)
            self.box.show_all()
            return

        # 总览
        cards = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        for title, value in (
            ("总题数", str(total)),
            ("答对", str(ok)),
            ("正确率", f"{int(round(ok / total * 100))}%"),
        ):
            card = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
            card.get_style_context().add_class("card")
            v = label("", True)
            v.set_markup(f"<span size='x-large' weight='bold'>{pango_esc(value)}</span>")
            card.pack_start(v, False, False, 0)
            k = label(title, False)
            k.get_style_context().add_class("muted")
            card.pack_start(k, False, False, 0)
            cards.pack_start(card, True, True, 0)
        self.box.pack_start(cards, False, False, 0)

        # 分题型
        self.box.pack_start(self._section_title("按题型"), False, False, 0)
        for name, o, n in sorted(accuracy_rows(history, "kind"), key=lambda x: -x[2]):
            self.box.pack_start(self._bar_row(TYPE_LABEL.get(name, name), o, n), False, False, 0)

        # 分术语
        self.box.pack_start(self._section_title("按术语（弱的在前）"), False, False, 0)
        for name, o, n in accuracy_rows(history, "term")[:12]:
            self.box.pack_start(self._bar_row(name, o, n), False, False, 0)

        # 最近记录
        self.box.pack_start(self._section_title("最近 30 条"), False, False, 0)
        store = Gtk.ListStore(str, str, str, str)
        for r in reversed(history[-30:]):
            ts = r.get("ts", "")
            try:
                ts = datetime.fromisoformat(ts).strftime("%m-%d %H:%M")
            except Exception:
                pass
            store.append([
                ts,
                r.get("term", ""),
                TYPE_LABEL.get(r.get("kind", ""), r.get("kind", "")),
                "✔" if r.get("ok") else ("看答案" if r.get("reveal") else "✘"),
            ])
        view = Gtk.TreeView(model=store)
        for i, name in enumerate(("时间", "术语", "题型", "结果")):
            renderer = Gtk.CellRendererText()
            col = Gtk.TreeViewColumn(name, renderer, text=i)
            col.set_resizable(True)
            view.append_column(col)
        self.box.pack_start(view, False, False, 0)

        self.box.show_all()

    def _section_title(self, text: str):
        lb = label("", True)
        lb.set_markup(f"<span weight='bold'>{pango_esc(text)}</span>")
        lb.set_margin_top(8)
        return lb

    def _bar_row(self, name: str, ok: int, total: int):
        from gi.repository import Gtk

        row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        n = label(name, False)
        n.set_size_request(150, -1)
        n.set_ellipsize(3)
        row.pack_start(n, False, False, 0)
        bar = Gtk.LevelBar()
        bar.set_min_value(0)
        bar.set_max_value(1)
        bar.set_value(ok / total if total else 0)
        bar.set_valign(Gtk.Align.CENTER)
        row.pack_start(bar, True, True, 0)
        pct = int(round(ok / total * 100)) if total else 0
        v = label("", True, xalign=1)
        v.set_markup(f"<span size='small'>{pct}% ({ok}/{total})</span>")
        v.set_size_request(110, -1)
        row.pack_end(v, False, False, 0)
        return row


class MainWindow:
    def __init__(self, app):
        from gi.repository import Gtk

        self.gtk = Gtk
        self.window = Gtk.ApplicationWindow(application=app, title=APP_NAME)
        self.window.set_default_size(1040, 720)
        self.window.set_border_width(0)

        header = Gtk.HeaderBar()
        header.set_show_close_button(True)
        header.props.title = APP_NAME
        header.props.subtitle = "题库 · 答题 · 记录"
        self.window.set_titlebar(header)

        self.toast_label = Gtk.Label(label="")
        header.pack_end(self.toast_label)

        self.stack = Gtk.Stack()
        self.stack.set_transition_type(Gtk.StackTransitionType.SLIDE_LEFT_RIGHT)
        self.stack.set_transition_duration(160)

        # 自定义导航栏：图标 + 文字
        sidebar = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        sidebar.set_size_request(170, -1)
        nav = Gtk.ListBox()
        nav.get_style_context().add_class("navigation-sidebar")
        nav.set_selection_mode(Gtk.SelectionMode.SINGLE)
        self._nav_rows = {}
        self._syncing_nav = False
        for page, title, icon in (
            ("library", "词条", "view-list-symbolic"),
            ("quiz", "答题", "dialog-question-symbolic"),
            ("stats", "记录", "utilities-system-monitor-symbolic"),
        ):
            row = Gtk.ListBoxRow()
            row.page_name = page
            hb = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
            hb.set_margin_start(12)
            hb.set_margin_end(12)
            hb.set_margin_top(9)
            hb.set_margin_bottom(9)
            img = Gtk.Image.new_from_icon_name(icon, Gtk.IconSize.BUTTON)
            lb = Gtk.Label(label=title, xalign=0)
            hb.pack_start(img, False, False, 0)
            hb.pack_start(lb, True, True, 0)
            row.add(hb)
            nav.add(row)
            self._nav_rows[page] = row
        sidebar.pack_start(nav, False, False, 0)
        self._nav = nav
        nav.connect("row-selected", self._on_nav_selected)
        self.stack.connect("notify::visible-child", self._on_stack_changed)

        self.library = LibraryPage(self)
        self.quiz = QuizPage(self)
        self.stats = StatsPage(self)

        self.stack.add_titled(self.library.box, "library", "词条")
        self.stack.add_titled(self.quiz.box, "quiz", "答题")
        self.stack.add_titled(self.stats.widget, "stats", "记录")
        self._nav.select_row(self._nav_rows["library"])

        root = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=0)
        root.pack_start(sidebar, False, False, 0)
        root.pack_start(Gtk.Separator(orientation=Gtk.Orientation.VERTICAL), False, False, 0)
        root.pack_start(self.stack, True, True, 0)
        self.window.add(root)

        self._toast_timeout = None

    def _on_nav_selected(self, _lb, row) -> None:
        if row is None or self._syncing_nav:
            return
        self._syncing_nav = True
        self.stack.set_visible_child_name(row.page_name)
        self._syncing_nav = False

    def _on_stack_changed(self, stack, _pspec) -> None:
        if self._syncing_nav:
            return
        row = self._nav_rows.get(stack.get_visible_child_name())
        if row is not None:
            self._syncing_nav = True
            self._nav.select_row(row)
            self._syncing_nav = False

    def show_all(self) -> None:
        self.window.show_all()

    def toast(self, text: str) -> None:
        from gi.repository import GLib
        self.toast_label.set_text(text)
        if self._toast_timeout:
            GLib.source_remove(self._toast_timeout)
        self._toast_timeout = GLib.timeout_add(2500, self._clear_toast)

    def _clear_toast(self) -> bool:
        self.toast_label.set_text("")
        self._toast_timeout = None
        return False

    def refresh_stats(self) -> None:
        self.stats.refresh()


class App:
    """薄封装，避免子类化 Gtk.Application 时的信号绑定问题。"""

    def __init__(self, smoke: bool = False):
        import gi

        gi.require_version("Gtk", "3.0")
        gi.require_version("Gdk", "3.0")
        from gi.repository import Gio, GLib, Gtk

        self.GLib = GLib
        self.smoke = smoke
        self.app = Gtk.Application(application_id=APP_ID, flags=Gio.ApplicationFlags.FLAGS_NONE)
        self.app.connect("activate", self.on_activate)

    def on_activate(self, app) -> None:
        import traceback

        try:
            existing = getattr(self, "win", None)
            if existing is not None:
                existing.window.present()
                log("second activate: present existing window")
                return
            log("activate: building window")
            try:
                from gi.repository import Gdk
                Gdk.set_program_class("io.github.termquiz")
            except Exception:
                pass
            try:
                from gi.repository import Gtk as _Gtk
                _Gtk.Window.set_default_icon_name("accessories-dictionary")
            except Exception:
                pass
            install_css()
            self.win = MainWindow(app)
            self.win.show_all()
            self.win.window.present()
            log("activate: window shown")
        except Exception:
            log("activate FAILED:\n" + traceback.format_exc())
            raise
        if self.smoke:
            self.GLib.timeout_add(400, lambda: (app.quit(), False)[1])

    def run(self) -> int:
        return self.app.run([sys.argv[0]])


# ---------------------------------------------------------------- 命令

def run_terminal_quiz() -> int:
    db = load_db()
    item = random.choice(build_pool(db, set(TYPES)) or [{}])
    if not item:
        print("题库是空的")
        return 1
    print(json.dumps(item, ensure_ascii=False, indent=2)[:800])
    return 0


def cmd_add(term: str, en_full: str, zh: str, pronounce: str = "") -> None:
    db = load_db()
    db.setdefault("words", [])
    db["words"].append({
        "term": term.strip(),
        "en_full": en_full.strip(),
        "en_aliases": [en_full.strip().lower()],
        "zh": zh.strip(),
        "zh_aliases": [zh.strip()],
        "pronounce": pronounce.strip() or en_full.strip(),
        "pronounce_accept": [pronounce.strip().lower()] if pronounce else [],
        "pronounce_choices": [
            pronounce.strip() or en_full.strip(),
            "（占位干扰项，请编辑 words.json）",
            "operations",
            "point of contact",
        ],
    })
    save_db(db)
    print("已写入", words_path())


def cmd_install() -> None:
    desktop_dir = Path.home() / ".local/share/applications"
    desktop_dir.mkdir(parents=True, exist_ok=True)
    entry = desktop_dir / "term-quiz.desktop"
    entry.write_text(
        f"""[Desktop Entry]
Type=Application
Name={APP_NAME}
Comment=术语题库与练习
Exec={sys.executable} {ROOT / 'term_quiz.py'}
Terminal=false
Categories=Education;
""",
        encoding="utf-8",
    )
    entry.chmod(0o755)
    print("已安装启动项：", entry)

    # 关掉旧的通知定时器
    subprocess.run(["systemctl", "--user", "disable", "--now", "term-quiz.timer"], check=False)
    old_unit = Path.home() / ".config/systemd/user/term-quiz.timer"
    if old_unit.exists():
        old_unit.unlink()
        print("已移除旧的 term-quiz.timer")
    print("不再有通知。直接从应用菜单打开「术语训练」即可。")


def main() -> int:
    log(f"main argv={sys.argv}")
    args = [a for a in sys.argv[1:]]
    smoke = "--smoke" in args
    args = [a for a in args if a != "--smoke"]
    cmd = args[0] if args else "gui"

    if smoke or cmd == "gui":
        return App(smoke=smoke).run()
    if cmd == "quiz":
        return run_terminal_quiz()
    if cmd == "install":
        cmd_install()
        return 0
    if cmd == "add" and len(args) >= 4:
        cmd_add(args[1], args[2], args[3], args[4] if len(args) > 4 else "")
        return 0
    print(__doc__)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
