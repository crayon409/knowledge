---
name: tech-summary
description: 当需要对采集的技术内容进行深度分析总结时使用此技能
allowed-tools: Read, Grep, Glob, WebFetch
---

# 技术内容深度分析总结技能

## 使用场景

当已完成 GitHub Trending 项目采集，需要对 `knowledge/raw/` 中的数据进行逐条深度分析、评分、趋势发现并输出结构化分析报告时使用此技能。

## 执行步骤

### 1. 读取最新采集文件

扫描 `knowledge/raw/` 目录，按文件名中的日期排序，读取最新的 `github-trending-YYYY-MM-DD.json` 文件：

```
knowledge/raw/github-trending-*.json
```

解析其中的 `items` 数组，作为后续分析的输入数据。

### 2. 逐条深度分析

对 `items` 中的每个项目进行以下维度的分析：

**a) 中文摘要（≤ 50 字）**

在原始摘要基础上精炼，用更准确的术语重新概括，保持简洁。

**b) 技术亮点（2-3 个）**

从项目 README、代码结构、技术架构中提取亮点，用事实说话：
- 引用具体的性能数据（如吞吐量、延迟、准确率）
- 引用架构特色（如插件机制、多模态支持、分布式设计）
- 引用生态兼容性（如兼容 OpenAI API、支持主流框架）

**c) 评分（1-10 分，附理由）**

依据以下标准打分，并用一句话说明理由：

| 分数区间 | 含义 | 典型特征 |
| -------- | ---- | -------- |
| 9-10 | 改变格局 | 范式级创新、解决行业痛点、具备生态颠覆潜力 |
| 7-8 | 直接有帮助 | 可立刻用于生产，补足现有工具链明显短板 |
| 5-6 | 值得了解 | 有亮点但尚不成熟，或针对特定细分领域 |
| 1-4 | 可略过 | 功能同质化严重、文档缺失、活跃度低 |

**重要约束：15 个项目中评分 9-10 分的不超过 2 个。**

**d) 标签建议**

为项目推荐 3-5 个标签，格式为 `分类/子分类`，例如：
- `AI/Agent`、`LLM/推理优化`、`RAG/向量检索`
- `前端/UI框架`、`工具/DevOps`、`数据/ETL`

### 3. 趋势发现

基于全部项目的分析结果，归纳本期趋势：

**a) 共同主题（2-3 个）**

识别多个项目共同聚焦的方向，例如：多 Agent 协作、本地化 LLM 部署、评估基准的标准化等。每个主题说明涉及的仓库数量及代表性项目。

**b) 新概念（1-2 个）**

发现本期内新兴的技术范式、架构模式或方法论，上述共同主题之外的，说明其来源项目及含义。

### 4. 输出分析结果 JSON

将分析结果写入 `knowledge/raw/tech-summary-YYYY-MM-DD.json`，格式见下方「输出格式」。文件名日期与输入文件保持一致。

## 注意事项

- 分析前需通过 WebFetch 访问项目 GitHub 页面，获取 README 和技术细节，不可仅凭原始摘要臆断
- 评分严格遵循标准，避免"高分通胀"，9-10 分项目必须有充分的技术突破性依据
- 技术亮点必须引用具体数据或特性，禁止模糊表述（如"性能好""功能多"等笼统评价）
- 趋势发现须有据可查，至少关联 2 个以上项目的共性问题才算"共同主题"
- 若输入文件 `items` 数量不足 15，按实际数量分析即可；超过 15 则取前 15

## 输出格式

```json
{
  "source": "tech-summary skill",
  "skill": "tech-summary",
  "analyzed_at": "YYYY-MM-DDTHH:mm:ssZ",
  "input_file": "knowledge/raw/github-trending-YYYY-MM-DD.json",
  "analysis": [
    {
      "name": "owner/repo",
      "url": "https://github.com/owner/repo",
      "summary": "精炼中文摘要，≤50字",
      "highlights": [
        "具体技术亮点1，引用数据或特性",
        "具体技术亮点2，引用数据或特性",
        "具体技术亮点3（可选）"
      ],
      "score": 8,
      "score_reason": "一句话给出评分理由",
      "tags": ["LLM/推理优化", "AI/Agent"]
    }
  ],
  "trends": {
    "themes": [
      {
        "name": "共同主题名称",
        "description": "该主题的描述，说明为什么这是一股趋势",
        "related_projects": 5,
        "representatives": ["owner/repo-a", "owner/repo-b"]
      }
    ],
    "new_concepts": [
      {
        "name": "新概念名称",
        "description": "该概念的含义说明",
        "source_project": "owner/repo"
      }
    ]
  }
}
```
