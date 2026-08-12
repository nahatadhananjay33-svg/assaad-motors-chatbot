"""
routing_metrics.py
=================

Tracks how messages are routed so we can measure the share handled WITHOUT an
LLM. Counts:

    inventory_count   — answered by the retrieval engine
    faq_count         — answered by the deterministic FAQ engine
    unknown_count     — deferred (mark_for_future_llm)

`handled_without_llm = inventory_count + faq_count`. Coverage = that over total.
Also keeps a per-FAQ-intent and per-language breakdown for the report.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from typing import Dict, Optional


@dataclass
class RoutingMetrics:
    inventory_count: int = 0
    faq_count: int = 0
    unknown_count: int = 0
    faq_by_intent: Counter = field(default_factory=Counter)
    by_language: Counter = field(default_factory=Counter)

    # -- record one routed message --
    def record(self, kind: str, *, intent: Optional[str] = None,
               language: Optional[str] = None) -> None:
        if kind == "faq":
            self.faq_count += 1
            if intent:
                self.faq_by_intent[intent] += 1
        elif kind == "inventory":
            self.inventory_count += 1
        else:
            self.unknown_count += 1
        if language:
            self.by_language[language] += 1

    @property
    def total(self) -> int:
        return self.inventory_count + self.faq_count + self.unknown_count

    @property
    def handled_without_llm(self) -> int:
        return self.inventory_count + self.faq_count

    def _pct(self, n: int) -> float:
        return round(100.0 * n / self.total, 1) if self.total else 0.0

    def coverage(self) -> Dict[str, object]:
        return {
            "total": self.total,
            "inventory_count": self.inventory_count,
            "faq_count": self.faq_count,
            "unknown_count": self.unknown_count,
            "handled_without_llm": self.handled_without_llm,
            "coverage_pct": self._pct(self.handled_without_llm),
            "inventory_pct": self._pct(self.inventory_count),
            "faq_pct": self._pct(self.faq_count),
            "unknown_pct": self._pct(self.unknown_count),
            "faq_by_intent": dict(self.faq_by_intent),
            "by_language": dict(self.by_language),
        }

    def report(self) -> str:
        c = self.coverage()
        lines = [
            "── Routing Coverage ──",
            f"total queries        : {c['total']}",
            f"inventory            : {c['inventory_count']} ({c['inventory_pct']}%)",
            f"faq                  : {c['faq_count']} ({c['faq_pct']}%)",
            f"unknown (future LLM) : {c['unknown_count']} ({c['unknown_pct']}%)",
            f"handled w/o LLM      : {c['handled_without_llm']} ({c['coverage_pct']}%)",
            f"faq by intent        : {c['faq_by_intent']}",
            f"by language          : {c['by_language']}",
        ]
        return "\n".join(lines)

    def reset(self) -> None:
        self.inventory_count = self.faq_count = self.unknown_count = 0
        self.faq_by_intent.clear()
        self.by_language.clear()
