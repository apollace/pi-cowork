"""Simple synchronous in-process event bus for pi_cowork.

Handler exceptions are caught per-handler so they never crash the caller.
"""

import contextlib
import logging
from threading import Lock

logger = logging.getLogger(__name__)


class EventBus:
    """Synchronous in-process publish/subscribe event bus."""

    def __init__(self):
        self._subscribers = {}
        self._lock = Lock()

    def subscribe(self, event_name, handler):
        """Subscribe *handler* to events named *event_name*."""
        with self._lock:
            self._subscribers.setdefault(event_name, []).append(handler)
        return handler  # convenient for @subscribe decorator

    def unsubscribe(self, event_name, handler):
        """Remove *handler* from *event_name*."""
        with self._lock:
            handlers = self._subscribers.get(event_name, [])
            with contextlib.suppress(ValueError):
                handlers.remove(handler)

    def publish(self, event_name, **kwargs):
        """Publish an event. All subscribed handlers are called synchronously.

        Handlers receive ``event_name`` as a keyword argument in addition
        to any ``**kwargs`` passed by the publisher.
        """
        handlers = list(self._subscribers.get(event_name, []))
        for handler in handlers:
            try:
                handler(event_name=event_name, **kwargs)
            except Exception:
                logger.exception(
                    "EventBus handler %r raised for event %s",
                    handler,
                    event_name,
                )

    def subscribers(self, event_name):
        """Return list of handlers subscribed to *event_name*."""
        return list(self._subscribers.get(event_name, []))


# ---------------------------------------------------------------------------
# Event name constants
# ---------------------------------------------------------------------------
TICKET_CREATED = "ticket.created"
TICKET_STATUS_CHANGED = "ticket.status_changed"
TICKET_UPDATED = "ticket.updated"
COMMENT_ADDED = "comment.added"
QUESTION_ASKED = "question.asked"
QUESTION_ANSWERED = "question.answered"
AGENT_SPAWNED = "agent.spawned"
AGENT_COMPLETED = "agent.completed"
AGENT_FAILED = "agent.failed"
GATE_PENDING = "gate.pending"
GATE_PASSED = "gate.passed"
GATE_FAILED = "gate.failed"
RECURRING_TRIGGERED = "recurring.triggered"

# Module-level singleton
bus = EventBus()
