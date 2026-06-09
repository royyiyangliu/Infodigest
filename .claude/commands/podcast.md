# /podcast — 播客转录与投资者摘要

将一个播客集完整走完：URL解析 → 转录 → 生成中文HTML摘要 → 更新索引 → Git push。

**用法：** `/podcast <apple_podcast_url 或 小宇宙_url>`

---

## 执行步骤

### Step 1：运行 pipeline.py 完成转录

```bash
python pipeline.py "$ARGUMENTS"
```

`pipeline.py` 会：
- **Apple Podcast**：通过 iTunes API + RSS 提取音频直链，从 RSS `<language>` 标签判断语言
- **小宇宙**：从页面 HTML 的 `__NEXT_DATA__` JSON 中提取 `enclosure.url`，语言默认 `zh`
- 自动跟随 CDN 重定向（Substack 等签名 URL 均可处理）
- 提交给阿里云百炼 Fun-ASR（`fun-asr` 模型，`diarization_enabled=True`）
- 轮询直到 SUCCEEDED，将转录保存为 `docs/podcast/YYMMDD-<title>/transcript.txt`
- 自动更新 `docs/podcast-episodes.json`（description 字段为空，Step 4 补充）

等 pipeline.py 成功返回后，记录：
- `ep_id`：集目录名（如 `260609-Episode-Title`）
- `title`：节目标题
- `podcast_name`：播客名称
- `language`：`en` 或 `zh`

### Step 2：读取转录全文

读取 `docs/podcast/<ep_id>/transcript.txt`，这是带时间戳和说话人标签的纯文本。

### Step 3：生成投资者摘要 HTML

目录由 pipeline.py 已创建，直接生成 **`docs/podcast/<ep_id>/summary.html`**，要求：

**内容要求：**
- 从**投资者视角**对访谈全文进行提炼总结
- **不编造内容**，忠实还原原意；原文是英文的不需要翻译，直接理解后总结
- **尤其保留量化指标和数字**（百分比、金额、时间、倍数等），用 `<strong>` 或红色高亮
- 根据内容决定结构（分节标题 + 要点列表 + 关键表格）和篇幅，**上限5000汉字**
- 总结语言：**中文**

**HTML 格式要求（与现有 summary.html 风格一致）：**
- 使用 `<!DOCTYPE html>`，`lang="zh-CN"`，内嵌 CSS，无外部依赖
- Header 显示：节目标题、嘉宾姓名、播客名称、日期
- 正文用 `<h2>` 分节，`<ul>/<li>` 列要点，重要数字用 `<strong>` 或 `color:#dc2626`
- 底部 footer 注明：原始 URL、转录引擎（阿里云百炼 Fun-ASR）、总结生成说明
- 参考已有样式：`docs/podcast/260609-Alex-Imas-and-Phil-Trammell-What-remains-scarce-after-AGI/summary.html`

### Step 4：补充 description 字段

pipeline.py 已自动将本集写入 `docs/podcast-episodes.json`，但 `description` 为空，需补充：

```python
import json
from pathlib import Path

manifest = Path("docs/podcast-episodes.json")
episodes = json.loads(manifest.read_text())
episodes[0]["description"] = "<一句话中文简介，从summary内容提炼，50字内>"
manifest.write_text(json.dumps(episodes, ensure_ascii=False, indent=2) + "\n")
```

如需手动添加完整条目（pipeline.py 未运行时）：

```python
import json
from pathlib import Path
from datetime import datetime

ep_id    = "<ep_id>"
manifest = Path("docs/podcast-episodes.json")
episodes = json.loads(manifest.read_text()) if manifest.exists() else []
episodes = [e for e in episodes if e.get("id") != ep_id]
episodes.insert(0, {
    "id": ep_id,
    "title": "<title>",
    "podcast": "<podcast_name>",
    "date": datetime.now().strftime("%Y-%m-%d"),
    "language": "<language>",
    "path": f"podcast/{ep_id}/summary.html",
    "description": "<一句话中文简介，50字内>",
})
manifest.write_text(json.dumps(episodes, ensure_ascii=False, indent=2) + "\n")
```

### Step 5：Git commit & push

```bash
git add "docs/podcast/<ep_id>/" docs/podcast-episodes.json
git commit -m "Add podcast: <title>

转录：阿里云百炼 Fun-ASR，<language>，说话人分离
总结：投资者视角中文 HTML"
git push
```

---

## 注意事项

- **API Key**：`DASHSCOPE_API_KEY` 环境变量必须已配置
- **Apple Podcast URL 格式**：`https://podcasts.apple.com/.../id{podcast_id}?i={episode_id}`
- **小宇宙 URL**：从页面 HTML 的 `__NEXT_DATA__` JSON 中提取 `enclosure.url`，语言默认 `zh`（已在 pipeline.py 中原生支持）
- **转录时间**：30分钟音频约需2-3分钟，90分钟约需5-8分钟
- **Substack/CDN 音频**：pipeline.py 已自动跟随重定向，无需手动处理
- **语言判断**：RSS `<language>` 标签为 `en` 开头则用 `['en']`，`zh` 开头则用 `['zh']`；其他默认 `['zh']`
- 转录完成后，`transcript.txt` 不会删除，可供后续重新生成摘要

## 目录结构说明

```
Infodigest/
├── pipeline.py                          # 转录脚本
└── docs/
    ├── index.html                       # 主页（含 Tab 2 播客摘要）
    ├── podcast-episodes.json            # 播客集索引
    └── podcast/
        └── <ep_id>/                     # 每集所有内容统一存放
            ├── transcript.txt           # 带时间戳和说话人标签的转录原文
            ├── source.url               # 原始播客 URL 存档
            └── summary.html             # GitHub Pages 提供服务的摘要页
```

## 相关文件

| 文件 | 作用 |
|------|------|
| `pipeline.py` | URL解析 + ASR提交/轮询 + 保存transcript + 写入podcast-episodes.json |
| `docs/podcast/<ep_id>/transcript.txt` | 带时间戳和说话人标签的转录原文 |
| `docs/podcast/<ep_id>/source.url` | 原始播客 URL 存档 |
| `docs/podcast-episodes.json` | 所有集的元数据，供播客摘要 Tab 读取 |
| `docs/podcast/<ep_id>/summary.html` | 投资者视角中文摘要（GitHub Pages 页面）|
| `docs/index.html` | 主页（Tab 1: AI 信息日报 / Tab 2: 播客研究摘要）|
