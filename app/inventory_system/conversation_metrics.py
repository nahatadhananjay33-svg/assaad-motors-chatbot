"""
conversation_metrics.py
======================

Pure calculation over a list of analytics events. No I/O, no LLM. Given events
shaped like:

    {session_id, query, route, intent, language, lead_level, visit_ready,
     is_media, vehicle, timestamp}

it computes route/percentage breakdowns, distributions, top-N rankings, and the
lead funnel.
"""

from __future__ import annotations

from collections import Counter
from typing import Any, Dict, List, Optional

ROUTES = ("inventory", "faq", "unknown")
_LEVEL_RANK = {None: -1, "Low": 0, "Medium": 1, "High": 2}


def _pct(n: int, total: int) -> float:
    return round(100.0 * n / total, 1) if total else 0.0


def _rank(counter: Counter, total: Optional[int] = None, *, key="key",
          limit: Optional[int] = None) -> List[Dict[str, Any]]:
    total = total if total is not None else sum(counter.values())
    items = counter.most_common(limit)
    return [{key: k, "count": n, "percentage": _pct(n, total)} for k, n in items]


# ─────────────────────────────────────────────────────────────────────────────
# Session-level funnel
# ─────────────────────────────────────────────────────────────────────────────
def funnel(events: List[Dict[str, Any]]) -> Dict[str, Any]:
    sessions: Dict[str, Dict[str, Any]] = {}
    for e in events:
        sid = e.get("session_id") or "anonymous"
        agg = sessions.setdefault(sid, {"level": None, "visit_ready": False,
                                        "vehicle": False})
        lvl = e.get("lead_level")
        if _LEVEL_RANK.get(lvl, -1) > _LEVEL_RANK.get(agg["level"], -1):
            agg["level"] = lvl
        agg["visit_ready"] = agg["visit_ready"] or bool(e.get("visit_ready"))
        agg["vehicle"] = agg["vehicle"] or bool(e.get("vehicle"))

    conversations = len(sessions)
    # a "lead" = a session that reached at least Medium intent (beyond browsing)
    leads = sum(1 for a in sessions.values()
                if _LEVEL_RANK.get(a["level"], -1) >= _LEVEL_RANK["Medium"])
    visit_ready = sum(1 for a in sessions.values() if a["visit_ready"])
    high_priority = sum(1 for a in sessions.values() if a["level"] == "High")

    return {
        "conversations": conversations,
        "leads": leads,
        "visit_ready": visit_ready,
        "high_priority_leads": high_priority,
        "lead_percentage": _pct(leads, conversations),
        "visit_ready_percentage": _pct(visit_ready, conversations),
        "high_priority_percentage": _pct(high_priority, conversations),
    }


# ─────────────────────────────────────────────────────────────────────────────
# Full metric set
# ─────────────────────────────────────────────────────────────────────────────
def compute(events: List[Dict[str, Any]]) -> Dict[str, Any]:
    total = len(events)
    route_counter = Counter(e.get("route") for e in events)
    intent_counter = Counter(e.get("intent") for e in events if e.get("intent"))
    language_counter = Counter(e.get("language") for e in events if e.get("language"))
    vehicle_counter = Counter(e.get("vehicle") for e in events if e.get("vehicle"))
    media_count = sum(1 for e in events if e.get("is_media"))
    unknown_queries = Counter(
        (e.get("query") or "").strip().lower()
        for e in events if e.get("route") == "unknown" and e.get("query"))

    f = funnel(events)

    return {
        "total_queries": total,
        # route coverage
        "inventory_percentage": _pct(route_counter.get("inventory", 0), total),
        "faq_percentage": _pct(route_counter.get("faq", 0), total),
        "unknown_percentage": _pct(route_counter.get("unknown", 0), total),
        "media_percentage": _pct(media_count, total),
        "route_counts": dict(route_counter),
        # lead / visit (session level)
        "lead_percentage": f["lead_percentage"],
        "visit_ready_percentage": f["visit_ready_percentage"],
        # distributions & rankings
        "language_distribution": _rank(language_counter, total, key="language"),
        "top_requested_models": _rank(vehicle_counter, key="model", limit=10),
        "top_requested_intents": _rank(intent_counter, total, key="intent", limit=10),
        "top_unknown_queries": _rank(unknown_queries, key="query", limit=10),
        # funnel block
        "funnel": f,
    }
