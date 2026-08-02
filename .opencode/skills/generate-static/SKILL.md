---
name: generate-static
description: 当需要生成知识库静态数据展示页面时使用此技能
allowed-tools: Read, Glob, Bash, Write
---

# 知识库静态页面生成技能

## 使用场景

当需要将 `knowledge/articles/` 下的所有 JSON 文章文件渲染为自包含的静态 HTML 页面时使用此技能。

## 执行步骤

### 1. 确认数据源

检查 `knowledge/articles/` 目录下存在 JSON 文件：

```
knowledge/articles/
├── 2026-07-30-github-trending-xxx.json
├── 2026-07-30-rss-xxx.json
├── 2026-07-31-github-trending-xxx.json
└── ...
```

每个 JSON 文件至少包含：
- `title` — 项目标题
- `source_url` — 原始链接（用于点击跳转）
- `summary` — 中文摘要
- `tags` — 分类标签
- `score` — 评分（1-10）
- `score_reason` — 评分理由

### 2. 运行生成器

执行 `knowledge/generate_index.py`：

```bash
python3 knowledge/generate_index.py
```

此脚本会：
- 读取 `knowledge/articles/*.json` 下所有文件
- 按文件名（即采集日期）倒序排列
- 将全部数据嵌入 HTML，生成为 `knowledge/index.html`

### 3. 验证输出

确认 `knowledge/index.html` 已生成且包含：
- 搜索框（按标题、摘要、标签实时过滤）
- 倒序排列的文章卡片列表
- 每条卡片展示：**标题**（可点击跳转 source_url）、**摘要**、**评分/来源/stars/语言**、**标签**、**评分理由（score_reason）**
- Dark 风格（GitHub 配色：`#0d1117` 背景，`#161b22` 卡片）
- 评分着色：≥8 绿色、6-7 黄色、<6 红色

## 页面效果

```
┌─────────────────────────────────────────────┐
│  AI 技术知识库                               │
│  自动采集 · LLM 分析 · 每日更新               │
│  [搜索标题、摘要、标签...               ]     │
│  显示 88 / 88 条                             │
│                                             │
│  ┌─ 卡片 ────────────────────────────────┐  │
│  │  owner/repo (可点击跳转 GitHub)        │  │
│  │  中文摘要描述项目核心功能...            │  │
│  │  8/10 | github-trending | ⭐5000 | Py │  │
│  │  [AI/Agent] [LLM/推理优化]             │  │
│  │  评分理由：打破封闭生态，提供多后端...   │  │
│  └──────────────────────────────────────┘  │
│  ...                                        │
└─────────────────────────────────────────────┘
```

## 注意事项

- 页面为纯静态 HTML，无外部依赖，可直接用浏览器打开
- 数据以 JSON 形式嵌入 HTML，无需 HTTP 服务器
- 若文章数量超过 200 条，建议考虑分页或虚拟滚动
- 修改 `generate_index.py` 中的 CSS 变量可调整主题色
