"""Tests for collapsed column ticket markers (Ticket #135).

Tests verify:
- JS app.js contains buildCollapsedMarker and rebuildCollapsedMarkers helpers
- buildGroup() creates both .cards and .cards-collapsed containers
- diffAndUpdateBoard() calls rebuildCollapsedMarkers() after updating counts
- render() calls rebuildCollapsedMarkers() after building groups
- CSS style.css contains .cards-collapsed and .collapsed-marker rules
- Desktop collapsed column width is 64px (not 48px)
- Mobile behavior is unchanged (cards-collapsed stays hidden)
"""

import json


def _load_js():
    with open("static/app.js") as f:
        return f.read()


def _load_css():
    with open("static/style.css") as f:
        return f.read()


def test_js_has_build_collapsed_marker():
    js = _load_js()
    assert "function buildCollapsedMarker(ticket)" in js


def test_js_has_rebuild_collapsed_markers():
    js = _load_js()
    assert "function rebuildCollapsedMarkers(allTickets)" in js


def test_build_group_creates_cards_collapsed_container():
    js = _load_js()
    start = js.find("function buildGroup(status, visibleTickets)")
    end = js.find("function render()")
    body = js[start:end]
    assert 'class="cards-collapsed"' in body
    assert 'class="cards"' in body


def test_diff_and_update_board_calls_rebuild_collapsed_markers():
    js = _load_js()
    start = js.find("function diffAndUpdateBoard(newTickets)")
    end = js.find("function formatElapsed(isoString)")
    body = js[start:end]
    assert "rebuildCollapsedMarkers(newTickets)" in body


def test_render_calls_rebuild_collapsed_markers():
    js = _load_js()
    start = js.find("function render()")
    end = js.find("showTerminal.addEventListener")
    body = js[start:end]
    assert "rebuildCollapsedMarkers(tickets)" in body


def test_css_has_cards_collapsed_default_hidden():
    css = _load_css()
    assert ".group.collapsed .cards-collapsed { display: none; }" in css


def test_css_has_desktop_collapsed_column_width_64px():
    css = _load_css()
    assert "flex: 0 0 64px;" in css
    assert "width: 64px;" in css
    assert "max-width: 64px;" in css


def test_css_has_collapsed_marker_styles():
    css = _load_css()
    assert ".collapsed-marker" in css
    assert ".collapsed-marker:hover" in css
    assert ".collapsed-marker-id" in css
    assert ".collapsed-marker.priority-Critical" in css


def test_css_desktop_shows_cards_collapsed_in_collapsed_group():
    css = _load_css()
    # Find the desktop media query section that styles .cards-collapsed
    media_start = css.find("@media (min-width: 769px)")
    media_end = css.find(".add-btn {", media_start)
    media_block = css[media_start:media_end]
    assert ".board > .group.collapsed .cards-collapsed" in media_block


def test_board_page_includes_app_js(client, default_board):
    """Verify board page loads the app.js script where collapsed marker helpers live."""
    res = client.get("/board")
    assert res.status_code == 200
    html = res.data.decode("utf-8")
    assert 'src="/static/app.js"' in html


def test_api_board_listing_returns_tickets_for_markers(client, default_board):
    """Ensure ticket list API provides data needed for markers (id, priority, status_id)."""
    board_id = default_board["id"]
    # Seed a ticket
    res = client.post(
        "/api/tickets",
        json={"title": "Marker test", "body": "test", "board_id": board_id, "priority": "High"},
    )
    assert res.status_code == 201
    res = client.get(f"/api/tickets?board_id={board_id}&include_terminal=true")
    assert res.status_code == 200
    tickets = json.loads(res.data)
    assert len(tickets) > 0
    for t in tickets:
        assert "id" in t
        assert "priority" in t
        assert "status_id" in t
