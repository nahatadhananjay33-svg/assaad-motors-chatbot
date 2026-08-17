"""
instrumented_chat_service.py
=============================

Phase 5B — pilot instrumentation. A thin subclass of `ChatService` that logs
every turn to `PilotQueryLog` (Task 1/2) without touching retrieval, parser,
FAQ, or inventory-matching logic. `handle()` delegates entirely to
`ChatService.handle()` and returns its result unchanged; logging happens
after the response is computed.

`session_id` is used directly as `conversation_id` (matches the convention
used throughout Phase 5A's `conversation_dataset.csv` / `conv_<id>` ids).
"""

from __future__ import annotations

import json
from typing import Any, Optional

from chat_service import ChatService, ChatResult
from pilot_query_log import PilotQueryLog, QueryLogEntry, DEFAULT_DB
from inventory_models import utcnow_iso


class InstrumentedChatService(ChatService):
    def __init__(self, *args, pilot_log_db: str = DEFAULT_DB, **kwargs):
        super().__init__(*args, **kwargs)
        self.pilot_log = PilotQueryLog(pilot_log_db)

    def handle(self, message: Any, *, request_id: Optional[str] = None,
               session_id: Optional[str] = None) -> ChatResult:
        out = super().handle(message, request_id=request_id, session_id=session_id)

        meta = out.meta or {}
        route = meta.get("route", "")
        # Phase 5D: count any inventory-routed response with count > 0 as a
        # successful match -- including relaxed/segment fallbacks (status
        # "off_sheet" with relaxed=True). Analytics-only change; does not
        # touch retrieval_engine/response_formatter behavior or output.
        matched_inventory = (
            route == "inventory"
            and out.count > 0
            and out.status != "not_found"
        )

        # Phase 8C: capture the complete turn (customer + bot) for later analysis.
        # All values are read straight off the already-computed ChatResult `out`
        # — no re-parsing, no extra retrieval, nothing in the response path changes.
        self.pilot_log.record(QueryLogEntry(
            timestamp=utcnow_iso(),
            conversation_id=session_id,
            session_id=session_id,
            user_query=message,
            detected_language=meta.get("language"),
            detected_intent=out.intent,
            route=route,
            unknown_flag=(route == "unknown"),
            matched_inventory=matched_inventory,
            response_time_ms=meta.get("latency_ms"),
            bot_response=out.response,
            lead_level=meta.get("lead_level"),
            visit_ready=bool(meta.get("visit_ready")),
            vehicle_selected=self._vehicles_shown(out),
            # Phase: applied inventory filters + how many cars matched, for
            # monitoring. filters is q.active_filters() already on the result;
            # serialize to compact JSON (None when empty so the column stays tidy).
            filters=self._filters_json(out),
            result_count=int(out.count or 0),
        ))
        return out

    @staticmethod
    def _filters_json(out: ChatResult) -> Optional[str]:
        f = getattr(out, "filters", None)
        if not f:
            return None
        try:
            return json.dumps(f, ensure_ascii=False, sort_keys=True, default=str)
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _vehicles_shown(out: ChatResult) -> Optional[str]:
        """Compact, customer-facing label of the vehicles surfaced this turn
        (e.g. '2016 Creta; 2019 Ertiga'). Reads only already-rendered card
        fields (G-EXPOSE keeps registration out); never re-queries inventory."""
        cards = out.vehicles or []
        labels = []
        for v in cards[:5]:
            year = v.get("year")
            model = v.get("model") or v.get("make") or ""
            label = f"{year} {model}".strip() if year else str(model).strip()
            if label:
                labels.append(label)
        return "; ".join(labels) or None

    def close(self) -> None:
        self.pilot_log.close()
        super_close = getattr(super(), "close", None)
        if callable(super_close):
            super_close()
