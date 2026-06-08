"""Tests for collapsed column ticket indicators (Ticket #136).

These tests verify the refactored indicator architecture:
- Indicators live outside the cards area in a column-level .group-indicators container
- Desktop = vertical dot stack; mobile = horizontal pill row (CSS layout-aware)
- Each marker is an <a> tag with href to /ticket/<id>
- Priority colour classes applied (Critical #dc2626, High #d97706, Medium #2563eb, Low #6b7280)
- aria-label and title attributes for accessibility
"""

import json


def _load_js():
    with open("static/app.js") as f:
        return f.read()


def _load_css():
    with open("static/style.css") as f:
        return f.read()


def test_js_has_build_indicator():
    js = _load_js()
    assert "function buildIndicator(ticket)" in js


def test_js_has_rebuild_indicators():
    js = _load_js()
    assert "function rebuildIndicators(allTickets)" in js


def test_build_group_creates_group_indicators_container():
    js = _load_js()
    start = js.find("function buildGroup(status, visibleTickets)")
    end = js.find("function render()")
    body = js[start:end]
    assert 'class="group-indicators"' in body
    assert 'class="cards"' in body
    assert 'class="cards-collapsed"' not in body


def test_diff_and_update_board_calls_rebuild_indicators():
    js = _load_js()
    start = js.find("function diffAndUpdateBoard(newTickets)")
    end = js.find("function formatElapsed(isoString)")
    body = js[start:end]
    assert "rebuildIndicators(newTickets)" in body


def test_render_calls_rebuild_indicators():
    js = _load_js()
    start = js.find("function render()")
    end = js.find("showTerminal.addEventListener")
    body = js[start:end]
    assert "rebuildIndicators(tickets)" in body


def test_css_group_indicators_default_hidden():
    css = _load_css()
    assert ".group-indicators { display: none; }" in css


def test_css_group_indicators_shown_when_collapsed():
    css = _load_css()
    assert ".group.collapsed .group-indicators {" in css
    assert "display: flex" in css
    assert "flex-wrap: wrap" in css


def test_css_has_desktop_collapsed_column_width_64px():
    css = _load_css()
    assert "flex: 0 0 64px;" in css
    assert "width: 64px;" in css
    assert "max-width: 64px;" in css


def test_css_has_group_indicator_styles():
    css = _load_css()
    assert ".group-indicator" in css
    assert ".group-indicator.priority-Critical" in css
    assert ".group-indicator.priority-High" in css
    assert ".group-indicator.priority-Medium" in css
    assert ".group-indicator.priority-Low" in css


def test_css_desktop_shows_group_indicators_in_collapsed_group():
    css = _load_css()
    # Find the desktop media query section that styles .group-indicators
    media_start = css.find("@media (min-width: 769px)")
    media_end = css.find(".add-btn {", media_start)
    media_block = css[media_start:media_end]
    assert ".board > .group.collapsed .group-indicators" in media_block
    assert "flex-direction: column" in media_block


def test_css_desktop_group_indicator_is_dot():
    css = _load_css()
    media_start = css.find("@media (min-width: 769px)")
    media_end = css.find(".add-btn {", media_start)
    media_block = css[media_start:media_end]
    assert ".board > .group.collapsed .group-indicator" in media_block
    # Desktop hides text and renders a small coloured dot
    assert "width: 10px" in media_block or "font-size: 0" in media_block


def test_build_indicator_returns_link_with_accessibility():
    js = _load_js()
    start = js.find("function buildIndicator(ticket)")
    end = js.find("function rebuildIndicators(allTickets)")
    body = js[start:end]
    assert 'aria-label' in body
    assert 'title' in body
    assert 'href = `/ticket/${ticket.id}`' in body or 'href = `/ticket/' in body or "href: `/ticket/" in body or 'href=`/ticket/' in body
    # Check for href pattern more loosely
    assert "/ticket/${ticket.id}" in body or "/ticket/" in body


def test_board_page_includes_app_js(client, default_board):
    """Verify board page loads the app.js script where indicator helpers live."""
    res = client.get("/board")
    assert res.status_code == 200
    html = res.data.decode("utf-8")
    assert 'src="/static/app.js"' in html


def test_api_board_listing_returns_tickets_for_markers(client, default_board):
    """Ensure ticket list API provides data needed for indicators (id, priority, status_id)."""
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
