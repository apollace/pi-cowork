"""Tests for Ticket #56: Ticket detail page real-time SSE updates.

Verifies that:
1. The ticket detail page ensures activeBoard in localStorage matches the
   ticket's board and reconnects SSE on page load
2. The ticket detail page listens for sse:ticket.updated events
3. Agent event handlers (spawned/completed/failed) call refreshTicketStatus()
4. The sse:open reconnect handler also calls refreshTicketStatus()
"""

import re

TICKET_DETAIL_PATH = "templates/ticket_detail.html"
BASE_HTML_PATH = "templates/base.html"


def read(path):
    with open(path) as f:
        return f.read()


class TestTicketDetailSSEConnection:
    """Test that the ticket detail page ensures the SSE stream is connected
    for the correct board."""

    def test_sets_active_board_in_local_storage(self):
        """On page load, the ticket detail page sets localStorage.activeBoard
        to the ticket's board_id if it doesn't already match."""
        html = read(TICKET_DETAIL_PATH)
        # Should reference ticket.board_id to set the active board
        assert "localStorage.setItem('activeBoard'" in html, (
            "Expected localStorage.setItem('activeBoard', ...) on ticket detail page"
        )
        # Should read the current ticket's board_id from the template context
        assert "currentBoardId" in html, "Expected currentBoardId variable derived from ticket.board_id"

    def test_reads_board_id_from_template_context(self):
        """The currentBoardId should be set from the Jinja template variable
        ticket.board_id."""
        html = read(TICKET_DETAIL_PATH)
        # Should use Jinja template syntax to inject the board_id
        assert "{{ ticket.board_id }}" in html, (
            "Expected {{ ticket.board_id }} in ticket_detail.html for SSE board setup"
        )

    def test_calls_reconnect_sse(self):
        """The ticket detail page should call _reconnectSSE() to establish
        or reconnect the SSE stream after setting activeBoard."""
        html = read(TICKET_DETAIL_PATH)
        assert "_reconnectSSE" in html, (
            "Expected _reconnectSSE() call on ticket detail page to establish SSE connection"
        )

    def test_comparisons_use_string_conversion(self):
        """The comparison between storedBoard and currentBoardId should handle
        type mismatches (localStorage returns strings, Jinja renders the raw int)."""
        html = read(TICKET_DETAIL_PATH)
        # Should use String() conversion or other type-safe comparison
        assert "String(currentBoardId)" in html, (
            "Expected String(currentBoardId) comparison to handle localStorage string vs int"
        )


class TestTicketDetailTicketUpdatedListener:
    """Test that the ticket detail page listens for sse:ticket.updated events."""

    def test_has_ticket_updated_listener(self):
        """The page should have an event listener for sse:ticket.updated."""
        html = read(TICKET_DETAIL_PATH)
        assert "sse:ticket.updated" in html, "Expected sse:ticket.updated event listener on ticket detail page"

    def test_ticket_updated_calls_refresh_ticket_status(self):
        """The sse:ticket.updated handler should call refreshTicketStatus()."""
        html = read(TICKET_DETAIL_PATH)
        # Find the sse:ticket.updated handler block
        m = re.search(
            r"sse:ticket\.updated.*?debounceDetailRefresh\(function\(\)\s*\{([^}]+)\}",
            html,
            re.DOTALL,
        )
        assert m, "Expected debounceDetailRefresh callback in sse:ticket.updated handler"
        body = m.group(1)
        assert "refreshTicketStatus" in body, (
            f"Expected refreshTicketStatus() in sse:ticket.updated handler, got: {body}"
        )

    def test_ticket_updated_calls_load_labels(self):
        """The sse:ticket.updated handler should reload labels."""
        html = read(TICKET_DETAIL_PATH)
        m = re.search(
            r"sse:ticket\.updated.*?debounceDetailRefresh\(function\(\)\s*\{([^}]+)\}",
            html,
            re.DOTALL,
        )
        assert m, "Expected debounceDetailRefresh callback in sse:ticket.updated handler"
        body = m.group(1)
        assert "loadLabels" in body, f"Expected loadLabels() in sse:ticket.updated handler, got: {body}"

    def test_ticket_updated_calls_load_comments(self):
        """The sse:ticket.updated handler should reload comments."""
        html = read(TICKET_DETAIL_PATH)
        m = re.search(
            r"sse:ticket\.updated.*?debounceDetailRefresh\(function\(\)\s*\{([^}]+)\}",
            html,
            re.DOTALL,
        )
        assert m, "Expected debounceDetailRefresh callback in sse:ticket.updated handler"
        body = m.group(1)
        assert "loadComments" in body, f"Expected loadComments() in sse:ticket.updated handler, got: {body}"

    def test_ticket_updated_filters_by_ticket_id(self):
        """The sse:ticket.updated handler should filter events by currentTicketId."""
        html = read(TICKET_DETAIL_PATH)
        # Find the sse:ticket.updated listener setup
        m = re.search(
            r"addEventListener\('sse:ticket\.updated',\s*function\(e\)\s*\{",
            html,
        )
        assert m, "Expected addEventListener for sse:ticket.updated"
        # The next line should check isForThisTicket(e)
        # Extract the block around the addEventListener
        start = m.start()
        block = html[start : start + 300]
        assert "isForThisTicket" in block, "Expected isForThisTicket(e) check in sse:ticket.updated handler"


class TestAgentEventHandlersRefreshStatus:
    """Test that agent SSE event handlers also call refreshTicketStatus()."""

    def _extract_handler_body(self, html, event_name):
        """Extract the debounceDetailRefresh callback body for a given SSE event."""
        # Match the pattern: addEventListener('sse:EVENT', function(e) { ...
        # debounceDetailRefresh(function() { BODY }, ...); });
        # We need a regex that captures the body inside debounceDetailRefresh
        pattern = (
            r"addEventListener\('sse:" + re.escape(event_name) + r"',\s*function\(e\)\s*\{"
            r"[^}]*?"
            r"debounceDetailRefresh\(function\(\)\s*\{([^}]+)\}"
        )
        m = re.search(pattern, html, re.DOTALL)
        return m.group(1) if m else None

    def test_agent_spawned_calls_refresh_ticket_status(self):
        """sse:agent.spawned handler should call refreshTicketStatus()."""
        html = read(TICKET_DETAIL_PATH)
        body = self._extract_handler_body(html, "agent.spawned")
        assert body is not None, "Could not find sse:agent.spawned handler"
        assert "refreshTicketStatus" in body, (
            f"Expected refreshTicketStatus() in sse:agent.spawned handler, got: {body}"
        )

    def test_agent_completed_calls_refresh_ticket_status(self):
        """sse:agent.completed handler should call refreshTicketStatus()."""
        html = read(TICKET_DETAIL_PATH)
        body = self._extract_handler_body(html, "agent.completed")
        assert body is not None, "Could not find sse:agent.completed handler"
        assert "refreshTicketStatus" in body, (
            f"Expected refreshTicketStatus() in sse:agent.completed handler, got: {body}"
        )

    def test_agent_failed_calls_refresh_ticket_status(self):
        """sse:agent.failed handler should call refreshTicketStatus()."""
        html = read(TICKET_DETAIL_PATH)
        body = self._extract_handler_body(html, "agent.failed")
        assert body is not None, "Could not find sse:agent.failed handler"
        assert "refreshTicketStatus" in body, f"Expected refreshTicketStatus() in sse:agent.failed handler, got: {body}"

    def test_agent_spawned_also_calls_load_agent_runs(self):
        """sse:agent.spawned should still call loadAgentRuns() and initRunAgentButton()."""
        html = read(TICKET_DETAIL_PATH)
        body = self._extract_handler_body(html, "agent.spawned")
        assert body is not None, "Could not find sse:agent.spawned handler"
        assert "loadAgentRuns" in body, f"Expected loadAgentRuns() in sse:agent.spawned handler, got: {body}"
        assert "initRunAgentButton" in body, f"Expected initRunAgentButton() in sse:agent.spawned handler, got: {body}"

    def test_agent_completed_also_calls_load_comments(self):
        """sse:agent.completed should still call loadComments()."""
        html = read(TICKET_DETAIL_PATH)
        body = self._extract_handler_body(html, "agent.completed")
        assert body is not None, "Could not find sse:agent.completed handler"
        assert "loadComments" in body, f"Expected loadComments() in sse:agent.completed handler, got: {body}"


class TestSSEOpenReconnect:
    """Test that the sse:open reconnect handler calls refreshTicketStatus()."""

    def test_sse_open_calls_refresh_ticket_status(self):
        """The sse:open handler should call refreshTicketStatus() on reconnect."""
        html = read(TICKET_DETAIL_PATH)
        # Find the sse:open handler
        m = re.search(
            r"addEventListener\('sse:open',\s*function\(\)\s*\{[^}]*?debounceDetailRefresh\(function\(\)\s*\{([^}]+)\}",
            html,
            re.DOTALL,
        )
        assert m, "Could not find sse:open handler with debounceDetailRefresh"
        body = m.group(1)
        assert "refreshTicketStatus" in body, f"Expected refreshTicketStatus() in sse:open handler, got: {body}"


class TestIntegration:
    """Integration tests: ticket detail page returns correct board_id for SSE setup."""

    def test_ticket_detail_page_contains_board_id(self, client, default_board):
        """The ticket detail page HTML should contain the board_id for SSE setup."""
        import json

        res = client.post(
            "/api/tickets",
            json={
                "title": "SSE Test Ticket",
                "board_id": default_board["id"],
            },
        )
        ticket_id = json.loads(res.data)["id"]

        rv = client.get(f"/ticket/{ticket_id}")
        html = rv.data.decode()
        # Should contain currentBoardId with the ticket's board_id
        assert "currentBoardId" in html, "Ticket detail page should contain currentBoardId variable"
        # Should reference ticket.board_id via Jinja template
        # The rendered HTML should contain the actual board ID value
        assert str(default_board["id"]) in html, (
            f"Ticket detail page should contain the board_id '{default_board['id']}'"
        )

    def test_ticket_detail_page_contains_ticket_updated_listener(self, client, default_board):
        """The ticket detail page should include the sse:ticket.updated listener."""
        import json

        res = client.post(
            "/api/tickets",
            json={
                "title": "SSE Listener Test",
                "board_id": default_board["id"],
            },
        )
        ticket_id = json.loads(res.data)["id"]

        rv = client.get(f"/ticket/{ticket_id}")
        html = rv.data.decode()
        assert "sse:ticket.updated" in html, "Ticket detail page should have sse:ticket.updated event listener"

    def test_direct_url_sse_connection_scenario(self, client, default_board):
        """When a user navigates directly to a ticket URL, the page should
        still ensure SSE is connected by setting activeBoard and reconnecting."""
        import json

        res = client.post(
            "/api/tickets",
            json={
                "title": "Direct URL Test",
                "board_id": default_board["id"],
            },
        )
        ticket_id = json.loads(res.data)["id"]

        rv = client.get(f"/ticket/{ticket_id}")
        html = rv.data.decode()
        # Should contain localStorage.setItem for activeBoard
        assert "localStorage.setItem('activeBoard'" in html, (
            "Ticket detail page should set localStorage.activeBoard on page load"
        )
        # Should call _reconnectSSE
        assert "_reconnectSSE" in html, "Ticket detail page should call _reconnectSSE() to establish SSE connection"
