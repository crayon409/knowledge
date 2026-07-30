#!/usr/bin/env python3
"""
Quality scoring for knowledge article JSON files.

Scoring dimensions (weighted total 100 points):
  Summary quality  — 25 pts
  Technical depth  — 25 pts
  Format compliance — 20 pts
  Tag precision    — 15 pts
  Buzzy-word check — 15 pts

Grades: A (≥80), B (≥60), C (<60).  Exit 1 if any file grades C.
"""

import json
import re
import sys
from calendar import monthrange
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

# ---------------------------------------------------------------------------
# Standard tag vocabulary (category → allowed sub-tags)
# ---------------------------------------------------------------------------
STANDARD_TAGS: dict[str, set[str]] = {
    "AI": {
        "Agent", "Agent基础设施", "Agent工程", "Agent工作流",
        "Agent可观测性", "Agent优化", "Agent编排", "Agent工具链",
        "多模态", "编码Agent", "Prompt工程", "文本生成",
        "代码生成", "强化学习", "推理部署", "推理优化",
        "边缘推理", "安全研究", "模型安全",
    },
    "LLM": {
        "开源大模型", "MoE架构", "MoE训练", "推理优化",
        "推理部署", "后训练", "模型压缩", "模型部署",
        "本地推理", "上下文管理", "安全对齐", "成本管理",
        "数据工程", "多提供商",
    },
    "工具": {"DevOps", "CLI", "开发效率", "内容创作", "测试工程"},
    "硬件": {"嵌入式AI", "Apple Silicon"},
    "基础设施": {"容器化", "GPU通信", "分布式训练"},
    "游戏": {"WebGL"},
    "数据": {"提示词收集"},
    "Rust": {"系统编程"},
}

# ---------------------------------------------------------------------------
# Buzzword blacklists
# ---------------------------------------------------------------------------
BUZZWORDS_CN: set[str] = {
    "赋能", "抓手", "闭环", "打通", "全链路",
    "底层逻辑", "颗粒度", "对齐", "拉通", "沉淀",
    "强大的", "革命性的",
}
BUZZWORDS_EN: set[str] = {
    "groundbreaking", "revolutionary", "game-changing",
    "cutting-edge", "state-of-the-art", "best-in-class",
    "innovative", "disruptive", "paradigm-shifting",
    "next-generation", "world-class", "industry-leading",
}
BUZZ_PATTERN = re.compile(
    "|".join(
        re.escape(w) for w in sorted(
            BUZZWORDS_CN | BUZZWORDS_EN, key=len, reverse=True
        )
    ),
    re.IGNORECASE,
)

# ---------------------------------------------------------------------------
# Technical keyword bonus (summary quality)
# ---------------------------------------------------------------------------
TECH_KEYWORDS: set[str] = {
    "MoE", "RLHF", "RL", "LoRA", "KV", "GPU", "API",
    "RAG", "SFT", "PPO", "GRPO", "MCP", "CUDA",
    "推理", "训练", "部署", "量化", "架构",
    "attention", "transformer", "嵌入式", "model",
    "SGLang", "Megatron", "基准", "benchmark",
    "token", "开源", "参数", "Agent", "LLM",
}

# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------


@dataclass
class DimensionScore:
    name: str
    score: float
    max_score: float
    details: list[str] = field(default_factory=list)


@dataclass
class QualityReport:
    file_path: str
    dimensions: list[DimensionScore]
    total_score: float
    max_total: int = 100
    grade: str = ""
    errors: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# File collection
# ---------------------------------------------------------------------------


def collect_files(args: list[str]) -> list[Path]:
    files: list[Path] = []
    for arg in args:
        path = Path(arg)
        if any(c in path.name for c in "*?["):
            matched = sorted(Path().glob(arg))
            if not matched:
                sys.stderr.write(f"No files matched pattern: {arg}\n")
            files.extend(matched)
        elif path.is_file():
            files.append(path)
        else:
            sys.stderr.write(f"File not found: {path}\n")
    return files


def parse_article(path: Path) -> dict[str, Any] | None:
    try:
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
    except (json.JSONDecodeError, OSError):
        return None
    return data if isinstance(data, dict) else None


# ---------------------------------------------------------------------------
# Dimension 1: Summary quality (25 pts)
# ---------------------------------------------------------------------------

_SUMMARY_MAX = 25


def _score_summary(data: dict[str, Any]) -> DimensionScore:
    details: list[str] = []
    summary: str = data.get("summary", "")
    length = len(summary)

    if length >= 50:
        length_score = _SUMMARY_MAX
        details.append(f"length {length} chars → full marks")
    elif length >= 20:
        length_score = round((length - 20) / 30 * _SUMMARY_MAX, 1)
        details.append(f"length {length} chars → {length_score}/{_SUMMARY_MAX}")
    else:
        length_score = 0
        details.append(f"length {length} chars (<20) → {length_score}/{_SUMMARY_MAX}")

    bonus = 0
    if summary:
        lower = summary.lower()
        found = [kw for kw in TECH_KEYWORDS if kw.lower() in lower]
        bonus = min(len(found) * 1, 5)  # max 5 bonus, adjusted into total cap
        if found:
            details.append(f"tech keywords found ({len(found)}): {', '.join(found[:5])}")

    final = min(length_score + bonus, _SUMMARY_MAX)
    return DimensionScore(
        name="摘要质量",
        score=final,
        max_score=_SUMMARY_MAX,
        details=details,
    )


# ---------------------------------------------------------------------------
# Dimension 2: Technical depth (25 pts) — mapped from article score 1→10
# ---------------------------------------------------------------------------

_TECH_MAX = 25


def _score_technical(data: dict[str, Any]) -> DimensionScore:
    details: list[str] = []
    raw_score = data.get("score")

    if raw_score is None:
        details.append("no score field → 0")
        return DimensionScore(
            name="技术深度",
            score=0,
            max_score=_TECH_MAX,
            details=details,
        )

    if not isinstance(raw_score, (int, float)) or raw_score < 1 or raw_score > 10:
        details.append(f"invalid score '{raw_score}' → 0")
        return DimensionScore(
            name="技术深度",
            score=0,
            max_score=_TECH_MAX,
            details=details,
        )

    mapped = round(raw_score / 10 * _TECH_MAX, 1)
    details.append(f"article score {raw_score}/10 → {mapped}/{_TECH_MAX}")

    reason = data.get("score_reason", "")
    if isinstance(reason, str) and len(reason) >= 10:
        details.append("score_reason present and substantive")
    elif not reason:
        details.append("score_reason missing")

    return DimensionScore(
        name="技术深度",
        score=mapped,
        max_score=_TECH_MAX,
        details=details,
    )


# ---------------------------------------------------------------------------
# Dimension 3: Format compliance (20 pts) — 5 items × 4 pts each
# ---------------------------------------------------------------------------

_FMT_MAX = 20
_FMT_ITEM_PTS = 4


def _valid_date(yyyymmdd: str) -> bool:
    try:
        y = int(yyyymmdd[:4])
        m = int(yyyymmdd[4:6])
        d = int(yyyymmdd[6:8])
        _, last = monthrange(y, m)
        return 1 <= d <= last
    except (ValueError, IndexError):
        return False


def _score_format(data: dict[str, Any]) -> DimensionScore:
    details: list[str] = []
    checks: list[tuple[str, bool, str]] = []

    fid = data.get("id", "")
    id_ok = isinstance(fid, str) and bool(fid.strip())
    checks.append(("id", id_ok, repr(fid) if not id_ok else ""))

    title = data.get("title", "")
    title_ok = isinstance(title, str) and bool(title.strip())
    checks.append(("title", title_ok, "" if title_ok else "missing/empty"))

    url = data.get("source_url", "")
    url_ok = isinstance(url, str) and url.startswith(("http://", "https://"))
    checks.append(("source_url", url_ok, repr(url) if not url_ok else ""))

    status = data.get("status", "")
    status_ok = isinstance(status, str) and status in {
        "draft", "review", "published", "archived",
    }
    checks.append(("status", status_ok, repr(status) if not status_ok else ""))

    # timestamp: extract YYYYMMDD from id (format: {source}-{YYYYMMDD}-{NNN})
    t_ok = False
    t_note = "not found in id"
    if isinstance(fid, str):
        m = re.search(r"-(\d{8})-", fid)
        if m:
            yyyymmdd = m.group(1)
            t_ok = _valid_date(yyyymmdd)
            t_note = yyyymmdd if t_ok else f"invalid date {yyyymmdd}"
    checks.append(("timestamp", t_ok, t_note if not t_ok else ""))

    passed = sum(1 for _, ok, _ in checks if ok)
    failed_checks = [(name, note) for name, ok, note in checks if not ok]
    for name, note in failed_checks:
        details.append(f"{name} — {note}")

    return DimensionScore(
        name="格式规范",
        score=passed * _FMT_ITEM_PTS,
        max_score=_FMT_MAX,
        details=details,
    )


# ---------------------------------------------------------------------------
# Dimension 4: Tag precision (15 pts)
# ---------------------------------------------------------------------------

_TAG_MAX = 15


def _is_valid_tag(tag: str) -> bool:
    if "/" not in tag:
        return False
    category, _, sub = tag.partition("/")
    if not category or not sub:
        return False
    allowed = STANDARD_TAGS.get(category)
    return allowed is not None and sub in allowed


def _score_tags(data: dict[str, Any]) -> DimensionScore:
    details: list[str] = []
    tags: list[str] = data.get("tags", [])
    if not isinstance(tags, list):
        details.append("tags is not a list → 0")
        return DimensionScore(
            name="标签精度", score=0, max_score=_TAG_MAX, details=details,
        )

    count = len(tags)
    valid_count = sum(1 for t in tags if isinstance(t, str) and _is_valid_tag(t))
    invalid_tags = [
        t for t in tags if isinstance(t, str) and not _is_valid_tag(t)
    ]

    if count == 0:
        details.append("no tags → 0")
        return DimensionScore(
            name="标签精度", score=0, max_score=_TAG_MAX, details=details,
        )

    # count bonus: 1-3 → best, 4-5 → slight penalty, 6+ → more penalty
    if 1 <= count <= 3:
        count_factor = 1.0
    elif count <= 5:
        count_factor = 0.8
        details.append(f"{count} tags (4-5) → 80% count factor")
    else:
        count_factor = 0.5
        details.append(f"{count} tags (6+) → 50% count factor")

    base_score = round(valid_count / count * _TAG_MAX * count_factor, 1)
    details.append(
        f"{valid_count}/{count} tags match standard vocabulary"
    )
    if invalid_tags:
        details.append(
            f"unrecognized: {', '.join(invalid_tags[:5])}"
        )

    return DimensionScore(
        name="标签精度",
        score=base_score,
        max_score=_TAG_MAX,
        details=details,
    )


# ---------------------------------------------------------------------------
# Dimension 5: Buzzword detection (15 pts)
# ---------------------------------------------------------------------------

_BUZZ_MAX = 15
_BUZZ_PENALTY = 3  # points deducted per buzzword hit


def _score_buzzwords(data: dict[str, Any]) -> DimensionScore:
    details: list[str] = []

    text_fields = [
        data.get("summary", ""),
        data.get("score_reason", ""),
    ]
    highlights = data.get("highlights", [])
    if isinstance(highlights, list):
        text_fields.extend(h for h in highlights if isinstance(h, str))

    combined = " ".join(text_fields)
    hits = BUZZ_PATTERN.findall(combined)

    if hits:
        unique_hits = sorted({h.lower() for h in hits})
        penalty = min(len(unique_hits) * _BUZZ_PENALTY, _BUZZ_MAX)
        details.append(
            f"{len(unique_hits)} unique buzzwords found: {', '.join(unique_hits)}"
        )
    else:
        details.append("no buzzwords detected")

    return DimensionScore(
        name="空洞词检测",
        score=max(_BUZZ_MAX - min(len(set(h.lower() for h in hits)) * _BUZZ_PENALTY, _BUZZ_MAX), 0),
        max_score=_BUZZ_MAX,
        details=details,
    )


# ---------------------------------------------------------------------------
# Report assembly & output
# ---------------------------------------------------------------------------


def _compute_grade(total: float) -> str:
    if total >= 80:
        return "A"
    if total >= 60:
        return "B"
    return "C"


def _progress_bar(value: float, width: int = 30) -> str:
    filled = round(value / 100 * width)
    empty = width - filled
    bar = "█" * filled + "░" * empty
    pct = f"{value:.1f}%".rjust(6)
    return f"{bar} {pct}"


def analyze_file(path: Path) -> QualityReport | None:
    data = parse_article(path)
    if data is None:
        return None

    dimensions = [
        _score_summary(data),
        _score_technical(data),
        _score_format(data),
        _score_tags(data),
        _score_buzzwords(data),
    ]
    total = round(sum(d.score for d in dimensions), 1)
    grade = _compute_grade(total)

    return QualityReport(
        file_path=str(path),
        dimensions=dimensions,
        total_score=total,
        grade=grade,
    )


def print_report(report: QualityReport) -> None:
    print(f"\n{'=' * 60}")
    print(f"  {report.file_path}")
    print(f"{'=' * 60}")
    for dim in report.dimensions:
        pct = dim.score / dim.max_score * 100
        bar = _progress_bar(pct, width=20) if dim.max_score > 0 else ""
        label = f"{dim.name}:".ljust(10)
        print(f"  {label} {dim.score:5.1f}/{dim.max_score:3.0f}  {bar}")
        for detail in dim.details:
            print(f"           ↳ {detail}")

    print(f"  {'─' * 56}")
    bar = _progress_bar(report.total_score)
    print(f"  {'总分:':10} {report.total_score:5.1f}/{report.max_total:3d}  {bar}")
    grade_str = f"[{report.grade}]"
    grade_color = {"A": "★", "B": "✓", "C": "✗"}.get(report.grade, "?")
    print(f"  {'等级:':10} {grade_color} {grade_str}")


def main() -> int:
    if len(sys.argv) < 2:
        sys.stderr.write(
            "Usage: python hooks/check_quality.py <json_file> [json_file2 ...]\n"
        )
        return 2

    files = collect_files(sys.argv[1:])
    if not files:
        sys.stderr.write("No JSON files to check.\n")
        return 2

    any_c = False
    parsed_count = 0
    failed_parse = 0

    for filepath in files:
        report = analyze_file(filepath)
        if report is None:
            sys.stderr.write(f"  SKIP: {filepath} — cannot parse\n")
            failed_parse += 1
            any_c = True  # unparseable counts as failing
            continue
        parsed_count += 1
        print_report(report)
        if report.grade == "C":
            any_c = True

    print(f"\nFiles: {len(files)}  Parsed: {parsed_count}  Failed: {failed_parse}")

    return 1 if any_c else 0


if __name__ == "__main__":
    sys.exit(main())
