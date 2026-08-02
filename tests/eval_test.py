"""AI knowledge pipeline evaluation tests.

Run:
  pytest tests/eval_test.py -v                       # fast tests only
  pytest tests/eval_test.py -v -m slow               # include LLM tests
  pytest tests/eval_test.py -v -m "not slow"         # skip LLM tests
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

import pytest
from dotenv import load_dotenv

# Load .env early for LLM_API_KEY (non-fatal if missing)
load_dotenv()

# Ensure the project root is on sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

# Silence PytestUnknownMarkWarning for the custom "slow" marker
pytest_plugins: list[str] = []


def pytest_configure(config: pytest.Config) -> None:
    config.addinivalue_line("markers", "slow: marks test as slow (LLM calls)")


# ======================================================================
# EVAL_CASES — structured test scenarios
# ======================================================================

EVAL_CASES = [
    # ---- Positive: high-quality tech input ----
    {
        "name": "positive-agent-framework",
        "input": {
            "title": "myorg/agent-core",
            "description": (
                "A production-ready multi-agent orchestration framework "
                "supporting tool-use, memory, and planning. Built on top of "
                "langchain with native OpenAI/Anthropic/Gemini backends. "
                "Features include streaming, structured output, and human-in-the-loop."
            ),
            "language": "Python",
            "stars": 4200,
        },
        "expected": {
            "summary_length": (5, 50),       # Chinese summary 5-50 chars
            "implies": ["智能体", "框架"],    # Chinese keywords for Chinese summary
            "score_range": (4, 10),
            "tags_non_empty": True,
        },
    },
    # ---- Positive: well-known framework ----
    {
        "name": "positive-llm-inference",
        "input": {
            "title": "vllm/vllm",
            "description": (
                "A high-throughput and memory-efficient inference engine "
                "for LLMs with PagedAttention, continuous batching, and "
                "tensor parallelism. Supports 40+ model architectures."
            ),
            "language": "Python",
            "stars": 38000,
        },
        "expected": {
            "summary_length": (5, 50),
            "implies": ["LLM", "推理"],
            "score_range": (6, 10),
            "tags_non_empty": True,
        },
    },
    # ---- Negative: irrelevant content ----
    {
        "name": "negative-non-tech",
        "input": {
            "title": "myorg/hello-world",
            "description": (
                "Just a test repo for learning git. Nothing to see here. "
                "Contains a single README with my name."
            ),
            "language": "Markdown",
            "stars": 1,
        },
        "expected": {
            "summary_length": (1, 50),
            "implies": [],
            "score_range": (1, 5),
            "tags_non_empty": False,
        },
    },
    # ---- Negative: spam / marketing fluff ----
    {
        "name": "negative-spam",
        "input": {
            "title": "crypto-bot/free-money",
            "description": (
                "🚀🚀🚀 Get rich quick with our revolutionary blockchain AI! "
                "1000x returns guaranteed! Join now before it's too late!!!"
            ),
            "language": "JavaScript",
            "stars": 0,
        },
        "expected": {
            "summary_length": (1, 50),
            "implies": [],
            "score_range": (1, 4),
            "tags_non_empty": False,
        },
    },
    # ---- Edge: minimal input ----
    {
        "name": "edge-minimal",
        "input": {
            "title": "x/ai",
            "description": "AI",
            "language": "",
            "stars": 10,
        },
        "expected": {
            "summary_length": (0, 50),
            "implies": [],
            "score_range": (1, 10),
            "tags_non_empty": False,
        },
    },
    # ---- Edge: empty fields ----
    {
        "name": "edge-empty-fields",
        "input": {
            "title": "",
            "description": "",
            "language": "",
            "stars": 0,
        },
        "expected": {
            "summary_length": (0, 50),
            "implies": [],
            "score_range": (1, 10),
            "tags_non_empty": False,
        },
    },
]


def _check_expected(result: dict, expected: dict) -> None:
    """Run range-based assertions on an analysis result."""
    summary = result.get("summary", "")

    # summary length
    lo, hi = expected.get("summary_length", (0, 100))
    assert lo <= len(summary) <= hi, (
        f"summary length {len(summary)} not in [{lo}, {hi}]: {summary}"
    )

    # implied keywords (at least one must appear)
    for kw in expected.get("implies", []):
        assert kw.lower() in summary.lower(), (
            f"summary must imply '{kw}': {summary}"
        )

    # score range
    score = result.get("score", 0)
    lo_s, hi_s = expected.get("score_range", (0, 10))
    assert lo_s <= score <= hi_s, f"score {score} not in [{lo_s}, {hi_s}]"

    # tags non-empty (when expected)
    tags = result.get("tags", [])
    if expected.get("tags_non_empty", False):
        assert len(tags) > 0, "tags must not be empty for this case"


# ======================================================================
# Fast test: EVAL_CASES structure (no LLM)
# ======================================================================

class TestEvalCasesStructure:
    """Verify EVAL_CASES are well-formed (no LLM calls)."""

    REQUIRED_INPUT_KEYS = {"title", "description", "language", "stars"}
    REQUIRED_EXPECTED_KEYS = {"summary_length", "implies", "score_range", "tags_non_empty"}

    @pytest.mark.parametrize("case", EVAL_CASES, ids=lambda c: c["name"])
    def test_case_has_required_keys(self, case: dict) -> None:
        assert "name" in case, "missing name"
        assert "input" in case, "missing input"
        assert "expected" in case, "missing expected"

        missing_input = self.REQUIRED_INPUT_KEYS - case["input"].keys()
        assert not missing_input, f"input missing keys: {missing_input}"

        missing_expected = self.REQUIRED_EXPECTED_KEYS - case["expected"].keys()
        assert not missing_expected, f"expected missing keys: {missing_expected}"

    def test_positive_cases_exist(self) -> None:
        pos = [c for c in EVAL_CASES if "positive" in c["name"]]
        assert len(pos) >= 2, "need at least 2 positive cases"

    def test_negative_cases_exist(self) -> None:
        neg = [c for c in EVAL_CASES if "negative" in c["name"]]
        assert len(neg) >= 2, "need at least 2 negative cases"

    def test_edge_cases_exist(self) -> None:
        edge = [c for c in EVAL_CASES if "edge" in c["name"]]
        assert len(edge) >= 2, "need at least 2 edge cases"

    def test_expected_ranges_are_valid(self) -> None:
        for case in EVAL_CASES:
            exp = case["expected"]
            lo, hi = exp["summary_length"]
            assert 0 <= lo <= hi <= 100, f"invalid summary_length range: [{lo}, {hi}]"
            lo_s, hi_s = exp["score_range"]
            assert 1 <= lo_s <= hi_s <= 10, f"invalid score_range: [{lo_s}, {hi_s}]"


# ======================================================================
# Slow test: pipeline eval via LLM-analyze + assertion
# ======================================================================

# Keep a cache per session to avoid re-analyzing the same input
_ANALYZE_CACHE: dict[str, dict] = {}


def _run_analyze(test_input: dict) -> dict:
    """Call analyze_node on a single item. (session-scoped cache)"""
    key = json.dumps(test_input, sort_keys=True)
    if key in _ANALYZE_CACHE:
        return _ANALYZE_CACHE[key]

    from workflows.model_client import chat_json
    from workflows.state import new_state
    from workflows.nodes import analyze_node

    state = new_state(
        sources=[{
            "name": test_input["title"],
            "description": test_input["description"],
            "url": f"https://github.com/{test_input['title']}",
            "stars": test_input["stars"],
            "language": test_input["language"],
        }]
    )
    result = analyze_node(state)
    analyses = result.get("analyses", [])
    item = analyses[0] if analyses else {"summary": "", "tags": [], "score": 1}
    _ANALYZE_CACHE[key] = item
    return item


@pytest.mark.slow
class TestPipelineEval:
    """End-to-end evaluation through analyze_node (LLM calls)."""

    @pytest.mark.parametrize("case", EVAL_CASES, ids=lambda c: c["name"])
    def test_case_against_expectations(self, case: dict) -> None:
        result = _run_analyze(case["input"])
        _check_expected(result, case["expected"])


# ======================================================================
# Slow test: LLM-as-Judge (meta-evaluation)
# ======================================================================

JUDGE_SYSTEM = (
    "你是一个 AI 知识库评估专家。你会收到一条技术项目的分析结果（中文摘要、标签、评分）。"
    "请评估该分析的整体质量，仅返回 JSON：\n"
    '{"score": <1-10>, "reason": "<一句话评价>"}'
    "评分标准：1-3 差（摘要不相关/格式错误），4-6 一般（可接受但有改进空间），"
    "7-8 好（准确简洁），9-10 优秀（高度凝练、标签精准）。"
)

JUDGE_CASES = [
    # High-quality input expected to score well
    {
        "name": "judge-vllm-analysis",
        "input": {
            "title": "vllm/vllm",
            "description": "High-throughput LLM inference engine with PagedAttention",
            "language": "Python",
            "stars": 38000,
        },
    },
    {
        "name": "judge-agent-analysis",
        "input": {
            "title": "langchain-ai/langgraph",
            "description": "Build stateful, multi-actor applications with LLMs",
            "language": "Python",
            "stars": 12000,
        },
    },
]


@pytest.mark.slow
class TestLLMJudge:
    """LLM-as-Judge: meta-evaluate the pipeline output quality."""

    @pytest.mark.parametrize("case", JUDGE_CASES, ids=lambda c: c["name"])
    def test_judge_score_above_threshold(self, case: dict) -> None:
        from workflows.model_client import chat_json

        # Step 1: run analyze_node
        analysis = _run_analyze(case["input"])

        # Step 2: LLM judge evaluates the analysis
        prompt = (
            f"标题：{analysis.get('title', '')}\n"
            f"摘要：{analysis.get('summary', '')}\n"
            f"标签：{', '.join(analysis.get('tags', []))}\n"
            f"评分：{analysis.get('score', 0)}"
        )
        judge_result, _ = chat_json(prompt, system=JUDGE_SYSTEM)

        score = judge_result.get("score", 0)
        reason = judge_result.get("reason", "")

        assert isinstance(score, (int, float)), f"judge score must be numeric, got {score}"
        assert score >= 5, (
            f"LLM judge scored below threshold: {score}/10\n"
            f"input: {case['input']['title']}\n"
            f"analysis: {json.dumps(analysis, ensure_ascii=False)}\n"
            f"reason: {reason}"
        )

    def test_all_judge_cases_analyzed(self) -> None:
        """Pre-warm: ensure all judge inputs are analyzed (no crash)."""
        for case in JUDGE_CASES:
            result = _run_analyze(case["input"])
            assert "summary" in result
            assert "score" in result
            assert isinstance(result["score"], int)
