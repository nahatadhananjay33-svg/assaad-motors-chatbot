"""
intent_analytics.py
===================

Phase 11B — Intent Analytics (STEP 11).

Anonymous, aggregate-only telemetry for the deterministic intent engine. It helps
improve the deterministic dictionaries later — it stores **no user data**: no
session ids, no names, no phone numbers. Free-text phrases (unknown / low-confidence
only) are PII-masked and truncated before storage.

Exports `intent_analytics.json`:

    {
      "totals": {...},
      "top_intents": {intent: count},
      "clarifications": {intent: count},
      "conflicts": {dimension: count},
      "multi_intents": {"2": n, "3": n, ...},
      "bands": {"high": n, "medium": n, "low": n},
      "unknown_phrases": [ "...masked...", ... ],
      "low_confidence_phrases": [ "...masked...", ... ]
    }

Pure stdlib. Deterministic. Thread-safe writes.
"""

from __future__ import annotations

import json
import os
import threading
from collections import Counter
from typing import Dict, List, Optional

try:
    from security import mask_pii
except Exception:                                # pragma: no cover - safety net
    def mask_pii(x):                             # type: ignore
        return x

DEFAULT_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                            "data", "intent_analytics.json")
_MAX_PHRASES = 500          # bounded lists so the file never grows unbounded


def _mask(phrase: str) -> str:
    """Anonymize a phrase: PII-mask, strip long digit runs, cap length."""
    p = mask_pii(phrase or "")
    p = " ".join(p.split())
    return p[:80]


class IntentAnalyticsStore:
    def __init__(self, path: str = DEFAULT_PATH):
        self.path = path
        self._lock = threading.Lock()
        self.totals = Counter()
        self.top_intents = Counter()
        self.clarifications = Counter()
        self.conflicts = Counter()
        self.multi_intents = Counter()
        self.bands = Counter()
        self.unknown_phrases: List[str] = []
        self.low_conf_phrases: List[str] = []
        self._load()

    # ── ingestion ──
    def record(self, analysis, *, message: str = "") -> None:
        """Record one anonymous intent observation from an IntentAnalysis."""
        with self._lock:
            self.totals["requests"] += 1
            self.bands[analysis.band] += 1
            if analysis.primary:
                self.top_intents[analysis.primary] += 1
            else:
                self.totals["no_primary"] += 1
            if analysis.recommendation == "clarify":
                self.totals["clarifications"] += 1
                if analysis.primary:
                    self.clarifications[analysis.primary] += 1
            if analysis.recommendation == "ask":
                self.totals["fallbacks"] += 1
            for c in analysis.conflicts:
                self.conflicts[c["dimension"]] += 1
            if len(analysis.multi_intents) >= 2:
                self.multi_intents[str(len(analysis.multi_intents))] += 1
            if analysis.band == "low" and message:
                self._push(self.unknown_phrases, _mask(message))
            elif analysis.band == "medium" and message:
                self._push(self.low_conf_phrases, _mask(message))

    @staticmethod
    def _push(lst: List[str], val: str) -> None:
        if val and val not in lst:
            lst.append(val)
            if len(lst) > _MAX_PHRASES:
                del lst[0]

    # ── export / persistence ──
    def snapshot(self) -> Dict[str, object]:
        return {
            "totals": dict(self.totals),
            "top_intents": dict(self.top_intents.most_common()),
            "clarifications": dict(self.clarifications.most_common()),
            "conflicts": dict(self.conflicts.most_common()),
            "multi_intents": dict(sorted(self.multi_intents.items())),
            "bands": dict(self.bands),
            "unknown_phrases": list(self.unknown_phrases),
            "low_confidence_phrases": list(self.low_conf_phrases),
        }

    def export(self, path: Optional[str] = None) -> str:
        path = path or self.path
        with self._lock:
            snap = self.snapshot()
        os.makedirs(os.path.dirname(path), exist_ok=True)
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(snap, f, ensure_ascii=False, indent=2)
        os.replace(tmp, path)
        return path

    def _load(self) -> None:
        if not os.path.exists(self.path):
            return
        try:
            with open(self.path, encoding="utf-8") as f:
                d = json.load(f)
        except Exception:
            return
        self.totals.update(d.get("totals", {}))
        self.top_intents.update(d.get("top_intents", {}))
        self.clarifications.update(d.get("clarifications", {}))
        self.conflicts.update(d.get("conflicts", {}))
        self.multi_intents.update(d.get("multi_intents", {}))
        self.bands.update(d.get("bands", {}))
        self.unknown_phrases = list(d.get("unknown_phrases", []))[-_MAX_PHRASES:]
        self.low_conf_phrases = list(d.get("low_confidence_phrases", []))[-_MAX_PHRASES:]


if __name__ == "__main__":
    from intent_intelligence import analyze
    st = IntentAnalyticsStore(path=os.path.join(os.path.dirname(__file__),
                                                "data", "intent_analytics_demo.json"))
    for m in ["RC?", "Paper?", "Clear?", "petrol diesel", "automatic diesel",
              "insurence", "price?", "photos bhejo"]:
        st.record(analyze(m), message=m)
    print(json.dumps(st.snapshot(), ensure_ascii=False, indent=2))
