#!/usr/bin/env python3
"""术语训练 · 桌面版 v1.1.0

三页：题库 / 答题 / 记录。本地运行，无通知。
新增：英文全称逐词翻译、增删改术语、排序筛选、单词练习、最近练习时间。
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

APP_ID = "io.github.termquiz"
APP_NAME = "术语训练"
VERSION = "1.1.0"
LOG_PATH = USER_DIR / "app.log"

TYPES = ("en_full", "zh", "pronounce", "relation")
TYPE_LABEL = {
    "en_full": "英文全称",
    "zh": "中文意思",
    "pronounce": "读音",
    "relation": "板卡关系",
}
TYPE_FULL = {
    "en_full": "写出英文全称",
    "zh": "写出中文意思",
    "pronounce": "选出正确读法",
    "relation": "板卡关系四选一",
}

# 拆词用的迷你词表：查不到就跳过，不追求精确
GLOSSARY = {
    "open": "开放的", "pluggable": "可插拔的", "specification": "规范", "spec": "规范",
    "proof": "验证", "of": "的", "concept": "概念",
    "smart": "智能的", "mobility": "移动性", "architecture": "架构",
    "baseband": "基带", "processor": "处理器", "board": "板", "module": "模组",
    "display": "显示", "screen": "屏幕", "interface": "接口", "universal": "通用",
    "serial": "串行", "bus": "总线", "power": "电源", "key": "按键", "reset": "复位",
    "audio": "音频", "video": "视频", "wireless": "无线", "network": "网络",
    "memory": "存储", "storage": "存储", "flash": "闪存", "camera": "摄像头",
    "sensor": "传感器", "battery": "电池", "charging": "充电", "thermal": "散热",
    "debug": "调试", "boot": "启动", "kernel": "内核", "driver": "驱动",
    "system": "系统", "service": "服务", "service's": "服务", "manager": "管理器",
    "protocol": "协议", "device": "设备", "application": "应用", "platform": "平台",
    "graphics": "图形", "image": "图像", "signal": "信号", "processing": "处理",
    "digital": "数字", "analog": "模拟", "input": "输入", "output": "输出",
    "channel": "通道", "control": "控制", "unit": "单元", "test": "测试",
    "high": "高速", "definition": "清晰度", "multimedia": "多媒体",
    "trusted": "可信", "execution": "执行", "environment": "环境",
}


def log(msg: str) -> None:
    try:
        LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
        with LOG_PATH.open("a", encoding="utf-8") as f:
            f.write(f"{datetime.now(TZ).isoformat(timespec='seconds')}  {msg}\n")
    except Exception:
        pass


def words_path() -> Path:
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


# ---------------------------------------------------------------- 拆词翻译

def split_phrase(text: str) -> list[str]:
    """把全称切成词/短语，保留 - 连接的组合词。"""
    text = (text or "").strip()
    if not text:
        return []
    parts = re.split(r"\s+", text)
    return [p for p in parts if p]


def breakdown(word: dict[str, Any]) -> list[tuple[str, str]]:
    manual = word.get("breakdown")
    if manual:
        out = []
        for item in manual:
            if isinstance(item, (list, tuple)) and len(item) >= 2:
                out.append((str(item[0]), str(item[1])))
            elif isinstance(item, dict):
                out.append((str(item.get("en", "")), str(item.get("zh", ""))))
        return [x for x in out if x[0]]

    result = []
    for token in split_phrase(word.get("en_full", "")):
        key = re.sub(r"[^a-zA-Z\-']", "", token).lower()
        zh = GLOSSARY.get(key)
        if not zh and "-" in key:
            pieces = [GLOSSARY.get(p) for p in key.split("-")]
            if all(pieces):
                zh = "".join(pieces)
        if zh:
            result.append((token, zh))
    return result


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
        t for t in re.split(r"[\s\-]+", normalize(text))
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
    prompt = (
        "你在批改工程师的术语小测。只回复一行中文：先写「通过」或「不通过」，再写一句理由。\n"
        "意思对、读音接近、全称差一两个虚词都算通过。不要太严。\n"
        f"术语: {word['term']}\n题型: {TYPE_FULL[kind]}\n"
        f"参考英文全称: {word['en_full']}\n参考中文: {word['zh']}\n"
        f"参考读法: {word.get('pronounce', '')}\n学员答案: {answer}\n"
    )
    try:
        proc = subprocess.run(
            ["curl", "-sS", "-m", "8", "http://127.0.0.1:11434/api/generate",
             "-H", "Content-Type: application/json",
             "-d", json.dumps({"model": os.environ.get("TERM_QUIZ_OLLAMA_MODEL", "qwen2.5:7b"),
                               "prompt": prompt, "stream": False,
                               "options": {"temperature": 0.1}})],
            capture_output=True, text=True, timeout=10,
        )
        if proc.returncode != 0 or not proc.stdout.strip():
            return None
        text = (json.loads(proc.stdout).get("response") or "").strip()
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

def term_stats(history: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    for r in history:
        name = r.get("term") or "?"
        item = out.setdefault(name, {"ok": 0, "total": 0, "last": ""})
        item["total"] += 1
        if r.get("ok"):
            item["ok"] += 1
        ts = r.get("ts") or ""
        if ts > item["last"]:
            item["last"] = ts
    return out


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
    total: Counter[tuple[str, str]] = Counter()
    ok: Counter[tuple[str, str]] = Counter()
    for r in history:
        key = (r.get("term") or "?", r.get("kind") or "?")
        total[key] += 1
        if r.get("ok"):
            ok[key] += 1
    return {k: 1.0 + (1.0 - ok[k] / n) * 2.0 for k, n in total.items() if n}


# ---------------------------------------------------------------- 出题

def build_pool(db: dict[str, Any], kinds: set[str], only_term: str | None = None) -> list[dict[str, Any]]:
    pool: list[dict[str, Any]] = []
    for w in db.get("words") or []:
        if only_term and w["term"] != only_term:
            continue
        for k in ("en_full", "zh", "pronounce"):
            if k not in kinds:
                continue
            if k == "pronounce" and not w.get("pronounce_choices"):
                continue
            pool.append({"mode": "term", "word": w, "kind": k})
    if "relation" in kinds and not only_term:
        for m in db.get("mcqs") or []:
            pool.append({"mode": "mcq", "q": m, "kind": "relation"})
    return pool


def shuffle_weighted(pool, weights):
    keyed = []
    for item in pool:
        name = item["word"]["term"] if item["mode"] == "term" else "板卡关系"
        w = weights.get((name, item["kind"]), 1.0)
        u = random.random() or 1e-9
        keyed.append((u ** (1.0 / max(w, 1e-9)), item))
    keyed.sort(key=lambda x: -x[0])
    return [i for _, i in keyed]


def build_session(db, kinds, count, smart, only_term=None):
    pool = build_pool(db, kinds, only_term)
    if not pool:
        return []
    weights = smart_weights(load_history()) if smart else {}
    ordered = shuffle_weighted(pool, weights)
    if count <= 0 or count >= len(ordered):
        return ordered
    return ordered[:count]


# ---------------------------------------------------------------- 通用 UI

def pango_esc(text: str) -> str:
    return (text or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _span(color: str, text: str) -> str:
    if not text:
        return ""
    return f'<span foreground="{color}">{pango_esc(text)}</span>'


def align_markup(correct: str, given: str) -> tuple[str, str, int]:
    a, b = correct or "", given or ""
    green, red = "#1b8a3a", "#d32f2f"
    ca, cb = [], []
    sm = SequenceMatcher(a=a.lower(), b=b.lower())
    for tag, i1, i2, j1, j2 in sm.get_opcodes():
        if tag == "equal":
            ca.append(_span(green, a[i1:i2])); cb.append(_span(green, b[j1:j2]))
        elif tag == "replace":
            ca.append(_span(red, a[i1:i2])); cb.append(_span(red, b[j1:j2]))
        elif tag == "delete":
            ca.append(_span(red, a[i1:i2]))
        elif tag == "insert":
            cb.append(_span(red, b[j1:j2]))
    return ("".join(ca) or _span(red, "（空）"),
            "".join(cb) or _span(red, "（空）"),
            int(round(sm.ratio() * 100)))


CSS = """
.nav { background-color: alpha(currentColor, 0.035); }
.nav row { border-radius: 9px; margin: 2px 8px; }
.nav row:selected { background-color: @theme_selected_bg_color; }
.nav row:selected label { color: #ffffff; }
.card { background-color: alpha(currentColor, 0.05); border-radius: 10px; padding: 12px 16px; }
.card-title { font-size: 11px; font-weight: 700; opacity: 0.62; }
.term-title { font-size: 30px; font-weight: 800; }
.row-term { font-size: 15px; font-weight: 700; }
.row-sub { font-size: 12px; opacity: 0.62; }
.chip { background-color: alpha(currentColor, 0.10); border-radius: 999px;
        padding: 2px 10px; font-size: 12px; }
.chip-good { background-color: #2e7d32; color: #ffffff; }
.chip-bad { background-color: #b3261e; color: #ffffff; }
.mono { font-family: "DejaVu Sans", "Noto Sans", sans-serif; }
.badge-ok { background-color: #2e7d32; color: #ffffff; border-radius: 8px;
            padding: 5px 14px; font-weight: 700; }
.badge-bad { background-color: #b3261e; color: #ffffff; border-radius: 8px;
             padding: 5px 14px; font-weight: 700; }
.badge-neutral { background-color: alpha(currentColor, 0.14); border-radius: 8px;
                 padding: 5px 14px; font-weight: 700; }
.q-text { font-size: 18px; }
"""


def install_css() -> None:
    import gi
    gi.require_version("Gtk", "3.0")
    gi.require_version("Gdk", "3.0")
    from gi.repository import Gdk, Gtk
    p = Gtk.CssProvider()
    p.load_from_data(CSS.encode("utf-8"))
    screen = Gdk.Screen.get_default()
    if screen is not None:
        Gtk.StyleContext.add_provider_for_screen(screen, p, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)


def L(text: str = "", markup: bool = False, cls: str = "", wrap: bool = True,
      selectable: bool = False, xalign: float = 0.0):
    from gi.repository import Gtk
    lb = Gtk.Label(xalign=xalign, yalign=0.5)
    lb.set_line_wrap(wrap)
    lb.set_selectable(selectable)
    if markup:
        lb.set_markup(text)
    else:
        lb.set_text(text)
    if cls:
        for c in cls.split():
            lb.get_style_context().add_class(c)
    return lb


def M(markup: str, **kw):
    """带 markup 的 label，省得每次写两行。"""
    return L(markup, markup=True, **kw)


def spacer(h: int = 6):
    from gi.repository import Gtk
    b = Gtk.Box()
    b.set_size_request(-1, h)
    return b


def card(title: str, children, spacing: int = 8):
    from gi.repository import Gtk
    box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=spacing)
    box.get_style_context().add_class("card")
    if title:
        box.pack_start(L(title, cls="card-title"), False, False, 0)
    for c in children:
        box.pack_start(c, False, False, 0)
    return box


def fmt_ts(ts: str) -> str:
    try:
        d = datetime.fromisoformat(ts)
        return d.strftime("%m-%d %H:%M")
    except Exception:
        return ""


# ---------------------------------------------------------------- 题库页

class LibraryPage:
    def __init__(self, win):
        from gi.repository import Gtk
        self.win = win
        self.db = load_db()
        self.history = load_history()
        self.current_index: int | None = None

        self.box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=0)

        # ---- 左：搜索 + 排序 + 列表
        left = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        left.set_size_request(340, -1)

        head = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        head.set_margin_start(16); head.set_margin_end(16)
        head.set_margin_top(14); head.set_margin_bottom(10)
        self.search = Gtk.SearchEntry()
        self.search.set_placeholder_text("搜术语 / 全称 / 中文")
        self.search.connect("search-changed", lambda *_: self.refresh_list())
        head.pack_start(self.search, True, True, 0)

        add_btn = Gtk.Button()
        add_btn.set_image(Gtk.Image.new_from_icon_name("list-add-symbolic", Gtk.IconSize.BUTTON))
        add_btn.set_tooltip_text("新增术语")
        add_btn.connect("clicked", lambda *_: self.add_term())
        head.pack_start(add_btn, False, False, 0)

        sort_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        sort_row.set_margin_start(16); sort_row.set_margin_end(16)
        sort_row.set_margin_bottom(8)
        self.sort_combo = Gtk.ComboBoxText()
        for t in ("字母序", "正确率低优先", "最近练习", "练习次数多"):
            self.sort_combo.append_text(t)
        self.sort_combo.set_active(0)
        self.sort_combo.connect("changed", lambda *_: self.refresh_list())
        sort_row.pack_start(L("排序", cls="row-sub"), False, False, 0)
        sort_row.pack_start(self.sort_combo, False, False, 0)
        left.pack_start(head, False, False, 0)
        left.pack_start(sort_row, False, False, 0)

        self.list = Gtk.ListBox()
        self.list.set_selection_mode(Gtk.SelectionMode.SINGLE)
        self.list.connect("row-selected", self.on_select)
        sw = Gtk.ScrolledWindow()
        sw.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        sw.add(self.list)
        left.pack_start(sw, True, True, 0)

        foot = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL)
        foot.set_margin_start(16); foot.set_margin_end(16)
        foot.set_margin_top(8); foot.set_margin_bottom(10)
        self.count_label = L("", cls="row-sub")
        foot.pack_start(self.count_label, True, True, 0)
        left.pack_start(Gtk.Separator(orientation=Gtk.Orientation.HORIZONTAL), False, False, 0)
        left.pack_start(foot, False, False, 0)

        # ---- 右：详情
        self.detail_holder = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        self.detail_holder.set_margin_start(28)
        self.detail_holder.set_margin_end(28)
        self.detail_holder.set_margin_top(20)
        self.detail_holder.set_margin_bottom(20)
        self.detail_holder.set_halign(Gtk.Align.START)
        self.detail_holder.set_size_request(720, -1)

        right_scroll = Gtk.ScrolledWindow()
        right_scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        right_scroll.add(self.detail_holder)

        self.box.pack_start(left, False, False, 0)
        self.box.pack_start(Gtk.Separator(orientation=Gtk.Orientation.VERTICAL), False, False, 0)
        self.box.pack_start(right_scroll, True, True, 0)

        self.refresh_list()

    # ---------------- 列表
    def _sort_key(self):
        mode = self.sort_combo.get_active()
        stats = term_stats(self.history)
        if mode == 1:
            return lambda w: (stats.get(w["term"], {}).get("ok", 0) /
                              max(stats.get(w["term"], {}).get("total", 0), 1),
                              w["term"])
        if mode == 2:
            return lambda w: (-_ts_value(stats.get(w["term"], {}).get("last", "")), w["term"])
        if mode == 3:
            return lambda w: (-stats.get(w["term"], {}).get("total", 0), w["term"])
        return lambda w: w["term"].lower()

    def refresh_list(self) -> None:
        from gi.repository import Gtk
        self.history = load_history()
        for row in self.list.get_children():
            self.list.remove(row)

        q = normalize(self.search.get_text())
        stats = term_stats(self.history)
        words = list(self.db.get("words") or [])
        words.sort(key=self._sort_key())

        shown = 0
        for w in words:
            hay = normalize(f"{w['term']} {w.get('en_full','')} {w.get('zh','')}")
            if q and q not in hay:
                continue
            idx = self.db["words"].index(w)
            row = Gtk.ListBoxRow()
            row.term_index = idx

            inner = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
            inner.set_margin_start(10); inner.set_margin_end(10)
            inner.set_margin_top(9); inner.set_margin_bottom(9)

            col = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
            col.pack_start(_titled(w["term"]), False, False, 0)
            sub = L(w.get("en_full", ""), cls="row-sub", wrap=False)
            sub.set_ellipsize(3)
            col.pack_start(sub, False, False, 0)
            inner.pack_start(col, True, True, 0)

            st = stats.get(w["term"])
            chip_text = f"{st['ok']}/{st['total']} 正确" if st else "未练习"
            chip = L(chip_text, cls="chip row-sub", wrap=False)
            chip.set_valign(0.5)
            inner.pack_end(chip, False, False, 0)

            row.add(inner)
            self.list.add(row)
            shown += 1

        self.count_label.set_text(f"{shown} / {len(words)} 个术语")
        if shown:
            rows = self.list.get_children()
            keep = None
            if self.current_index is not None:
                for r in rows:
                    if r.term_index == self.current_index:
                        keep = r
                        break
            self.list.select_row(keep or rows[0])
        else:
            self.show_empty()

    def show_empty(self) -> None:
        for c in self.detail_holder.get_children():
            self.detail_holder.remove(c)
        self.detail_holder.pack_start(L("没有匹配的术语。", cls="row-sub"), False, False, 0)
        self.detail_holder.show_all()

    def on_select(self, _lb, row) -> None:
        if row is None:
            return
        self.current_index = row.term_index
        self.show_detail(self.db["words"][row.term_index])

    # ---------------- 详情
    def show_detail(self, w: dict[str, Any]) -> None:
        from gi.repository import Gtk
        for c in self.detail_holder.get_children():
            self.detail_holder.remove(c)

        st = term_stats(self.history).get(w["term"])
        top = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        top.pack_start(L(w["term"], markup=True, cls="term-title", wrap=False), False, False, 0)
        if st:
            pct = int(round(st["ok"] / st["total"] * 100))
            cls = "chip chip-good" if pct >= 80 else ("chip chip-bad" if pct < 50 else "chip")
            chip = L(f"{st['ok']}/{st['total']} · {pct}%", cls=cls, wrap=False)
            chip.set_valign(0.5)
            top.pack_start(chip, False, False, 0)
        else:
            chip = L("未练习", cls="chip", wrap=False)
            chip.set_valign(0.5)
            top.pack_start(chip, False, False, 0)

        top.pack_end(self._action_buttons(w), False, False, 0)
        self.detail_holder.pack_start(top, False, False, 0)
        self.detail_holder.pack_start(spacer(4), False, False, 0)

        if st and st.get("last"):
            self.detail_holder.pack_start(
                L(f"最近练习 {fmt_ts(st['last'])}", cls="row-sub"), False, False, 0)

        self.detail_holder.pack_start(spacer(10), False, False, 0)

        # 全称 + 拆词
        parts = breakdown(w)
        if parts:
            flow = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
            flow.pack_start(M(f"<span size='large' weight='bold'>{pango_esc(w['en_full'])}</span>",
                              selectable=True), False, False, 0)
            for en, zh in parts:
                row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
                row.pack_start(M(f"<span weight='bold'>{pango_esc(en)}</span>", wrap=False),
                               False, False, 0)
                row.pack_start(L("·"), False, False, 0)
                row.pack_start(L(zh, cls="row-sub", wrap=False), False, False, 0)
                flow.pack_start(row, False, False, 0)
            self.detail_holder.pack_start(card("英文全称", [flow]), False, False, 0)
        else:
            self.detail_holder.pack_start(
                card("英文全称", [M(f"<span size='large' weight='bold'>{pango_esc(w['en_full'])}</span>",
                                    selectable=True)]),
                False, False, 0)

        self.detail_holder.pack_start(spacer(8), False, False, 0)

        zh_children = [L(w.get("zh", ""), selectable=True)]
        if w.get("zh_aliases"):
            zh_children.append(L("别名：" + "、".join(w["zh_aliases"]), cls="row-sub"))
        self.detail_holder.pack_start(card("中文意思", zh_children), False, False, 0)

        self.detail_holder.pack_start(spacer(8), False, False, 0)

        pr = [M(f"<span size='large'>{pango_esc(w.get('pronounce',''))}</span>",
                selectable=True, cls="mono")]
        choices = w.get("pronounce_choices") or []
        if choices:
            pr.append(L("练习时的候选读音（✔ 正确）", cls="row-sub"))
            for c in choices:
                mark = "✔" if c == choices[0] else "·"
                pr.append(L(f"{mark}  {c}", cls="mono"))
        self.detail_holder.pack_start(card("读法", pr), False, False, 0)

        rel = [m for m in (self.db.get("mcqs") or [])
               if w["term"].lower() in json.dumps(m, ensure_ascii=False).lower()]
        if rel:
            self.detail_holder.pack_start(spacer(8), False, False, 0)
            kids = []
            for m in rel:
                box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=3)
                box.pack_start(M(f"<b>{pango_esc(m['prompt'])}</b>"), False, False, 0)
                for i, c in enumerate(m["choices"]):
                    mark = "✔" if i == 0 else "·"
                    box.pack_start(L(f"{mark}  {c}", cls="row-sub" if i else ""), False, False, 0)
                if m.get("explain"):
                    box.pack_start(L(m["explain"], cls="row-sub"), False, False, 0)
                kids.append(box)
                kids.append(spacer(6))
            self.detail_holder.pack_start(card("相关题目", kids), False, False, 0)

        self.detail_holder.show_all()

    def _action_buttons(self, w):
        from gi.repository import Gtk
        box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        b1 = Gtk.Button(label="练这个")
        b1.connect("clicked", lambda *_: self.win.quiz.start_single(w["term"]))
        b2 = Gtk.Button(label="编辑")
        b2.connect("clicked", lambda *_: self.edit_term(w))
        box.pack_start(b1, False, False, 0)
        box.pack_start(b2, False, False, 0)
        return box

    # ---------------- 增改
    def add_term(self):
        self.edit_term(None)

    def edit_term(self, w):
        from gi.repository import Gtk
        dlg = TermDialog(self.win.window, w)
        resp = dlg.run()
        data = dlg.result()
        dlg.destroy()
        if resp != Gtk.ResponseType.OK or not data:
            return
        if w is None:
            self.db.setdefault("words", []).append(data)
        else:
            w.update(data)
        save_db(self.db)
        self.refresh_list()
        self.win.toast("已保存")


def _titled(term: str):
    from gi.repository import Gtk
    lb = Gtk.Label(xalign=0, yalign=0.5)
    lb.set_markup(f"<span size='large' weight='bold'>{pango_esc(term)}</span>")
    lb.get_style_context().add_class("row-term")
    lb.set_selectable(False)
    return lb


def _ts_value(ts: str) -> int:
    try:
        return int(datetime.fromisoformat(ts).timestamp())
    except Exception:
        return 0


class TermDialog:
    def __init__(self, parent, word):
        from gi.repository import Gtk
        self.dlg = Gtk.Dialog(title="编辑术语" if word else "新增术语",
                              transient_for=parent, flags=0)
        self.dlg.set_default_size(520, -1)
        self.dlg.add_buttons("取消", Gtk.ResponseType.CANCEL,
                             "保存", Gtk.ResponseType.OK)
        area = self.dlg.get_content_area()
        area.set_spacing(8)
        area.set_border_width(16)

        self.f_term = Gtk.Entry()
        self.f_en = Gtk.Entry()
        self.f_zh = Gtk.Entry()
        self.f_pr = Gtk.Entry()
        self.f_term.set_placeholder_text("缩写，如 OPS")
        self.f_en.set_placeholder_text("英文全称，如 Open Pluggable Specification")
        self.f_zh.set_placeholder_text("中文意思")
        self.f_pr.set_placeholder_text("读法（可留空）")

        for lab, entry in (("缩写", self.f_term), ("英文全称", self.f_en),
                           ("中文意思", self.f_zh), ("读法", self.f_pr)):
            area.pack_start(L(lab, cls="row-sub"), False, False, 0)
            area.pack_start(entry, False, False, 0)

        if word:
            self.f_term.set_text(word.get("term", ""))
            self.f_en.set_text(word.get("en_full", ""))
            self.f_zh.set_text(word.get("zh", ""))
            self.f_pr.set_text(word.get("pronounce", ""))
            self.f_term.set_sensitive(False)

        area.show_all()

    def run(self):
        return self.dlg.run()

    def destroy(self):
        self.dlg.destroy()

    def result(self):
        term = self.f_term.get_text().strip()
        en = self.f_en.get_text().strip()
        zh = self.f_zh.get_text().strip()
        pr = self.f_pr.get_text().strip()
        if not term or not en or not zh:
            return None
        choices = [pr or en, "（干扰项 1，请编辑 words.json）",
                   "（干扰项 2）", "（干扰项 3）"]
        return {
            "term": term, "en_full": en,
            "en_aliases": [en.lower()],
            "zh": zh, "zh_aliases": [zh],
            "pronounce": pr or en,
            "pronounce_accept": [pr.lower()] if pr else [],
            "pronounce_choices": choices if pr else [],
        }


# ---------------------------------------------------------------- 答题页

class QuizPage:
    def __init__(self, win):
        from gi.repository import Gtk
        self.win = win
        self.db = load_db()
        self.session: list[dict[str, Any]] = []
        self.index = 0
        self.correct = 0
        self.answered = 0
        self.current = None
        self.summary_mode = False
        self.only_term: str | None = None

        self.box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        self.box.set_margin_start(36); self.box.set_margin_end(36)
        self.box.set_margin_top(24); self.box.set_margin_bottom(24)

        self.stack = Gtk.Stack()
        self.stack.set_transition_type(Gtk.StackTransitionType.CROSSFADE)
        self.box.pack_start(self.stack, True, True, 0)

        self.stack.add_named(self.build_start(), "start")
        self.stack.add_named(self.build_question(), "question")
        self.stack.add_named(self.build_result(), "result")
        self.stack.set_visible_child_name("start")

    def build_start(self):
        from gi.repository import Gtk
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=14)
        box.set_valign(Gtk.Align.CENTER); box.set_halign(Gtk.Align.CENTER)

        self.start_title = L("开始一组练习", markup=True, xalign=0.5)
        self.start_title.set_markup("<span size='xx-large' weight='bold'>开始一组练习</span>")
        box.pack_start(self.start_title, False, False, 0)

        self.start_hint = L("", cls="row-sub", xalign=0.5)
        box.pack_start(self.start_hint, False, False, 0)

        kinds_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=16)
        kinds_box.set_halign(Gtk.Align.CENTER)
        self.kind_checks = {}
        for k in TYPES:
            cb = Gtk.CheckButton(label=TYPE_FULL[k])
            cb.set_active(True)
            if k == "relation" and not (self.db.get("mcqs") or []):
                cb.set_sensitive(False); cb.set_active(False)
            kinds_box.pack_start(cb, False, False, 0)
            self.kind_checks[k] = cb
        box.pack_start(kinds_box, False, False, 0)

        count_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        count_box.set_halign(Gtk.Align.CENTER)
        count_box.pack_start(L("题量"), False, False, 0)
        self.count_combo = Gtk.ComboBoxText()
        for t in ("10 题", "20 题", "30 题", "全部"):
            self.count_combo.append_text(t)
        self.count_combo.set_active(0)
        count_box.pack_start(self.count_combo, False, False, 0)
        box.pack_start(count_box, False, False, 0)

        self.smart_check = Gtk.CheckButton(label="优先出我错得多的题")
        self.smart_check.set_active(True)
        self.smart_check.set_halign(Gtk.Align.CENTER)
        box.pack_start(self.smart_check, False, False, 0)

        self.start_btn = Gtk.Button(label="开始答题")
        self.start_btn.get_style_context().add_class("suggested-action")
        self.start_btn.set_size_request(220, 44)
        self.start_btn.set_halign(Gtk.Align.CENTER)
        self.start_btn.connect("clicked", lambda *_: self.start_session())
        box.pack_start(self.start_btn, False, False, 8)

        box.pack_start(L("答完自动记录，可在「记录」页看正确率。", cls="row-sub", xalign=0.5),
                       False, False, 0)
        return box

    def build_question(self):
        from gi.repository import Gtk
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=14)
        box.set_valign(Gtk.Align.START)

        top = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        self.progress_label = L("", cls="row-sub")
        top.pack_start(self.progress_label, True, True, 0)
        self.live_label = L("", cls="row-sub", xalign=1)
        top.pack_end(self.live_label, False, False, 0)
        box.pack_start(top, False, False, 0)

        self.question_label = L("", markup=True, cls="q-text")
        box.pack_start(self.question_label, False, False, 0)

        self.input_area = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
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

        self.entry = None
        self.radios = []
        return box

    def build_result(self):
        from gi.repository import Gtk
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        box.set_valign(Gtk.Align.START)
        self.badge = Gtk.Label(xalign=0)
        box.pack_start(self.badge, False, False, 0)
        self.result_correct = L("", markup=True)
        box.pack_start(self.result_correct, False, False, 0)
        self.result_yours = L("", markup=True)
        box.pack_start(self.result_yours, False, False, 0)
        self.result_break = L("", markup=True, cls="row-sub")
        box.pack_start(self.result_break, False, False, 0)
        self.result_why = L("", cls="row-sub")
        box.pack_start(self.result_why, False, False, 0)
        self.result_hist = L("", cls="row-sub")
        box.pack_start(self.result_hist, False, False, 0)
        self.next_btn = Gtk.Button(label="下一题")
        self.next_btn.get_style_context().add_class("suggested-action")
        self.next_btn.set_size_request(180, 40)
        self.next_btn.connect("clicked", lambda *_: self.next_question())
        box.pack_start(self.next_btn, False, False, 10)
        return box

    # ---------------- 流程
    def refresh_start_hint(self) -> None:
        ok, total = overall(load_history())
        self.start_hint.set_text(
            f"共 {len(self.db.get('words') or [])} 个术语"
            + (f" · 历史 {ok}/{total}（{int(round(ok/total*100))}%）" if total else " · 还没练过")
        )

    def start_single(self, term: str) -> None:
        self.only_term = term
        self.start_title.set_text("练习这个术语")
        self.start_btn.set_label("开始")
        self.win.stack.set_visible_child_name("quiz")
        self.stack.set_visible_child_name("start")
        self.refresh_start_hint()

    def start_session(self) -> None:
        self.db = load_db()
        kinds = {k for k, cb in self.kind_checks.items() if cb.get_active()}
        if not kinds:
            self.win.toast("至少选一种题型")
            return
        count = {0: 10, 1: 20, 2: 30, 3: 0}.get(self.count_combo.get_active(), 10)
        self.session = build_session(self.db, kinds, count, self.smart_check.get_active(),
                                     self.only_term)
        if not self.session:
            self.win.toast("题库是空的")
            return
        self.index = 0; self.correct = 0; self.answered = 0
        self.summary_mode = False
        self.reveal_btn.show(); self.skip_btn.show()
        self.submit_btn.set_label("提交")
        self.show_question()

    def show_question(self) -> None:
        from gi.repository import Gtk
        if self.index >= len(self.session):
            self.show_summary(); return
        self.current = self.session[self.index]
        item = self.current
        self.progress_label.set_text(f"第 {self.index + 1} / {len(self.session)} 题")
        live = f"已答 {self.answered}"
        if self.answered:
            live += f" · 正确率 {int(round(self.correct / self.answered * 100))}%"
        self.live_label.set_text(live)

        for c in self.input_area.get_children():
            self.input_area.remove(c)
        self.entry = None
        self.radios = []

        if item["mode"] == "mcq":
            q = item["q"]
            self.question_label.set_markup(f"<b>{pango_esc(q['prompt'])}</b>")
            choices = list(q["choices"]); random.shuffle(choices)
            group = None
            for c in choices:
                rb = Gtk.RadioButton.new_with_label_from_widget(group, c)
                group = group or rb
                self.input_area.pack_start(rb, False, False, 0)
                self.radios.append(rb)
            self.radios[0].set_active(True)
        else:
            w = item["word"]; kind = item["kind"]
            if kind == "pronounce":
                self.question_label.set_markup(
                    f"<b>「{pango_esc(w['term'])}」</b> 的英文全称，哪个音标更合适？")
                choices = list(w["pronounce_choices"]); random.shuffle(choices)
                group = None
                for c in choices:
                    rb = Gtk.RadioButton.new_with_label_from_widget(group, c)
                    group = group or rb
                    self.input_area.pack_start(rb, False, False, 0)
                    self.radios.append(rb)
                self.radios[0].set_active(True)
            else:
                hint = "用自己的话写，意思对就算" if kind == "zh" else "写出完整英文，虚词差一点没关系"
                self.question_label.set_markup(
                    f"<b>「{pango_esc(w['term'])}」</b> · {TYPE_FULL[kind]}\n"
                    f"<span size='small'>{pango_esc(hint)}</span>")
                self.entry = Gtk.Entry()
                self.entry.set_placeholder_text("输入答案后回车")
                self.entry.connect("activate", lambda *_: self.do_submit())
                self.input_area.pack_start(self.entry, False, False, 0)

        self.input_area.show_all()
        self.stack.set_visible_child_name("question")
        if self.entry is not None:
            self.entry.grab_focus()

    def on_submit_clicked(self, *_):
        if self.summary_mode:
            self.back_to_start()
        else:
            self.do_submit()

    def _answer(self) -> str:
        if self.radios:
            for rb in self.radios:
                if rb.get_active():
                    return rb.get_label()
            return ""
        return self.entry.get_text() if self.entry is not None else ""

    def _expected(self, item) -> str:
        if item["mode"] == "mcq":
            return item["q"]["choices"][0]
        w = item["word"]
        return {"en_full": w["en_full"], "zh": w["zh"]}.get(
            item["kind"], w["pronounce_choices"][0] if w.get("pronounce_choices") else w.get("pronounce", ""))

    def do_submit(self, reveal: bool = False) -> None:
        item = self.current
        if not item:
            return
        answer = "" if reveal else self._answer().strip()
        expected = self._expected(item)
        if not reveal and not answer:
            self.win.toast("还没写答案"); return

        engine = "查看答案" if reveal else "四选一对照"
        ok, why = False, ""
        if reveal:
            pass
        elif item["mode"] == "mcq":
            ok = answer == item["q"]["choices"][0]
            why = item["q"].get("explain", "")
        elif item["kind"] == "pronounce":
            ok = answer == item["word"]["pronounce_choices"][0]
            if not ok and normalize(answer) in {normalize(x) for x in item["word"].get("pronounce_accept", [])}:
                ok, engine = True, "可接受读法"
            why = f"标准读法：{item['word'].get('pronounce','')}"
        else:
            ok, why, engine = grade(item["kind"], item["word"], answer)

        term = item["word"]["term"] if item["mode"] == "term" else "板卡关系"
        pct = align_markup(expected, answer)[2] if (
            item["mode"] == "term" and item["kind"] in ("en_full", "zh") and not reveal
        ) else (100 if ok else 0)

        append_history({"ts": datetime.now(TZ).isoformat(timespec="seconds"), "term": term,
                        "kind": item["kind"], "answer": answer, "ok": ok,
                        "engine": engine, "pct": pct, "reveal": reveal})
        self.answered += 1
        if ok:
            self.correct += 1
        self.show_result(item, ok, answer, expected, why, reveal, term)

    def show_result(self, item, ok, answer, expected, why, reveal, term) -> None:
        ctx = self.badge.get_style_context()
        for c in ("badge-ok", "badge-bad", "badge-neutral"):
            ctx.remove_class(c)
        if reveal:
            ctx.add_class("badge-neutral"); self.badge.set_text("看答案")
        elif ok:
            ctx.add_class("badge-ok"); self.badge.set_text("通过")
        else:
            ctx.add_class("badge-bad"); self.badge.set_text("再记一下")

        if item["mode"] == "term" and item["kind"] in ("en_full", "zh") and not reveal:
            cm, gm, p = align_markup(expected, answer)
            self.result_correct.set_markup(f"<b>正确：</b>{cm}  <span size='small'>（{p}%）</span>")
            self.result_yours.set_markup(f"<b>你的：</b>{gm}")
        else:
            self.result_correct.set_markup(f"<b>正确：</b>{pango_esc(expected)}")
            self.result_yours.set_markup(f"<b>你的：</b>{pango_esc(answer) if answer else '（未作答）'}")

        if item["mode"] == "term":
            parts = breakdown(item["word"])
            if parts:
                self.result_break.set_markup("拆解：" + " · ".join(
                    f"{pango_esc(en)}（{pango_esc(zh)}）" for en, zh in parts))
            else:
                self.result_break.set_text("")
        else:
            self.result_break.set_text("")

        self.result_why.set_text(why or "")
        st = term_stats(load_history()).get(term)
        if st:
            self.result_hist.set_text(
                f"「{term}」累计 {st['ok']}/{st['total']}，正确率 {int(round(st['ok']/st['total']*100))}%")

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
        for c in self.input_area.get_children():
            self.input_area.remove(c)
        self.entry = None; self.radios = []
        pct = int(round(self.correct / self.answered * 100)) if self.answered else 0
        self.progress_label.set_text("本组结束")
        self.live_label.set_text("")
        self.question_label.set_markup(
            f"<span size='xx-large' weight='bold'>{pct}%</span>\n"
            f"<span size='large'>答对 {self.correct} / {self.answered} 题</span>")
        self.reveal_btn.hide(); self.skip_btn.hide()
        self.submit_btn.set_label("再来一组")
        self.summary_mode = True
        self.stack.set_visible_child_name("question")
        self.win.stats.refresh()

    def back_to_start(self) -> None:
        self.summary_mode = False
        self.reveal_btn.show(); self.skip_btn.show()
        self.submit_btn.set_label("提交")
        self.refresh_start_hint()
        self.stack.set_visible_child_name("start")


# ---------------------------------------------------------------- 记录页

class StatsPage:
    def __init__(self, win):
        from gi.repository import Gtk
        self.win = win
        sw = Gtk.ScrolledWindow()
        sw.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        self.box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=14)
        self.box.set_margin_start(32); self.box.set_margin_end(32)
        self.box.set_margin_top(24); self.box.set_margin_bottom(24)
        sw.add(self.box)
        self.widget = sw
        self.refresh()

    def _clear(self):
        for c in self.box.get_children():
            self.box.remove(c)

    def refresh(self) -> None:
        from gi.repository import Gtk
        self._clear()
        history = load_history()
        ok, total = overall(history)

        head = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        t = L("答题记录", markup=True)
        t.set_markup("<span size='xx-large' weight='bold'>答题记录</span>")
        head.pack_start(t, True, True, 0)
        b = Gtk.Button(label="刷新")
        b.connect("clicked", lambda *_: self.refresh())
        head.pack_end(b, False, False, 0)
        self.box.pack_start(head, False, False, 0)

        if not total:
            self.box.pack_start(L("还没有记录。去「答题」页做一组。", cls="row-sub"), False, False, 0)
            self.box.show_all(); return

        cards = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        for title, value in (("总题数", str(total)), ("答对", str(ok)),
                             ("正确率", f"{int(round(ok/total*100))}%")):
            box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
            box.get_style_context().add_class("card")
            v = L("", markup=True)
            v.set_markup(f"<span size='xx-large' weight='bold'>{pango_esc(value)}</span>")
            box.pack_start(v, False, False, 0)
            box.pack_start(L(title, cls="row-sub"), False, False, 0)
            cards.pack_start(box, True, True, 0)
        self.box.pack_start(cards, False, False, 0)

        self.box.pack_start(self._section("按题型"), False, False, 0)
        for name, o, n in sorted(accuracy_rows(history, "kind"), key=lambda x: -x[2]):
            self.box.pack_start(self._bar(TYPE_LABEL.get(name, name), o, n), False, False, 0)

        self.box.pack_start(self._section("按术语（弱的在前）"), False, False, 0)
        for name, o, n in accuracy_rows(history, "term")[:12]:
            self.box.pack_start(self._bar(name, o, n), False, False, 0)

        self.box.pack_start(self._section("最近 30 条"), False, False, 0)
        store = Gtk.ListStore(str, str, str, str)
        for r in reversed(history[-30:]):
            store.append([fmt_ts(r.get("ts", "")), r.get("term", ""),
                          TYPE_LABEL.get(r.get("kind", ""), r.get("kind", "")),
                          "✔" if r.get("ok") else ("看答案" if r.get("reveal") else "✘")])
        view = Gtk.TreeView(model=store)
        for i, name in enumerate(("时间", "术语", "题型", "结果")):
            col = Gtk.TreeViewColumn(name, Gtk.CellRendererText(), text=i)
            col.set_resizable(True)
            view.append_column(col)
        self.box.pack_start(view, False, False, 0)
        self.box.show_all()

    def _section(self, text: str):
        lb = L("", markup=True)
        lb.set_markup(f"<span weight='bold'>{pango_esc(text)}</span>")
        lb.set_margin_top(10)
        return lb

    def _bar(self, name: str, ok: int, total: int):
        from gi.repository import Gtk
        row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        n = L(name, wrap=False)
        n.set_size_request(160, -1)
        n.set_ellipsize(3)
        row.pack_start(n, False, False, 0)
        bar = Gtk.LevelBar()
        bar.set_min_value(0); bar.set_max_value(1)
        bar.set_value(ok / total if total else 0)
        bar.set_valign(Gtk.Align.CENTER)
        row.pack_start(bar, True, True, 0)
        pct = int(round(ok / total * 100)) if total else 0
        v = L(f"{pct}%  ({ok}/{total})", cls="row-sub", wrap=False, xalign=1)
        v.set_size_request(120, -1)
        row.pack_end(v, False, False, 0)
        return row


# ---------------------------------------------------------------- 主窗口

class MainWindow:
    def __init__(self, app):
        from gi.repository import Gtk
        self.gtk = Gtk
        self.window = Gtk.ApplicationWindow(application=app, title=APP_NAME)
        self.window.set_default_size(1180, 760)

        header = Gtk.HeaderBar()
        header.set_show_close_button(True)
        header.props.title = APP_NAME
        header.props.subtitle = f"v{VERSION}"
        self.window.set_titlebar(header)

        self.toast_label = Gtk.Label(label="")
        header.pack_end(self.toast_label)

        self.stack = Gtk.Stack()
        self.stack.set_transition_type(Gtk.StackTransitionType.SLIDE_LEFT_RIGHT)
        self.stack.set_transition_duration(150)

        nav = Gtk.ListBox()
        nav.get_style_context().add_class("nav")
        nav.set_selection_mode(Gtk.SelectionMode.SINGLE)
        nav.set_size_request(196, -1)
        self._nav_rows = {}
        self._syncing = False
        for page, title, icon in (("library", "题库", "view-list-symbolic"),
                                  ("quiz", "答题", "dialog-question-symbolic"),
                                  ("stats", "记录", "utilities-system-monitor-symbolic")):
            row = Gtk.ListBoxRow()
            row.page_name = page
            hb = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
            hb.set_margin_start(10); hb.set_margin_end(10)
            hb.set_margin_top(9); hb.set_margin_bottom(9)
            hb.pack_start(Gtk.Image.new_from_icon_name(icon, Gtk.IconSize.BUTTON), False, False, 0)
            hb.pack_start(Gtk.Label(label=title, xalign=0), True, True, 0)
            row.add(hb)
            nav.add(row)
            self._nav_rows[page] = row

        nav_wrap = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        nav_wrap.set_margin_top(6); nav_wrap.set_margin_bottom(6)
        nav_wrap.pack_start(nav, False, False, 0)

        self.library = LibraryPage(self)
        self.quiz = QuizPage(self)
        self.stats = StatsPage(self)

        self.stack.add_titled(self.library.box, "library", "题库")
        self.stack.add_titled(self.quiz.box, "quiz", "答题")
        self.stack.add_titled(self.stats.widget, "stats", "记录")

        nav.connect("row-selected", self._on_nav)
        self.stack.connect("notify::visible-child", self._on_page)
        self._nav = nav
        nav.select_row(self._nav_rows["library"])

        root = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=0)
        root.pack_start(nav_wrap, False, False, 0)
        root.pack_start(Gtk.Separator(orientation=Gtk.Orientation.VERTICAL), False, False, 0)
        root.pack_start(self.stack, True, True, 0)
        self.window.add(root)
        self.quiz.refresh_start_hint()
        self._toast_timeout = None

    def _on_nav(self, _lb, row):
        if row is None or self._syncing:
            return
        self._syncing = True
        self.stack.set_visible_child_name(row.page_name)
        self._syncing = False

    def _on_page(self, stack, _p):
        if self._syncing:
            return
        name = stack.get_visible_child_name()
        row = self._nav_rows.get(name)
        if row is not None:
            self._syncing = True
            self._nav.select_row(row)
            self._syncing = False
        if name == "stats":
            self.stats.refresh()
        if name == "library":
            self.library.db = load_db()
            self.library.refresh_list()

    def show_all(self):
        self.window.show_all()

    def toast(self, text: str) -> None:
        self.toast_label.set_text(text)
        if getattr(self, "_toast_timeout", None):
            self.gtk.timeout_remove(self._toast_timeout)
        self._toast_timeout = self.gtk.timeout_add(2500, self._clear_toast)

    def _clear_toast(self):
        self.toast_label.set_text("")
        self._toast_timeout = None
        return False


class App:
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
                from gi.repository import Gdk, Gtk
                Gdk.set_program_class("io.github.termquiz")
                Gtk.Window.set_default_icon_name("accessories-dictionary")
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
            self.GLib.timeout_add(500, lambda: (app.quit(), False)[1])

    def run(self) -> int:
        return self.app.run([sys.argv[0]])


# ---------------------------------------------------------------- 命令

def cmd_add(term: str, en_full: str, zh: str, pronounce: str = "") -> None:
    db = load_db()
    db.setdefault("words", []).append({
        "term": term.strip(), "en_full": en_full.strip(),
        "en_aliases": [en_full.strip().lower()],
        "zh": zh.strip(), "zh_aliases": [zh.strip()],
        "pronounce": pronounce.strip() or en_full.strip(),
        "pronounce_accept": [pronounce.strip().lower()] if pronounce else [],
        "pronounce_choices": [pronounce.strip() or en_full.strip(),
                              "（占位干扰项，请编辑 words.json）", "operations", "point of contact"],
    })
    save_db(db)
    print("已写入", words_path())


def cmd_install() -> None:
    apps = Path.home() / ".local/share/applications"
    apps.mkdir(parents=True, exist_ok=True)
    entry = apps / "io.github.termquiz.desktop"
    entry.write_text(f"""[Desktop Entry]
Version=1.0
Type=Application
Name={APP_NAME}
Comment=术语题库与练习
Exec={ROOT}/start.sh
Icon=accessories-dictionary
Terminal=false
StartupNotify=false
StartupWMClass=io.github.termquiz
Categories=Education;
""", encoding="utf-8")
    entry.chmod(0o755)
    subprocess.run(["update-desktop-database", str(apps)], check=False)
    subprocess.run(["systemctl", "--user", "disable", "--now", "term-quiz.timer"], check=False)
    print("已安装启动项：", entry)


def main() -> int:
    log(f"main argv={sys.argv}")
    args = [a for a in sys.argv[1:] if a != "--smoke"]
    smoke = "--smoke" in sys.argv
    cmd = args[0] if args else "gui"

    if smoke or cmd == "gui":
        return App(smoke=smoke).run()
    if cmd == "install":
        cmd_install(); return 0
    if cmd == "add" and len(args) >= 4:
        cmd_add(args[1], args[2], args[3], args[4] if len(args) > 4 else "")
        return 0
    print(__doc__)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
