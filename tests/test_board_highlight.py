"""Tests for Ticket #163: Board highlight fix.

Verifies that the board manager slide-out panel always highlights the
currently selected board by ensuring `renderBoardList()` is called at
the right times.
"""

import re


def _get_board_script(client):
    res = client.get("/board")
    assert res.status_code == 200
    html = res.data.decode("utf-8")
    # Extract the inline script block in board.html (the last <script> block)
    script_match = re.search(r"<script>\s*// Board manager panel.*?</script>", html, re.DOTALL)
    assert script_match, "Expected inline board manager script block"
    return script_match.group(0)


class TestToggleBoardPanel:
    """toggleBoardPanel must refresh the list when opening."""

    def test_detects_opening_state(self, client):
        script = _get_board_script(client)
        assert "const isOpening = !panel.classList.contains('open');" in script

    def test_calls_render_board_list_when_opening(self, client):
        script = _get_board_script(client)
        assert "if (isOpening) {" in script
        assert "renderBoardList();" in script

    def test_no_unconditional_render_in_toggle(self, client):
        """renderBoardList should only be called conditionally (when opening)."""
        script = _get_board_script(client)
        # Find toggleBoardPanel function body
        match = re.search(
            r"function toggleBoardPanel\(\)\s*\{([^}]+(?:\{[^}]*\}[^}]*)*)\}",
            script,
            re.DOTALL,
        )
        assert match, "Could not extract toggleBoardPanel body"
        body = match.group(1)
        # Count renderBoardList calls inside toggleBoardPanel
        calls = body.count("renderBoardList()")
        assert calls == 1, f"Expected exactly 1 renderBoardList() call in toggleBoardPanel, found {calls}"


class TestSelectBoard:
    """selectBoard must defensively refresh the panel list."""

    def test_calls_render_board_list(self, client):
        script = _get_board_script(client)
        match = re.search(
            r"function selectBoard\(id\)\s*\{([^}]+(?:\{[^}]*\}[^}]*)*)\}",
            script,
            re.DOTALL,
        )
        assert match, "Could not extract selectBoard body"
        body = match.group(1)
        assert "renderBoardList();" in body

    def test_sets_local_storage_before_render(self, client):
        """localStorage must be updated before renderBoardList so the highlight is correct."""
        script = _get_board_script(client)
        match = re.search(
            r"function selectBoard\(id\)\s*\{([^}]+(?:\{[^}]*\}[^}]*)*)\}",
            script,
            re.DOTALL,
        )
        assert match
        body = match.group(1)
        set_pos = body.find("localStorage.setItem('activeBoard', id);")
        render_pos = body.find("renderBoardList();")
        assert set_pos != -1 and render_pos != -1
        assert set_pos < render_pos, "localStorage must be set before renderBoardList"


class TestStartupSequence:
    """Initial page load must sequence initBoard before renderBoardList."""

    def test_awaits_init_board_first(self, client):
        script = _get_board_script(client)
        assert "await initBoard();" in script

    def test_awaits_render_board_list_second(self, client):
        script = _get_board_script(client)
        assert "await renderBoardList();" in script

    def test_immediately_invoked_async_function(self, client):
        """The startup calls must be wrapped in an async IIFE to allow awaiting."""
        script = _get_board_script(client)
        assert "(async function() {" in script
        assert "await initBoard();" in script
        assert "await renderBoardList();" in script
        assert "})();" in script
