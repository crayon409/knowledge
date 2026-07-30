#!/usr/bin/env python3
"""
Validate knowledge article JSON files.

Usage: python hooks/validate_json.py <json_file> [json_file2 ...]
       python hooks/validate_json.py knowledge/articles/*.json
"""

import json
import re
import sys
from pathlib import Path
from typing import Any

REQUIRED_FIELDS: dict[str, type] = {
    "id": str,
    "title": str,
    "source_url": str,
    "summary": str,
    "tags": list,
    "status": str,
}

VALID_STATUSES = {"draft", "review", "published", "archived"}
VALID_AUDIENCES = {"beginner", "intermediate", "advanced"}

ID_PATTERN = re.compile(r"^[a-z][a-z0-9-]*-\d{8}-\d{3}$")
URL_PATTERN = re.compile(r"^https?://")

MIN_SUMMARY_LEN = 20
SCORE_MIN = 1
SCORE_MAX = 10


class ValidationError(Exception):
    pass


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


def parse_json(path: Path) -> dict[str, Any]:
    try:
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
    except json.JSONDecodeError as exc:
        raise ValidationError(f"invalid JSON — {exc}") from exc
    except OSError as exc:
        raise ValidationError(f"read error — {exc}") from exc
    if not isinstance(data, dict):
        raise ValidationError(
            f"top-level must be an object, got {type(data).__name__}"
        )
    return data


def validate_required(data: dict[str, Any], path: Path) -> list[str]:
    errors: list[str] = []
    for field, expected_type in REQUIRED_FIELDS.items():
        if field not in data:
            errors.append(
                f"{path}: missing required field '{field}'"
            )
            continue
        value = data[field]
        if not isinstance(value, expected_type):
            errors.append(
                f"{path}: field '{field}' expected {expected_type.__name__}, "
                f"got {type(value).__name__}"
            )
    return errors


def validate_id(data: dict[str, Any], path: Path) -> list[str]:
    field_id = data.get("id", "")
    if isinstance(field_id, str) and not ID_PATTERN.match(field_id):
        return [
            f"{path}: invalid id '{field_id}' — "
            f"expected format {{source}}-{{YYYYMMDD}}-{{NNN}} "
            f"(e.g. github-20260317-001)"
        ]
    return []


def validate_status(data: dict[str, Any], path: Path) -> list[str]:
    status = data.get("status", "")
    if isinstance(status, str) and status not in VALID_STATUSES:
        return [
            f"{path}: invalid status '{status}' — "
            f"must be one of: {', '.join(sorted(VALID_STATUSES))}"
        ]
    return []


def validate_url(data: dict[str, Any], path: Path) -> list[str]:
    url = data.get("source_url", "")
    if isinstance(url, str) and not URL_PATTERN.match(url):
        return [f"{path}: invalid source_url '{url}' — must start with http:// or https://"]
    return []


def validate_summary_tags(data: dict[str, Any], path: Path) -> list[str]:
    errors: list[str] = []

    summary = data.get("summary", "")
    if isinstance(summary, str) and len(summary) < MIN_SUMMARY_LEN:
        errors.append(
            f"{path}: summary too short ({len(summary)} chars) — "
            f"minimum {MIN_SUMMARY_LEN}"
        )

    tags = data.get("tags", [])
    if isinstance(tags, list) and len(tags) == 0:
        errors.append(f"{path}: tags must contain at least 1 entry")

    return errors


def validate_optional(data: dict[str, Any], path: Path) -> list[str]:
    errors: list[str] = []

    if "score" in data and data["score"] is not None:
        score = data["score"]
        if not isinstance(score, int) or not (SCORE_MIN <= score <= SCORE_MAX):
            errors.append(
                f"{path}: score '{score}' out of range — "
                f"must be integer {SCORE_MIN}–{SCORE_MAX}"
            )

    if "audience" in data and data["audience"] is not None:
        audience = data["audience"]
        if not isinstance(audience, str) or audience not in VALID_AUDIENCES:
            errors.append(
                f"{path}: invalid audience '{audience}' — "
                f"must be one of: {', '.join(sorted(VALID_AUDIENCES))}"
            )

    return errors


def validate_file(path: Path) -> list[str]:
    try:
        data = parse_json(path)
    except ValidationError as exc:
        return [f"{path}: {exc}"]

    errors: list[str] = []
    errors.extend(validate_required(data, path))
    errors.extend(validate_id(data, path))
    errors.extend(validate_status(data, path))
    errors.extend(validate_url(data, path))
    errors.extend(validate_summary_tags(data, path))
    errors.extend(validate_optional(data, path))
    return errors


def main() -> int:
    if len(sys.argv) < 2:
        sys.stderr.write(
            "Usage: python hooks/validate_json.py <json_file> [json_file2 ...]\n"
        )
        return 2

    files = collect_files(sys.argv[1:])
    if not files:
        sys.stderr.write("No JSON files to validate.\n")
        return 2

    passed = 0
    failed = 0
    total_errors = 0

    for filepath in files:
        errors = validate_file(filepath)
        if errors:
            failed += 1
            total_errors += len(errors)
            for err in errors:
                print(err, file=sys.stderr)
        else:
            passed += 1

    print()
    print(f"Files: {len(files)}  Passed: {passed}  Failed: {failed}  Errors: {total_errors}")

    return 0 if total_errors == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
