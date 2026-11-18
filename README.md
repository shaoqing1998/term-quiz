# 术语训练 (term-quiz)

本地运行的术语题库 + 练习工具，GTK3 桌面应用。三页：**词条 / 答题 / 记录**。

不联网、不弹通知，所有数据存在本机。

## 安装

### 方式 1：deb 包（推荐，双击即可）

```bash
wget https://github.com/shaoqing1998/term-quiz/releases/latest/download/term-quiz_1.0.0_all.deb
sudo apt install ./term-quiz_1.0.0_all.deb
```

依赖会自动装（`python3-gi`、`gir1.2-gtk-3.0`）。

### 方式 2：一键脚本（免 sudo）

```bash
curl -fsSL https://raw.githubusercontent.com/shaoqing1998/term-quiz/main/install-online.sh | bash
```

装到 `~/.local/share/term-quiz`，不需要 root。

## 使用

- 打开：按 `Super` 键搜「术语训练」，或终端运行 `term-quiz`
- **词条**：搜索术语，看英文全称 / 中文 / 读法 / 别名 / 相关题目
- **答题**：点「开始答题」→ 选题型（英文全称 / 中文 / 读法 / 板卡关系）→ 选题量 → 开始
- **记录**：总体正确率、按题型、按术语（弱的排前面）、最近 30 条

答错的题会提高下次出现概率（可在开始页关掉「优先出错得多的题」）。

## 数据位置

```
~/.local/share/term-quiz/
├── words.json      # 词库（首次运行从程序目录复制一份）
├── history.jsonl   # 答题记录
└── app.log         # 启动日志
```

卸载程序**不会**删除这个目录。

## 词库格式

```json
{
  "settings": {},
  "words": [
    {
      "term": "POC",
      "en_full": "Proof of Concept",
      "en_aliases": ["proof of concept"],
      "zh": "概念验证 / 样机验证",
      "zh_aliases": ["概念验证", "样机验证"],
      "pronounce": "/pruːf əv ˈkɒnsept/",
      "pronounce_accept": ["/pruːf əv ˈkɒnsept/"],
      "pronounce_choices": ["/pruːf əv ˈkɒnsept/", "/pɔɪnt əv kəˈtækt/"]
    }
  ],
  "mcqs": [
    {
      "id": "example",
      "prompt": "题干",
      "choices": ["正确答案", "干扰项 1", "干扰项 2", "干扰项 3"],
      "explain": "解析"
    }
  ]
}
```

约定：四选一题的 **`choices[0]` 是正确答案**。

## 判定规则

- 英文全称 / 中文意思：规则匹配（相似度、关键词覆盖、中文字符重合度）
- 如果本机跑着 Ollama（`127.0.0.1:11434`），会再用小模型复核一遍；模型过严时以宽松规则为准

## 自己打包

```bash
bash packaging/build.sh
# 产出 dist/term-quiz_1.0.0_all.deb 和 dist/term-quiz-1.0.0.tar.gz
```

## 命令行

```bash
term-quiz                 # 打开图形界面
term-quiz quiz            # 终端里随机抽一题（排查用）
python3 term_quiz.py add TERM 'English Full' '中文意思' '读法'
```

## 许可

个人自用工具，未附许可协议；如需开源协议自行添加。
