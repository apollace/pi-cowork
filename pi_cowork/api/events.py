"""API: Events — SSE stream endpoint bridging EventBus to browser clients."""

import json
import logging
import queue
import threading
import time

from flask import Blueprint, Response, request, stream_with_context, current_app

from pi_cowork.events import bus
from pi_cowork.events import (
    TICKET_CREATED, TICKET_STATUS_CHANGED, TICKET_UPDATED,
    COMMENT_ADDED, QUESTION_ASKED, QUESTION_ANSWERED,
    AGENT_SPAWNED, AGENT_COMPLETED, AGENT_FAILED,
    GATE_PENDING, GATE_PASSED, GATE_FAILED,
)

logger = logging.getLogger(__name__)

MAX_CONNECTIONS = 50
RETRY_AFTER_SECONDS = 5

EVENT_NAMES = [
    TICKET_CREATED, TICKET_STATUS_CHANGED, TICKET_UPDATED,
    COMMENT_ADDED, QUESTION_ASKED, QUESTION_ANSWERED,
    AGENT_SPAWNED, AGENT_COMPLETED, AGENT_FAILED,
    GATE_PENDING, GATE_PASSED, GATE_FAILED,
]

# Module-level connection tracking
_active_connections = 0
_connections_lock = threading.Lock()

events_bp = Blueprint('events', __name__)


def _get_board_id_for_ticket(ticket_id):
    """Look up the board_id for a given ticket_id. Returns None if not found."""
    try:
        from pi_cowork.db import query_db
        row = query_db("SELECT board_id FROM tickets WHERE id = ?", (ticket_id,), one=True)
        return row['board_id'] if row else None
    except Exception:
        return None


@events_bp.route('/api/events/stream')
def api_events_stream():
    """SSE endpoint that forwards EventBus events to browser clients.

    Query params:
        board_id: Optional filter — only events for tickets on this board
                  are forwarded. TICKET_CREATED already includes board_id
                  in the event data; other events require a lightweight
                  DB lookup to resolve the ticket's board.
    """
    global _active_connections

    board_id = request.args.get('board_id', type=int)

    # Connection limit guard
    with _connections_lock:
        if _active_connections >= MAX_CONNECTIONS:
            return Response(
                "Too many SSE connections",
                status=429,
                mimetype='text/plain',
                headers={'Retry-After': str(RETRY_AFTER_SECONDS)},
            )
        _active_connections += 1

    return current_app.response_class(
        stream_with_context(_event_generator(board_id)),
        mimetype='text/event-stream',
        headers={
            'Cache-Control': 'no-cache',
            'X-Accel-Buffering': 'no',
        },
    )


def _event_generator(board_id):
    """Generator that subscribes to the EventBus, forwards events as SSE frames,
    and cleans up on disconnect.

    The subscriber is created inside the generator so we hold a stable
    reference for both pushing to the queue and unsubscribing on cleanup.
    """
    global _active_connections

    event_queue = queue.Queue()

    def _subscriber(event_name=None, **kwargs):
        """Dynamic EventBus subscriber — O(1) put, no DB calls in hot path."""
        event_queue.put((event_name, kwargs))

    # Subscribe to all event types
    for ev in EVENT_NAMES:
        bus.subscribe(ev, _subscriber)

    try:
        # Yield immediately so that WSGI servers (and test clients) can
        # detect response headers without waiting for the first event.
        yield ": ready\n\n"
        last_heartbeat = time.monotonic()
        while True:
            try:
                # Block for up to 1 second waiting for an event
                event_name, kwargs = event_queue.get(timeout=1)
            except queue.Empty:
                # No event — maybe send heartbeat
                now = time.monotonic()
                if now - last_heartbeat >= 25:
                    last_heartbeat = now
                    yield ": keepalive\n\n"
                continue

            # Board ID filtering
            if board_id is not None:
                event_board_id = kwargs.get('board_id')
                if event_board_id is None:
                    # Try to resolve from ticket_id
                    ticket_id = kwargs.get('ticket_id')
                    if ticket_id is not None:
                        event_board_id = _get_board_id_for_ticket(ticket_id)
                if event_board_id != board_id:
                    continue  # skip events for other boards

            # Build SSE frame
            data = dict(kwargs)
            yield f"event: {event_name}\ndata: {json.dumps(data)}\n\n"

            last_heartbeat = time.monotonic()

    except GeneratorExit:
        # Client disconnected
        pass
    finally:
        # Cleanup: unsubscribe and decrement connection count
        for ev in EVENT_NAMES:
            bus.unsubscribe(ev, _subscriber)
        with _connections_lock:
            _active_connections -= 1