---
name: github-trending
description: 当需要采集 Github 热门开源项目时使用此技能
allowed-tools: Read, Grep, Glob, Webfetch
---

# GitHub Trending 项目采集技能

## 使用场景

当需要从 GitHub 获取当前热门开源项目，筛选与 AI/LLM/Agent 相关的项目，并输出结构化 JSON 时使用此技能。

## 执行步骤

### 1. 搜索热门仓库

使用 GitHub Search API 搜索近期（默认最近7天）创建且获得较多 star 的仓库：

```
https://api.github.com/search/repositories?q=created:>=YYYY-MM-DD&sort=stars&order=desc&per_page=100
```

必要时分页获取更多结果。

### 2. 提取信息

从 API 返回结果中提取以下字段：
- `full_name`（仓库全名）
- `html_url`（仓库地址）
- `description`（项目描述）
- `stargazers_count`（star 数）
- `language`（主要编程语言）
- `topics`（主题标签）

### 3. 过滤

纳入满足以下条件的项目：
- 标题、描述或 topics 中包含 AI、LLM、Agent、GPT、RAG、Machine Learning、Deep Learning、NLP 等关键词

排除以下项目：
- 标题包含 "awesome" 的整理类列表仓库
- 纯教程/课程类仓库（tutorial、course 等）
- 已归档或长期不活跃的仓库

### 4. 去重

按 `full_name` 去重，若同一仓库出现在多页结果中，仅保留一次。

### 5. 撰写中文摘要

为每个通过筛选的项目撰写中文摘要，公式：

> **项目名** + 做什么 + 为什么值得关注

摘要需简洁（50字以内），突出项目核心功能与亮点，使用中文描述。

### 6. 排序取 Top 15

按 star 数从高到低排序，取前 15 个项目。

### 7. 输出 JSON

将结果输出到 `knowledge/raw/github-trending-YYYY-MM-DD.json`，格式见下方「输出格式」。

## 注意事项

- API 请求需设置 `User-Agent` 头，否则会返回 403
- GitHub Search API 未认证时限速为每分钟 10 次请求，如有 Token 建议使用认证请求提高限额
- `created` 参数使用 ISO 8601 日期格式（如 `2024-01-01`）
- 仅采集公开仓库信息，不涉及任何私有数据
- 摘要应聚焦项目本身价值，避免营销化表述

## 输出格式

JSON 文件结构如下：

```json
{
  "source": "GitHub Search API",
  "skill": "github-trending",
  "collected_at": "YYYY-MM-DDTHH:mm:ssZ",
  "items": [
    {
      "name": "owner/repo",
      "url": "https://github.com/owner/repo",
      "summary": "中文摘要：项目做什么 + 为什么值得关注",
      "stars": 1234,
      "language": "Python",
      "topics": ["llm", "agent", "rag"]
    }
  ]
}
```
