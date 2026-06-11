"""Self-improvement observation collector.

Subscribes to system events and creates observation tickets on the System
board for the Synthesizer agent to process.
"""

import logging

from pi_cowork.config import get_config
from pi_cowork.db import query_db, run_db
from pi_cowork.events import (
    AGENT_FAILED,
    COMMENT_ADDED,
    GATE_FAILED,
    GATE_REVIEW_REJECTED,
    TICKET_CREATED,
    TICKET_RERUN_DETECTED,
    bus,
)

logger = logging.getLogger(__name__)

_SYSTEM_EMOJI_PREFIXES = (
    "🤖",
    "⏳",
    "⚠️",
    "✅",
    "❌",
    "🔥",
    "🔔",
    "🔄",
)

_OBSERVATION_STATUS_NAMES = ("Observe", "Analyze", "Synthesize", "Apply", "Validate")


def _is_system_comment(body):
    """Return True if a comment body is a system-generated message."""
    return body.strip().startswith(_SYSTEM_EMOJI_PREFIXES)


def _get_system_board_id():
    """Return the ID of the System board, or None if it doesn't exist."""
    row = query_db(
        """
        SELECT b.id FROM boards b
        JOIN workflows w ON b.workflow_id = w.id
        WHERE b.name = ? AND w.name = ?
        """,
        ("System", "System Improvement"),
        one=True,
    )
    return row["id"] if row else None


def _get_observe_status_id(workflow_id):
    """Return the ID of the 'Observe' status for the given workflow."""
    row = query_db(
        "SELECT id FROM statuses WHERE name = ? AND workflow_id = ?",
        ("Observe", workflow_id),
        one=True,
    )
    return row["id"] if row else None


def _get_system_workflow_id():
    """Return the workflow ID for System Improvement, or None."""
    row = query_db("SELECT id FROM workflows WHERE name = ?", ("System Improvement",), one=True)
    return row["id"] if row else None


def _enabled():
    """Return True if self-improvement is enabled."""
    return str(get_config("self_improvement_enabled") or "1") == "1"


def _create_observation_ticket(title, body, board_id, observe_status_id):
    """Create an observation ticket and return its ID, or None on failure."""
    try:
        cur = run_db(
            "INSERT INTO tickets (title, body, status_id, board_id, priority) VALUES (?, ?, ?, ?, ?)",
            (title, body, observe_status_id, board_id, "Medium"),
        )
        ticket_id = cur.lastrowid
        bus.publish(
            TICKET_CREATED,
            ticket_id=ticket_id,
            title=title,
            board_id=board_id,
            status_id=observe_status_id,
        )
        return ticket_id
    except Exception:
        logger.exception("Failed to create observation ticket")
        return None


def _has_open_churn_observation(source_ticket_id, board_id, workflow_id):
    """Check if an open high-churn observation already exists for this source ticket."""
    row = query_db(
        """
        SELECT 1 FROM tickets t
        JOIN statuses s ON t.status_id = s.id
        WHERE t.board_id = ?
          AND t.title LIKE ?
          AND s.name IN ({placeholders})
          AND s.is_terminal = 0
        LIMIT 1
        """.replace("{placeholders}", ",".join("?" * len(_OBSERVATION_STATUS_NAMES))),
        (board_id, f"[High Churn] Ticket #{source_ticket_id}%", *_OBSERVATION_STATUS_NAMES),
        one=True,
    )
    return row is not None


def _count_human_comments(ticket_id):
    """Count non-system comments for a ticket."""
    rows = query_db("SELECT body FROM comments WHERE ticket_id = ?", (ticket_id,))
    return sum(1 for r in rows if not _is_system_comment(r["body"]))


def _on_agent_failed(event_name=None, ticket_id=None, agent_name=None, exit_code=None, **kwargs):
    """Create an observation when an agent fails."""
    if not _enabled():
        return
    board_id = _get_system_board_id()
    if not board_id:
        logger.warning("System board not found; skipping agent-failed observation")
        return
    workflow_id = _get_system_workflow_id()
    observe_status_id = _get_observe_status_id(workflow_id) if workflow_id else None
    if not observe_status_id:
        logger.warning("Observe status not found; skipping agent-failed observation")
        return
    title = f"[Agent Failed] Ticket #{ticket_id}"
    body = f"Agent '{agent_name}' failed with exit code {exit_code} on ticket #{ticket_id}."
    _create_observation_ticket(title, body, board_id, observe_status_id)


def _on_gate_failed(event_name=None, ticket_id=None, gate_name=None, notify_on_failure=None, **kwargs):
    """Create an observation when a quality gate fails."""
    if not _enabled():
        return
    if notify_on_failure is False:
        logger.info("Skipping gate-failed observation for ticket %d — notify_on_failure=False", ticket_id)
        return
    board_id = _get_system_board_id()
    if not board_id:
        logger.warning("System board not found; skipping gate-failed observation")
        return
    workflow_id = _get_system_workflow_id()
    observe_status_id = _get_observe_status_id(workflow_id) if workflow_id else None
    if not observe_status_id:
        logger.warning("Observe status not found; skipping gate-failed observation")
        return
    title = f"[Gate Failed] Ticket #{ticket_id}"
    body = f"Quality gate '{gate_name}' failed on ticket #{ticket_id}."
    _create_observation_ticket(title, body, board_id, observe_status_id)


def _on_gate_review_rejected(event_name=None, ticket_id=None, gate_name=None, notify_on_failure=None, **kwargs):
    """Create an observation when a manual gate review is rejected."""
    if not _enabled():
        return
    if notify_on_failure is False:
        logger.info("Skipping gate-rejected observation for ticket %d — notify_on_failure=False", ticket_id)
        return
    board_id = _get_system_board_id()
    if not board_id:
        logger.warning("System board not found; skipping gate-rejected observation")
        return
    workflow_id = _get_system_workflow_id()
    observe_status_id = _get_observe_status_id(workflow_id) if workflow_id else None
    if not observe_status_id:
        logger.warning("Observe status not found; skipping gate-rejected observation")
        return
    title = f"[Gate Rejected] Ticket #{ticket_id}"
    body = f"Manual gate review '{gate_name}' was rejected on ticket #{ticket_id}."
    _create_observation_ticket(title, body, board_id, observe_status_id)


def _has_recent_gate_failure(ticket_id):
    """Check if the ticket had a gate failure or rejection within the last 10 minutes."""
    row = query_db(
        """
        SELECT 1 FROM comments
        WHERE ticket_id = ?
          AND (body LIKE '❌ Gate%' OR body LIKE '🚫 Transition%')
          AND created_at > datetime('now', '-10 minutes')
        LIMIT 1
        """,
        (ticket_id,),
        one=True,
    )
    return row is not None


def _on_ticket_rerun_detected(event_name=None, ticket_id=None, old_status_id=None, new_status_id=None, **kwargs):
    """Create an observation when a ticket moves backward (rerun)."""
    if not _enabled():
        return
    # Skip if this rerun is likely a consequence of a recent gate failure/rejection
    # (system-initiated re-trigger). User-initiated backward moves don't have recent gate comments.
    if _has_recent_gate_failure(ticket_id):
        logger.info("Skipping rerun observation for ticket %d — recent gate activity detected", ticket_id)
        return
    board_id = _get_system_board_id()
    if not board_id:
        logger.warning("System board not found; skipping rerun observation")
        return
    workflow_id = _get_system_workflow_id()
    observe_status_id = _get_observe_status_id(workflow_id) if workflow_id else None
    if not observe_status_id:
        logger.warning("Observe status not found; skipping rerun observation")
        return
    old_status = query_db("SELECT name FROM statuses WHERE id = ?", (old_status_id,), one=True)
    new_status = query_db("SELECT name FROM statuses WHERE id = ?", (new_status_id,), one=True)
    title = f"[Rerun] Ticket #{ticket_id}"
    body = (
        f"Ticket #{ticket_id} moved backward from "
        f"'{old_status['name'] if old_status else 'unknown'}' to "
        f"'{new_status['name'] if new_status else 'unknown'}'."
    )
    _create_observation_ticket(title, body, board_id, observe_status_id)


def _on_comment_added(event_name=None, ticket_id=None, body=None, **kwargs):
    """Create an observation when human comment churn exceeds the threshold."""
    if not _enabled():
        return
    if _is_system_comment(body or ""):
        return
    threshold = int(get_config("high_comment_threshold") or "10")
    if threshold <= 0:
        return
    count = _count_human_comments(ticket_id)
    if count <= threshold:
        return
    board_id = _get_system_board_id()
    if not board_id:
        logger.warning("System board not found; skipping high-churn observation")
        return
    workflow_id = _get_system_workflow_id()
    observe_status_id = _get_observe_status_id(workflow_id) if workflow_id else None
    if not observe_status_id:
        logger.warning("Observe status not found; skipping high-churn observation")
        return
    if _has_open_churn_observation(ticket_id, board_id, workflow_id):
        return
    title = f"[High Churn] Ticket #{ticket_id}"
    body = f"Ticket #{ticket_id} has {count} human comments (threshold: {threshold})."
    _create_observation_ticket(title, body, board_id, observe_status_id)


def register_self_improvement_subscribers():
    """Register event bus subscribers for the self-improvement loop."""
    bus.subscribe(AGENT_FAILED, _on_agent_failed)
    bus.subscribe(GATE_FAILED, _on_gate_failed)
    bus.subscribe(GATE_REVIEW_REJECTED, _on_gate_review_rejected)
    bus.subscribe(TICKET_RERUN_DETECTED, _on_ticket_rerun_detected)
    bus.subscribe(COMMENT_ADDED, _on_comment_added)
