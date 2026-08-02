"""Multi-agent budget guard with triple-layer protection.

Tracks LLM costs, warns near budget threshold, raises on exceed.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

# ======================================================================
# Data classes
# ======================================================================


@dataclass
class CostRecord:
    """A single LLM call record."""

    timestamp: str = ""
    """ISO-8601 UTC timestamp of the call."""

    node_name: str = ""
    """Which pipeline node made the call (collect/analyze/organize/review)."""

    prompt_tokens: int = 0
    """Input token count."""

    completion_tokens: int = 0
    """Output token count."""

    cost_yuan: float = 0.0
    """Cost in CNY for this single call."""

    model: str = ""
    """LLM model name (e.g. deepseek-chat, qwen-plus)."""


# ======================================================================
# Exception
# ======================================================================


class BudgetExceededError(Exception):
    """Raised when cumulative cost exceeds the total budget."""

    def __init__(self, total: float, budget: float) -> None:
        self.total = total
        self.budget = budget
        super().__init__(
            f"Budget exceeded: total {total:.6f} CNY > budget {budget:.4f} CNY"
        )


# ======================================================================
# CostGuard
# ======================================================================

MILLION = 1_000_000


class CostGuard:
    """Track and guard LLM cost with triple-layer protection.

    1. record()  — log every LLM call
    2. check()   — status check (ok / warning / exceeded)
    3. report()  — per-node cost summary + export
    """

    def __init__(
        self,
        budget_yuan: float = 1.0,
        alert_threshold: float = 0.8,
        input_price_per_million: float = 1.0,
        output_price_per_million: float = 2.0,
    ) -> None:
        self._budget = budget_yuan
        self._alert = alert_threshold
        self._input_price = input_price_per_million
        self._output_price = output_price_per_million
        self._records: list[CostRecord] = []
        self._total_cost: float = 0.0
        self._total_prompt: int = 0
        self._total_completion: int = 0

    # ------------------------------------------------------------------
    # Layer 1: record
    # ------------------------------------------------------------------

    def record(
        self,
        node_name: str,
        usage: dict,
        model: str = "",
    ) -> None:
        """Record one LLM call and increment totals.

        Args:
            node_name: Pipeline node name (collect/analyze/organize/review).
            usage: Dict with prompt_tokens / completion_tokens.
            model: LLM model identifier.
        """
        prompt = usage.get("prompt_tokens", 0)
        completion = usage.get("completion_tokens", 0)

        cost = (
            prompt * self._input_price + completion * self._output_price
        ) / MILLION

        record = CostRecord(
            timestamp=datetime.now(timezone.utc).isoformat(),
            node_name=node_name,
            prompt_tokens=prompt,
            completion_tokens=completion,
            cost_yuan=round(cost, 6),
            model=model,
        )

        self._records.append(record)
        self._total_cost += cost
        self._total_prompt += prompt
        self._total_completion += completion

    # ------------------------------------------------------------------
    # Layer 2: check
    # ------------------------------------------------------------------

    def check(self) -> dict:
        """Check budget status.

        Returns:
            {"status": "ok"|"warning", "total_cost": float, "budget": float,
             "usage_ratio": float, "message": str}

        Raises:
            BudgetExceededError: When total_cost >= budget_yuan.
        """
        ratio = self._total_cost / self._budget if self._budget > 0 else 1.0

        if self._total_cost >= self._budget:
            raise BudgetExceededError(self._total_cost, self._budget)

        if ratio >= self._alert:
            return {
                "status": "warning",
                "total_cost": round(self._total_cost, 6),
                "budget": self._budget,
                "usage_ratio": round(ratio, 4),
                "message": (
                    f"已使用预算的 {ratio:.1%}（{self._total_cost:.6f} / "
                    f"{self._budget:.4f} CNY），请控制后续调用"
                ),
            }

        return {
            "status": "ok",
            "total_cost": round(self._total_cost, 6),
            "budget": self._budget,
            "usage_ratio": round(ratio, 4),
            "message": f"预算正常，已使用 {ratio:.1%}",
        }

    # ------------------------------------------------------------------
    # Layer 3: report
    # ------------------------------------------------------------------

    def get_report(self) -> dict:
        """Generate a per-node cost summary.

        Returns:
            {
              "summary": {
                "total_calls": int,
                "total_prompt_tokens": int,
                "total_completion_tokens": int,
                "total_cost_yuan": float,
                "budget_yuan": float,
              },
              "by_node": {
                "node_name": {
                  "calls": int,
                  "prompt_tokens": int,
                  "completion_tokens": int,
                  "cost_yuan": float,
                },
                ...
              },
              "records": [...],
            }
        """
        by_node: dict[str, dict] = {}
        for r in self._records:
            node = r.node_name or "unknown"
            if node not in by_node:
                by_node[node] = {
                    "calls": 0,
                    "prompt_tokens": 0,
                    "completion_tokens": 0,
                    "cost_yuan": 0.0,
                }
            by_node[node]["calls"] += 1
            by_node[node]["prompt_tokens"] += r.prompt_tokens
            by_node[node]["completion_tokens"] += r.completion_tokens
            by_node[node]["cost_yuan"] += r.cost_yuan

        # Round costs
        for v in by_node.values():
            v["cost_yuan"] = round(v["cost_yuan"], 6)

        return {
            "summary": {
                "total_calls": len(self._records),
                "total_prompt_tokens": self._total_prompt,
                "total_completion_tokens": self._total_completion,
                "total_cost_yuan": round(self._total_cost, 6),
                "budget_yuan": self._budget,
            },
            "by_node": by_node,
            "records": [
                {
                    "timestamp": r.timestamp,
                    "node": r.node_name,
                    "prompt": r.prompt_tokens,
                    "completion": r.completion_tokens,
                    "cost_yuan": r.cost_yuan,
                    "model": r.model,
                }
                for r in self._records
            ],
        }

    def save_report(self, path: str | Path | None = None) -> Path:
        """Save cost report to JSON file.

        Args:
            path: Output path.  Defaults to tests/cost_report.json.

        Returns:
            The resolved Path that was written to.
        """
        target = Path(path) if path else Path(__file__).with_name("cost_report.json")
        report = self.get_report()
        target.write_text(
            json.dumps(report, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        return target

    # ------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------

    @property
    def total_cost(self) -> float:
        return self._total_cost

    @property
    def total_prompt_tokens(self) -> int:
        return self._total_prompt

    @property
    def total_completion_tokens(self) -> int:
        return self._total_completion

    @property
    def call_count(self) -> int:
        return len(self._records)


# ======================================================================
# Smoke test
# ======================================================================

if __name__ == "__main__":
    guard = CostGuard(
        budget_yuan=0.005,
        alert_threshold=0.6,
        input_price_per_million=1.0,
        output_price_per_million=2.0,
    )

    # ---- Test 1: cost tracking ----
    print("=== Test 1: Cost tracking ===")
    guard.record("analyze", {"prompt_tokens": 500, "completion_tokens": 100})
    guard.record("analyze", {"prompt_tokens": 300, "completion_tokens": 50})
    guard.record("review", {"prompt_tokens": 800, "completion_tokens": 200})

    assert guard.total_prompt_tokens == 1600, "prompt total mismatch"
    assert guard.call_count == 3, "call count mismatch"

    # 500*1 + 100*2 + 300*1 + 50*2 + 800*1 + 200*2 = 500+200+300+100+800+400 = 2300 / 1000000 = 0.0023
    assert abs(guard.total_cost - 0.0023) < 0.00001, f"cost mismatch: {guard.total_cost}"

    status = guard.check()
    assert status["status"] == "ok", f"expected ok, got {status['status']}"
    print(f"  total_cost={guard.total_cost:.6f}, status={status['status']}, ratio={status['usage_ratio']:.2%}")

    # ---- Test 2: alert threshold (>= 60%) ----
    print("\n=== Test 2: Alert threshold ===")
    guard.record("organize", {"prompt_tokens": 400, "completion_tokens": 100})
    # additional cost: 400*1 + 100*2 = 600 / 1M = 0.0006
    # total: 0.0023 + 0.0006 = 0.0029, budget=0.005, ratio=0.58... still below 0.6
    guard.record("analyze", {"prompt_tokens": 100, "completion_tokens": 20})
    # additional: 100 + 40 = 140 / 1M = 0.00014
    # total: 0.0029 + 0.00014 = 0.00304, budget=0.005, ratio=0.608

    status = guard.check()
    assert status["status"] == "warning", f"expected warning, got {status['status']}"
    print(f"  total_cost={guard.total_cost:.6f}, status={status['status']}, ratio={status['usage_ratio']:.2%}")
    print(f"  message: {status['message']}")

    # ---- Test 3: budget exceeded exception ----
    print("\n=== Test 3: Budget exceeded ===")
    try:
        guard.record("review", {"prompt_tokens": 1000, "completion_tokens": 500})
        # additional: 1000 + 1000 = 2000 / 1M = 0.002
        # total: 0.00304 + 0.002 = 0.00504 > 0.005
        guard.check()
        print("  ERROR: BudgetExceededError not raised!")
    except BudgetExceededError as e:
        print(f"  Caught: {e}")
        assert e.total >= e.budget
        print(f"  total={e.total:.6f}, budget={e.budget:.3f}")

    # ---- Test 4: report ----
    print("\n=== Test 4: Report ===")
    report = guard.get_report()
    print(f"  calls={report['summary']['total_calls']}")
    print(f"  by_node: {list(report['by_node'].keys())}")
    for node, stats in report["by_node"].items():
        print(f"    {node}: {stats['calls']} calls, {stats['cost_yuan']:.6f} CNY")

    saved = guard.save_report()
    print(f"\n  Report saved to: {saved}")

    print("\nAll tests passed!")
