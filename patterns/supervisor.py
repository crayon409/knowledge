"""Supervisor agent pattern: worker → review → retry (max 3 rounds).

Worker produces JSON analysis reports. Supervisor scores on accuracy/depth/format.
Pass threshold: score >= 7. Max 3 retries with feedback on failure.
"""

from __future__ import annotations

import json
import re
import textwrap

from workflows.model_client import chat

# ======================================================================
# Worker Agent
# ======================================================================

WORKER_SYSTEM = textwrap.dedent("""\
    你是一位专家分析师。收到任务后，输出一份结构清晰的分析报告，必须为 JSON 格式：

    {
      "summary": "任务分析摘要（≤100字）",
      "key_points": ["要点1", "要点2", "要点3"],
      "detailed_analysis": "详细分析（分段，每条论点有依据）",
      "references": ["参考来源1", "参考来源2"]
    }

    要求：
    - 分析需有深度，提供具体论据而非泛泛而谈
    - JSON 格式严格正确，key/values 用双引号
    - 仅输出 JSON，不加任何前缀或后缀
""")


def _worker(task: str, feedback: str = "") -> str:
    """Run worker agent to produce analysis JSON for a task.

    Args:
        task: The task description.
        feedback: Optional supervisor feedback from a previous attempt.

    Returns:
        Raw text output from the LLM (expected to be JSON).
    """
    prompt = f'任务：{task}'
    if feedback:
        prompt += f'\n\n上一轮审核反馈：{feedback}\n请根据反馈改进你的分析报告，确保 JSON 格式正确。'

    text, _ = chat(WORKER_SYSTEM, prompt, temperature=0.7)
    return text


# ======================================================================
# Supervisor Agent
# ======================================================================

SUPERVISOR_SYSTEM = textwrap.dedent("""\
    你是一位严苛的质量审核员。你会收到一份分析报告（JSON 格式），请从三个维度评分：

    - accuracy (1-10)：事实准确性，有无明显错误或编造
    - depth (1-10)：分析深度，是否给出具体论据而非空泛
    - format (1-10)：JSON 格式是否严格合法、结构清晰

    综合分 score = round((accuracy + depth + format) / 3)

    passed = true 当且仅当 score >= 7

    仅返回 JSON，不加前缀或后缀：
    {"passed": bool, "score": int, "feedback": "不通过时的改进建议（通过时为空字符串）", "accuracy": int, "depth": int, "format": int}
""")


def _supervisor(report: str) -> dict:
    """Evaluate a worker's analysis report.

    Args:
        report: Raw worker output (expected to be JSON).

    Returns:
        Dict with keys: passed, score, feedback, accuracy, depth, format.
    """
    prompt = f'请审核以下分析报告：\n\n{report}'
    text, _ = chat(SUPERVISOR_SYSTEM, prompt, temperature=0.3)

    # Parse supervisor JSON
    parsed = _extract_json(text)
    return {
        "passed": parsed.get("passed", False),
        "score": parsed.get("score", 0),
        "feedback": parsed.get("feedback", ""),
        "accuracy": parsed.get("accuracy", 0),
        "depth": parsed.get("depth", 0),
        "format": parsed.get("format", 0),
    }


# ======================================================================
# JSON extraction helper
# ======================================================================


def _extract_json(text: str) -> dict:
    """Robust JSON extraction from LLM output (supports ``` fences)."""
    # ```json fence
    m = re.search(r'```(?:json)?\s*(\{.*?\})\s*```', text, re.DOTALL)
    if m:
        try:
            return json.loads(m.group(1))
        except json.JSONDecodeError:
            pass

    # Bare JSON object
    m = re.search(r'\{.*\}', text, re.DOTALL)
    if m:
        try:
            return json.loads(m.group())
        except json.JSONDecodeError:
            pass

    # Full text
    try:
        return json.loads(text.strip())
    except json.JSONDecodeError:
        pass

    return {}


def _parse_worker_report(text: str) -> dict:
    """Parse worker output into a dict, with fallback."""
    parsed = _extract_json(text)
    if not parsed:
        parsed = {"raw": text, "summary": "JSON 解析失败", "key_points": [], "detailed_analysis": text}
    return parsed


# ======================================================================
# Main supervisor loop
# ======================================================================


def supervisor(task: str, max_retries: int = 3) -> dict:
    """Run the supervisor-agent loop: worker produces, supervisor reviews.

    Args:
        task: The analysis task description.
        max_retries: Maximum review rounds (default 3). Includes the first attempt.

    Returns:
        Dict with:
          - output: Final worker report (parsed dict)
          - score: Final supervisor score (int)
          - passed: Whether it passed review
          - attempts: Number of worker runs
          - feedback: Last supervisor feedback
          - warning: Present only if max_retries exhausted without passing
    """
    feedback = ""
    last_report_raw = ""
    last_review: dict = {}

    for attempt in range(1, max_retries + 1):
        # Step 1: Worker runs
        report_raw = _worker(task, feedback)
        last_report_raw = report_raw

        # Step 2: Supervisor reviews
        review = _supervisor(report_raw)
        last_review = review

        if review.get("passed"):
            return {
                "output": _parse_worker_report(report_raw),
                "score": review["score"],
                "passed": True,
                "attempts": attempt,
                "feedback": review.get("feedback", ""),
                "dimensions": {
                    "accuracy": review.get("accuracy", 0),
                    "depth": review.get("depth", 0),
                    "format": review.get("format", 0),
                },
            }

        # Step 3: Not passed → prepare feedback for next round
        feedback = review.get("feedback", "请改进分析质量。")

    # Exceeded max retries → force return with warning
    return {
        "output": _parse_worker_report(last_report_raw),
        "score": last_review.get("score", 0),
        "passed": False,
        "attempts": max_retries,
        "feedback": last_review.get("feedback", ""),
        "dimensions": {
            "accuracy": last_review.get("accuracy", 0),
            "depth": last_review.get("depth", 0),
            "format": last_review.get("format", 0),
        },
        "warning": f"超过最大重试次数 ({max_retries})，强制返回最终结果",
    }


# ======================================================================
# CLI smoke test
# ======================================================================

if __name__ == "__main__":
    TASK = "分析Python中异步编程(asyncio)的核心概念和最佳实践"

    print(f"Task: {TASK}\n")

    result = supervisor(TASK, max_retries=3)

    print(f"Passed:    {result['passed']}")
    print(f"Score:     {result['score']}/10")
    print(f"Attempts:  {result['attempts']}")
    dims = result.get("dimensions", {})
    if dims:
        print(f"Accuracy:  {dims.get('accuracy', '-')}")
        print(f"Depth:     {dims.get('depth', '-')}")
        print(f"Format:    {dims.get('format', '-')}")
    if result.get("warning"):
        print(f"WARNING:   {result['warning']}")
    if result.get("feedback"):
        print(f"Feedback:  {result['feedback']}")

    output = result["output"]
    print(f"\n--- Analysis Output ---")
    print(json.dumps(output, ensure_ascii=False, indent=2))
