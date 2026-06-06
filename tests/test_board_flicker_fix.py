"""Tests for Ticket #125: Board window flicker fix.

Verifies that SSE events trigger surgical DOM updates instead of full
refresh(), eliminating the board flicker caused by destroying and
recreating the entire DOM on every update.
"""

import os
import re

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
JS_PATH = os.path.join(ROOT, "static", "app.js")


def _read_js():
    with open(JS_PATH) as f:
        return f.read()


class TestSyncTicketsFunction:
    """Verify syncTickets() and helpers exist."""

    def test_syncTickets_function_exists(self):
        js = _read_js()
        assert "async function syncTickets()" in js

    def test_diffAndUpdateBoard_function_exists(self):
        js = _read_js()
        assert "function diffAndUpdateBoard(newTickets)" in js

    def test_debounceSync_function_exists(self):
        js = _read_js()
        assert "function debounceSync(delay)" in js

    def test_updateCardInPlace_function_exists(self):
        js = _read_js()
        assert "function updateCardInPlace(ticket, cardEl)" in js

    def test_updateGroupCounts_function_exists(self):
        js = _read_js()
        assert "function updateGroupCounts(allTickets)" in js

    def test_getCardsContainer_function_exists(self):
        js = _read_js()
        assert "function getCardsContainer(statusId)" in js

    def test_removeCard_function_exists(self):
        js = _read_js()
        assert "function removeCard(ticketId)" in js

    def test_appendCardToColumn_function_exists(self):
        js = _read_js()
        assert "function appendCardToColumn(ticket)" in js

    def test_moveCardToColumn_function_exists(self):
        js = _read_js()
        assert "function moveCardToColumn(ticket, oldStatusId)" in js


class TestSSEEventHandlers:
    """Verify SSE events use debounceSync, not debounceRefresh."""

    def test_board_events_use_debounceSync(self):
        js = _read_js()
        # Find the boardEvents array and its listener
        events_match = re.search(
            r"const boardEvents = \[([^\]]+)\];",
            js,
            re.DOTALL,
        )
        assert events_match, "Expected boardEvents array"
        # After the boardEvents forEach, the handler should call debounceSync
        after_events = js[events_match.end() : events_match.end() + 400]
        assert "debounceSync(500)" in after_events, "Expected boardEvents listener to call debounceSync(500)"

    def test_sse_open_uses_debounceRefresh(self):
        js = _read_js()
        # sse:open should still use debounceRefresh for full resync
        open_match = re.search(
            r"addEventListener\('sse:open'[^}]+debounceRefresh\(100\)",
            js,
            re.DOTALL,
        )
        assert open_match, "Expected sse:open to call debounceRefresh(100) for full resync"

    def test_no_debounceRefresh_in_boardEvents(self):
        js = _read_js()
        # The boardEvents handler block should NOT contain debounceRefresh
        events_match = re.search(
            r"const boardEvents = \[([^\]]+)\];\s*boardEvents\.forEach\(function\(type\)\s*\{([^}]+)\}\);",
            js,
            re.DOTALL,
        )
        assert events_match
        handler_body = events_match.group(2)
        assert "debounceRefresh" not in handler_body, "boardEvents listener should not call debounceRefresh"


class TestBuildCardIdentity:
    """Verify cards have stable IDs for surgical updates."""

    def test_buildCard_assigns_id(self):
        js = _read_js()
        start = js.find("function buildCard(ticket)")
        end = js.find("function updateLabelFilters")
        region = js[start:end]
        assert "card.id = 'ticket-card-' + ticket.id" in region

    def test_card_id_prefix(self):
        js = _read_js()
        assert "ticket-card-" in js


class TestRenderRunningPanelDiffing:
    """Verify renderRunningPanel diffs instead of wiping."""

    def test_uses_dataset_runId(self):
        js = _read_js()
        panel_start = js.find("function renderRunningPanel(runs)")
        panel_end = js.find("async function moveTicket", panel_start)
        region = js[panel_start:panel_end]
        assert "dataset.runId" in region

    def test_maps_existing_cards(self):
        js = _read_js()
        panel_start = js.find("function renderRunningPanel(runs)")
        panel_end = js.find("async function moveTicket", panel_start)
        region = js[panel_start:panel_end]
        assert "existingCards" in region
        assert "newRunIds" in region

    def test_removes_orphaned_cards(self):
        js = _read_js()
        panel_start = js.find("function renderRunningPanel(runs)")
        panel_end = js.find("async function moveTicket", panel_start)
        region = js[panel_start:panel_end]
        assert "card.remove()" in region

    def test_no_unconditional_panel_innerHTML_empty(self):
        js = _read_js()
        panel_start = js.find("function renderRunningPanel(runs)")
        panel_end = js.find("async function moveTicket", panel_start)
        region = js[panel_start:panel_end]
        # The old code did `panel.innerHTML = '';` unconditionally after showing the panel.
        # In the new code, innerHTML is only cleared when there are no runs.
        # We verify there is no `panel.innerHTML = '';` after `panel.style.display = 'flex';`
        flex_pos = region.find("panel.style.display = 'flex';")
        assert flex_pos != -1
        after_flex = region[flex_pos:]
        # Should NOT contain a second innerHTML = '' after the flex display
        # (the only innerHTML = '' is in the early-return `if (!runs || runs.length === 0)` block)
        assert "panel.innerHTML = '';" not in after_flex, (
            "renderRunningPanel should not wipe innerHTML after showing panel; it should diff"
        )


class TestSyncTicketsLightweightFetch:
    """Verify syncTickets fetches only what it needs."""

    def test_fetches_tickets_and_runs_only(self):
        js = _read_js()
        sync_start = js.find("async function syncTickets()")
        sync_end = js.find("function getCardsContainer", sync_start)
        region = js[sync_start:sync_end]
        # Should fetch tickets endpoint
        assert "/api/tickets?board_id=" in region
        # Should fetch running agents
        assert "/api/running_agent_runs?board_id=" in region
        # Should NOT fetch statuses or labels
        assert "/api/statuses?workflow_id=" not in region
        assert "/api/labels?workflow_id=" not in region

    def test_no_skeleton_in_syncTickets(self):
        js = _read_js()
        sync_start = js.find("async function syncTickets()")
        sync_end = js.find("function getCardsContainer", sync_start)
        region = js[sync_start:sync_end]
        assert "board-skeleton" not in region
        assert "skeleton" not in region


class TestMoveTicketBehavior:
    """Verify moveTicket triggers lightweight sync instead of full refresh."""

    def test_moveTicket_calls_syncTickets_not_refresh(self):
        js = _read_js()
        move_start = js.find("async function moveTicket(ticketId, statusId)")
        move_end = js.find("function closeActivePopover", move_start)
        region = js[move_start:move_end]
        assert "syncTickets" in region
        assert "await refresh()" not in region
        assert "refresh()" not in region

    def test_moveTicket_uses_setTimeout_fallback(self):
        js = _read_js()
        move_start = js.find("async function moveTicket(ticketId, statusId)")
        move_end = js.find("function closeActivePopover", move_start)
        region = js[move_start:move_end]
        assert "setTimeout(syncTickets" in region or "setTimeout(function" in region


class TestDiffAndUpdateBoardLogic:
    """Verify diffAndUpdateBoard contains the expected surgical update paths."""

    def test_handles_removed_tickets(self):
        js = _read_js()
        diff_start = js.find("function diffAndUpdateBoard(newTickets)")
        diff_end = js.find("function formatElapsed", diff_start)
        region = js[diff_start:diff_end]
        assert "removeCard(id)" in region

    def test_handles_new_tickets(self):
        js = _read_js()
        diff_start = js.find("function diffAndUpdateBoard(newTickets)")
        diff_end = js.find("function formatElapsed", diff_start)
        region = js[diff_start:diff_end]
        assert "appendCardToColumn(newTicket)" in region

    def test_handles_status_changes(self):
        js = _read_js()
        diff_start = js.find("function diffAndUpdateBoard(newTickets)")
        diff_end = js.find("function formatElapsed", diff_start)
        region = js[diff_start:diff_end]
        assert "moveCardToColumn(newTicket" in region

    def test_handles_in_place_updates(self):
        js = _read_js()
        diff_start = js.find("function diffAndUpdateBoard(newTickets)")
        diff_end = js.find("function formatElapsed", diff_start)
        region = js[diff_start:diff_end]
        assert "updateCardInPlace(newTicket, cardEl)" in region

    def test_updates_group_counts(self):
        js = _read_js()
        diff_start = js.find("function diffAndUpdateBoard(newTickets)")
        diff_end = js.find("function formatElapsed", diff_start)
        region = js[diff_start:diff_end]
        assert "updateGroupCounts(newTickets)" in region

    def test_preserves_filter_visibility(self):
        js = _read_js()
        diff_start = js.find("function diffAndUpdateBoard(newTickets)")
        diff_end = js.find("function formatElapsed", diff_start)
        region = js[diff_start:diff_end]
        assert "matchesFilters(newTicket)" in region
        assert "matchesFilters(oldTicket)" in region
