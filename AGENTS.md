# AGENTS.md

## 仓库概览

AI 技术动态知识库，通过四阶段 Agent 流水线自动采集、分析、整理 GitHub/Hacker News 热门项目。

## 目录结构

```
.opencode/agents/           Agent 定义（collector → analyzer → organizer）
.opencode/skills/            可复用技能（github-trending / tech-summary / generate-static / git-commit）
knowledge/raw/               流水线中间产物（采集结果 + 分析报告）
knowledge/articles/          最终知识条目（去重、格式化、按日归档）
knowledge/index.html         自包含静态数据展示页（organizer 完成后生成）
knowledge/generate_index.py  静态页生成脚本
patterns/                    Router / Supervisor 模式实现
workflows/                   LangGraph 工作流（model_client / state / nodes / graph）
tests/                       评估测试
pipeline/                    主流水线（model_client + pipeline.py）
hooks/                       JSON 验证脚本
opencode.json               MCP 配置
```

## Agent 流水线

| 阶段 | Agent | 输入 | 输出 | 禁止 |
|------|-------|------|------|------|
| 1. 采集 | `collector` | GitHub API / HN API | `knowledge/raw/github-trending-{date}.json` | Write, Edit, Bash |
| 2. 分析 | `analyzer` | `knowledge/raw/` 最新文件 | `knowledge/raw/tech-summary-{date}.json` | Write, Edit, Bash |
| 3. 整理 | `organizer` | 分析结果 | `knowledge/articles/{date}-{source}-{slug}.json` | WebFetch, Bash |
| 4. 展示 | `generate-static` | `knowledge/articles/` 全部 JSON | `knowledge/index.html` | WebFetch |

`collector` / `analyzer` 不能写文件，需由调用者保存输出。organizer 完成后必须运行：

```bash
python3 knowledge/generate_index.py
```

## 常用命令

```bash
# 运行完整管线
python3 pipeline/pipeline.py --sources github --limit 20

# 仅生成静态页面
python3 knowledge/generate_index.py

# 运行测试（排除 LLM 调用）
pytest tests/ -v -m "not slow"

# 运行全部测试（含 LLM）
PYTHONPATH=. pytest tests/ -v

# LangGraph 流式执行（mock 数据，不调 API）
PYTHONPATH=. python3 workflows/test_review_loop.py
```

## model_client API（关键）

```python
from workflows.model_client import chat, chat_json, accumulate_usage

# prompt 在前，system 为 keyword-only
text, usage = chat(prompt, system="...")           # → (str, dict)
result, usage = chat_json(prompt, system="...")    # → (dict, dict)
accumulate_usage(tracker, usage)                    # 累加 token 统计
```

## 数据格式约束

- **摘要**：纯中文，≤50 字（Unicode 码点）
- **标签**：`分类/子分类` 层级格式（如 `LLM/推理优化`、`AI/Agent`）
- **评分**：1-10，每批 15 个中 9-10 分 ≤2 个
- **文件名**：`{date}-{source}-{slug}.json`，slug 仅小写字母、数字、连字符
- **去重**：按 `source_url` 去重

## GitHub API 注意事项

- 必须 `User-Agent` 头，否则 403；未认证限速 10/min
- `created` 日期用 ISO 8601（`>=YYYY-MM-DD`）
- WebFetch 页面可能超时，改用 `api.github.com` 端点
- **SSL 错误**：某些环境缺 CA 证书，`nodes.py` 的 `collect_node` 会自动回退到 `ssl._create_unverified_context`

## 写作约定

- 回复使用中文，注释使用英文
- 摘要聚焦项目价值，避免营销化表述

## 红线

- **不编造数据** — 不杜撰不存在的项目、URL、star 数、评分或其他数据
- **不泄露密钥** — 日志/输出/代码中不输出 API Key、Token、密码
- **不执行危险命令** — 不使用 `rm -rf`、`git push --force`、磁盘格式化
- **不改 Git 配置** — 不改 `git config`、remote URL、`~/.gitconfig`，除非用户明确要求
