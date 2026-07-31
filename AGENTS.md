# AGENTS.md

## 仓库概览

AI 技术动态知识库，通过三阶段 Agent 流水线自动采集、分析、整理 GitHub/Hacker News 热门项目。

## 目录结构

```
.opencode/agents/         Agent 定义（collector → analyzer → organizer）
.opencode/skills/          可复用技能（github-trending, tech-summary）
knowledge/raw/             流水线中间产物（采集结果 + 分析报告）
knowledge/articles/        最终知识条目（去重、格式化、按日归档）
```

## Agent 流水线（必须按序执行）

| 阶段 | Agent | 输入 | 输出 | 禁止 |
|------|-------|------|------|------|
| 1. 采集 | `collector` | GitHub API / HN API | `knowledge/raw/github-trending-{date}.json` | Write, Edit, Bash |
| 2. 分析 | `analyzer` | `knowledge/raw/` 最新文件 | `knowledge/raw/tech-summary-{date}.json` | Write, Edit, Bash |
| 3. 整理 | `organizer` | 分析结果 | `knowledge/articles/{date}-{source}-{slug}.json` | WebFetch, Bash |

`collector` 和 `analyzer` 不能写文件 — 需由调用者（用户或 orchestrator）将输出保存到目标路径。

## 数据格式关键约束

- **摘要**：纯中文，≤50 字（`len()` 按 Unicode 码点计）
- **标签**：`分类/子分类` 层级格式（如 `LLM/推理优化`、`AI/Agent`）
- **评分**：1-10 分制，每批 15 个项目中 9-10 分不超过 2 个
- **文件命名**：`{date}-{source}-{slug}.json`，slug 仅含小写字母、数字、连字符
- **去重依据**：`source_url` 字段，已有相同 URL 则跳过

## GitHub API 注意事项

- 必须设置 `User-Agent` 请求头，否则返回 403
- 未认证限速 10 次/分钟，有 Token 可提高
- `created` 日期参数使用 ISO 8601（`>=YYYY-MM-DD`）
- `WebFetch` 访问项目页面可能超时，改用 `raw.githubusercontent.com` 路径或 API 端点

## 写作约定

- 回复使用中文
- 注释使用英文
- 摘要聚焦项目价值，避免营销化表述

## 红线（绝对不可违反）

- **不编造数据** — 不杜撰不存在的项目、URL、star 数、benchmark 分数或其他任何数据
- **不泄露密钥** — 不在日志、输出或代码中输出 API Key、Token、密码等敏感信息
- **不执行危险命令** — 不使用 `rm -rf`、`git push --force`、磁盘格式化等不可逆操作
- **不改 AGENTS.md** — 除非用户明确要求，不修改本文件
- **不改 Git 配置** — 不修改 `git config`、remote URL、`~/.gitconfig` 或其他 Git 设置，除非用户明确要求
