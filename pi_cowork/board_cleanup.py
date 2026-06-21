"""Filesystem and process cleanup helpers for board deletion."""

import contextlib
import logging
import os
import shutil
import signal
import time
from datetime import UTC, datetime
from pathlib import Path

from pi_cowork import agents as _agents_mod
from pi_cowork.db import query_db, run_db

logger = logging.getLogger(__name__)


def terminate_running_agents_for_board(board_id):
    """Kill any running agent processes belonging to tickets on this board.

    Does not add comments or feedback rows; those are about to be deleted.
    Returns the number of processes that were terminated.
    """
    rows = query_db(
        """
        SELECT ar.id, ar.pid, ar.ticket_id, a.name AS agent_name
        FROM agent_runs ar
        JOIN agents a ON ar.agent_id = a.id
        JOIN tickets t ON ar.ticket_id = t.id
        WHERE ar.status = 'running' AND t.board_id = ?
        """,
        (board_id,),
    )
    terminated = 0
    for row in rows:
        pid = row["pid"]
        if pid is None:
            logger.info("Agent run %d has no PID; skipping termination", row["id"])
            continue

        if not _agents_mod._is_our_process(pid):
            logger.info("Agent run %d PID %d is no longer a pi process", row["id"], pid)
            continue

        try:
            os.killpg(pid, signal.SIGTERM)
        except ProcessLookupError:
            logger.info("Agent run %d PID %d already terminated", row["id"], pid)
            continue
        except Exception as e:  # noqa: BLE001
            logger.warning("SIGTERM failed for agent run %d PID %d: %s", row["id"], pid, e)
            continue

        # Brief wait, then SIGKILL if the process is still alive.
        for _ in range(10):
            time.sleep(0.05)
            if not _agents_mod._is_our_process(pid):
                break
        else:
            with contextlib.suppress(ProcessLookupError):
                os.killpg(pid, signal.SIGKILL)

        terminated += 1
        logger.info("Terminated agent run %d (%s) for ticket %d", row["id"], row["agent_name"], row["ticket_id"])

        # Update the row so it is not left as 'running' in case the caller
        # inspects the DB before deleting it.
        now = datetime.now(UTC).isoformat()
        run_db(
            "UPDATE agent_runs SET status = 'failed', completed_at = ?, exit_code = ? WHERE id = ?",
            (now, -15, row["id"]),
        )

    return terminated


def cleanup_board_filesystem(board_id, working_directory):
    """Remove board-specific agent logs and session directories.

    Removes, for the board's working directory:
      - .pi-logs/ticket-{ticket_id} for every ticket on the board
      - .pi-sessions/{agent_id}/ticket-{ticket_id} for every recorded agent run
      - .pi-sessions/assistant-board-{board_id}

    Intentionally does NOT delete the rest of ``working_directory`` so that
    boards sharing a workspace cannot damage each other.
    """
    board_dir = Path(working_directory).resolve()
    if not board_dir.is_dir():
        logger.warning("Working directory %s does not exist; skipping filesystem cleanup", board_dir)
        return

    ticket_rows = query_db("SELECT id FROM tickets WHERE board_id = ?", (board_id,))
    ticket_ids = {r["id"] for r in ticket_rows}

    run_rows = query_db(
        """
        SELECT DISTINCT agent_id, ticket_id
        FROM agent_runs
        WHERE ticket_id IN (SELECT id FROM tickets WHERE board_id = ?)
        """,
        (board_id,),
    )

    logs_dir = board_dir / ".pi-logs"
    for ticket_id in ticket_ids:
        path = logs_dir / f"ticket-{ticket_id}"
        if path.exists():
            shutil.rmtree(path, ignore_errors=True)

    sessions_dir = board_dir / ".pi-sessions"
    for row in run_rows:
        path = sessions_dir / str(row["agent_id"]) / f"ticket-{row['ticket_id']}"
        if path.exists():
            shutil.rmtree(path, ignore_errors=True)

    assistant_session = sessions_dir / f"assistant-board-{board_id}"
    if assistant_session.exists():
        shutil.rmtree(assistant_session, ignore_errors=True)
