"""
instrumented_chat_service.py
=============================

A thin subclass of `ChatService` that persists every turn to `PilotQueryLog`
without touching retrieval, parser, FAQ, or inventory-matching logic.
`handle()` delegates entirely to `ChatService.handle()` and returns its result
unchanged; logging happens after the response is computed.

SIMPLIFIED chat log: the persistent record is deliberately minimal — only the
customer message and the agent reply are stored per turn:

    timestamp, conversation_id, session_id, user_query, bot_response

The chatbot still computes intent, filters, retrieval, result_count, language,
latency etc. internally (they live on the returned `ChatResult`) to answer the
customer — those runtime values are simply NOT persisted. Runtime intelligence
!= persistent chat history. This keeps the conversation database growing only
with the size of the customer/agent messages, not with per-turn analytics.

`session_id` is used directly as `conversation_id` (matches the convention used
throughout the codebase's `conv_<id>` ids).
"""

from __future__ import annotations

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

        # Persist ONLY the conversation (customer message + agent reply). The
        # response is already computed above; this adds no re-parsing, no extra
        # retrieval, and nothing in the response path changes.
        self.pilot_log.record(QueryLogEntry(
            timestamp=utcnow_iso(),
            conversation_id=session_id,
            session_id=session_id,
            user_query=message,
            bot_response=out.response,
        ))
        return out

    def close(self) -> None:
        self.pilot_log.close()
        super_close = getattr(super(), "close", None)
        if callable(super_close):
            super_close()
