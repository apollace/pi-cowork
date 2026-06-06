import json
import os


def _read_static(filename):
    """Read a static asset file from the project."""
    path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "static", filename)
    with open(path) as f:
        return f.read()


def test_board_page_has_filter_controls(client):
    res = client.get("/board")
    assert res.status_code == 200
    html = res.data.decode("utf-8")
    assert "ticket-search" in html
    assert "priority-toggles" in html
    assert "label-filters" in html
    assert "Search tickets" in html
    # New dropdown structure
    assert "filter-dropdown-btn" in html
    assert "filter-dropdown-panel" in html
    assert "filter-badge" in html
    assert "filter-dropdown-section" in html
    # Terminal checkbox moved inside dropdown
    assert "show-terminal" in html
    assert "filter-dropdown-checkbox" in html


def test_board_filter_dropdown_sections(client):
    """Verify the dropdown panel contains Priority, Labels, and Display sections."""
    res = client.get("/board")
    assert res.status_code == 200
    html = res.data.decode("utf-8")
    # Section titles inside dropdown
    assert "filter-dropdown-section-title" in html
    assert ">Priority<" in html
    assert ">Labels<" in html
    assert ">Display<" in html


def test_ticket_list_includes_body_priority_and_labels(client, default_board):
    wf_id = default_board["workflow_id"]
    lbl = client.post(
        "/api/labels",
        json={
            "name": "Feature",
            "color": "#10b981",
            "workflow_id": wf_id,
        },
    )
    lid = json.loads(lbl.data)["id"]
    client.post(
        "/api/tickets",
        json={
            "title": "Searchable Ticket",
            "body": "Look for me in search",
            "board_id": default_board["id"],
            "priority": "Critical",
            "labels": [lid],
        },
    )
    res = client.get(f"/api/tickets?board_id={default_board['id']}")
    assert res.status_code == 200
    data = json.loads(res.data)
    assert len(data) == 1
    t = data[0]
    assert t["title"] == "Searchable Ticket"
    assert t["body"] == "Look for me in search"
    assert t["priority"] == "Critical"
    assert "labels" in t
    assert len(t["labels"]) == 1
    assert t["labels"][0]["name"] == "Feature"


def test_board_page_has_filter_badge_element(client):
    """The filter badge element exists in the HTML (JS updates visibility/count)."""
    res = client.get("/board")
    assert res.status_code == 200
    html = res.data.decode("utf-8")
    # Badge element with id filter-badge is present
    assert 'id="filter-badge"' in html
    # Badge starts hidden
    assert 'style="display:none"' in html


# ── Viewport-aware filter dropdown positioning tests ──


def test_filter_dropdown_css_has_right_alignment_class():
    """The stylesheet must include a .dropdown-right class for right-aligned panels."""
    css = _read_static("style.css")
    assert ".filter-dropdown-panel.dropdown-right" in css
    # Should set left:auto and right:0 to flip to right edge
    assert "left: auto" in css
    assert "right: 0" in css


def test_filter_dropdown_css_has_above_positioning_class():
    """The stylesheet must include a .dropdown-above class for above-trigger panels."""
    css = _read_static("style.css")
    assert ".filter-dropdown-panel.dropdown-above" in css
    # Should set top:auto and bottom value to position above trigger
    assert "bottom: calc(100%" in css


def test_filter_dropdown_js_has_positioning_function():
    """The app.js must include positionFilterDropdown() for viewport-aware repositioning."""
    js = _read_static("app.js")
    assert "positionFilterDropdown" in js
    # Should add the CSS classes based on overflow detection
    assert "dropdown-right" in js
    assert "dropdown-above" in js
    # Should use getBoundingClientRect for position calculation
    assert "getBoundingClientRect" in js
    # Should check viewport dimensions
    assert "window.innerWidth" in js
    assert "window.innerHeight" in js


def test_filter_dropdown_js_repositions_on_open():
    """The toggleFilterDropdown function must call positionFilterDropdown when opening."""
    js = _read_static("app.js")
    # When opening the dropdown, positionFilterDropdown should be called
    # Find the part of toggleFilterDropdown that handles opening
    assert "positionFilterDropdown()" in js


def test_filter_dropdown_js_handles_max_height():
    """When the panel doesn't fit above or below, max-height should be constrained."""
    js = _read_static("app.js")
    # Should set maxHeight when constrained
    assert "maxHeight" in js
    # Should reset overflowY in the reset block (clears inline style)
    assert "style.overflowY = ''" in js
    # Should use .scrollable class for overflow (not inline style.overflowY = 'auto')
    assert "classList.add('scrollable')" in js
    assert "style.overflowY = 'auto'" not in js


def test_filter_dropdown_js_resets_scrollable_class():
    """The positionFilterDropdown reset block must remove the .scrollable class."""
    js = _read_static("app.js")
    assert (
        "classList.remove('scrollable')" in js
        or "classList.remove('dropdown-right', 'dropdown-above', 'scrollable')" in js
    )


def test_filter_dropdown_js_repositions_on_resize_scroll():
    """The dropdown should reposition when the viewport changes (resize/scroll)."""
    js = _read_static("app.js")
    # Should listen for resize and scroll events
    assert "addEventListener('resize'" in js
    assert "addEventListener('scroll'" in js


def test_filter_dropdown_css_scrollable_class():
    """The stylesheet must include a .scrollable class for constrained panels."""
    css = _read_static("style.css")
    assert ".filter-dropdown-panel.scrollable" in css
    assert "overflow-y: auto" in css


def test_filter_dropdown_mobile_css_respects_right_alignment():
    """Mobile media query should not override the dropdown-right positioning."""
    css = _read_static("style.css")
    # In mobile media query, dropdown-right should still work
    # Find the mobile media query section
    mobile_start = css.find("@media (max-width: 768px)")
    assert mobile_start != -1
    mobile_section = css[mobile_start : mobile_start + 2000]
    # Should have .dropdown-right rule in mobile
    assert "dropdown-right" in mobile_section


# ── Board preferences persistence tests ──


def test_app_js_has_save_board_prefs_function():
    """The app.js must define a saveBoardPrefs() function."""
    js = _read_static("app.js")
    assert "function saveBoardPrefs()" in js


def test_app_js_has_restore_board_prefs_function():
    """The app.js must define a restoreBoardPrefs() function."""
    js = _read_static("app.js")
    assert "function restoreBoardPrefs()" in js


def test_app_js_uses_board_prefs_key_pattern():
    """The localStorage key must follow the board_prefs_{id} pattern."""
    js = _read_static("app.js")
    assert "'board_prefs_'" in js or '"board_prefs_"' in js
    assert "boardPrefsKey" in js


def test_app_js_collapsed_groups_stored_as_status_ids():
    """Collapsed groups must be stored as an array of status IDs."""
    js = _read_static("app.js")
    # The save should spread collapsed (a Set of status IDs) into an array
    assert "collapsedGroups: [...collapsed]" in js
    # The restore should populate collapsed from an array
    assert "collapsed.clear()" in js
    # Should iterate and add each ID from collapsedGroups
    assert "collapsedGroups.forEach" in js or "collapsedGroups.forEach" in js


def test_app_js_save_includes_all_filter_fields():
    """The saved preferences must include all five filter/layout fields."""
    js = _read_static("app.js")
    # Find the saveBoardPrefs function body
    save_start = js.find("function saveBoardPrefs()")
    assert save_start != -1
    save_end = js.find("function restoreBoardPrefs()", save_start)
    save_body = js[save_start:save_end]
    assert "searchQuery" in save_body
    assert "selectedPriorities" in save_body
    assert "selectedLabels" in save_body
    assert "collapsedGroups" in save_body
    assert "showTerminal" in save_body


def test_app_js_restore_applies_all_filter_fields():
    """The restore function must apply all five filter/layout fields."""
    js = _read_static("app.js")
    restore_start = js.find("function restoreBoardPrefs()")
    assert restore_start != -1
    # Find end of restore function
    # Search for the next function definition or top-level declaration
    restore_end = js.find("\n  async function loadBoards", restore_start)
    if restore_end == -1:
        restore_end = js.find("\n  }\n  ", restore_start + 100)
    restore_body = js[restore_start:restore_end]
    # Each field must be restored
    assert "filterState.searchQuery" in restore_body
    assert "filterState.selectedPriorities" in restore_body
    assert "filterState.selectedLabels" in restore_body
    assert "collapsed" in restore_body
    assert "showTerminal.checked" in restore_body


def test_app_js_save_called_on_search_input():
    """saveBoardPrefs must be called when the search input changes."""
    js = _read_static("app.js")
    # Find the search input event handler
    idx = js.find("searchInput.addEventListener('input'")
    assert idx != -1
    # Check that saveBoardPrefs is called within this handler
    handler_block = js[idx : idx + 300]
    assert "saveBoardPrefs()" in handler_block


def test_app_js_save_called_on_priority_toggle():
    """saveBoardPrefs must be called when a priority toggle is clicked."""
    js = _read_static("app.js")
    # There are two priorityToggles.forEach occurrences — the click handler is the second one
    first_idx = js.find("priorityToggles.forEach")
    assert first_idx != -1
    idx = js.find("priorityToggles.forEach", first_idx + 1)
    assert idx != -1
    handler_block = js[idx : idx + 600]
    assert "saveBoardPrefs()" in handler_block


def test_app_js_save_called_on_label_filter_change():
    """saveBoardPrefs must be called when a label filter checkbox changes."""
    js = _read_static("app.js")
    # Find the label filter change handler inside updateLabelFilters
    idx = js.find("'change'", js.find("updateLabelFilters"))
    assert idx != -1
    # Get a reasonable chunk around it
    block = js[idx : idx + 300]
    assert "saveBoardPrefs()" in block


def test_app_js_save_called_on_collapse_toggle():
    """saveBoardPrefs must be called when a group header is collapsed/expanded."""
    js = _read_static("app.js")
    # Find the click handler for group headers inside buildGroup
    # Look for the first collapsed.add/collapsed.delete in buildGroup
    idx = js.find("group.querySelector")
    assert idx != -1
    # The group-header click handler should contain saveBoardPrefs
    header_handler_start = js.find("header.addEventListener('click'", idx - 200)
    assert header_handler_start != -1
    handler_block = js[header_handler_start : header_handler_start + 500]
    assert "saveBoardPrefs()" in handler_block


def test_app_js_save_called_on_show_terminal_change():
    """saveBoardPrefs must be called when the show-terminal checkbox changes."""
    js = _read_static("app.js")
    idx = js.find("showTerminal.addEventListener('change'")
    assert idx != -1
    handler_block = js[idx : idx + 300]
    assert "saveBoardPrefs()" in handler_block


def test_app_js_save_called_on_clear_all():
    """saveBoardPrefs must be called when the 'Clear all' button is clicked."""
    js = _read_static("app.js")
    idx = js.find("clearAll.textContent = 'Clear all'")
    assert idx != -1
    handler_block = js[idx : idx + 500]
    assert "saveBoardPrefs()" in handler_block


def test_app_js_restore_called_in_refresh():
    """restoreBoardPrefs must be called in the refresh() function before render()."""
    js = _read_static("app.js")
    # Find where restoreBoardPrefs is called
    idx = js.find("restoreBoardPrefs()")
    assert idx != -1
    # It should be called before render() in refresh
    # Check that render() appears after restoreBoardPrefs() in the refresh function
    refresh_start = js.find("async function refresh()")
    assert refresh_start != -1
    restore_idx = js.find("restoreBoardPrefs()", refresh_start)
    render_idx = js.find("render()", restore_idx)
    assert render_idx > restore_idx


def test_app_js_save_called_on_individual_pill_dismissal():
    """saveBoardPrefs must be called when a single filter pill is dismissed (✕ button)."""
    js = _read_static("app.js")
    # Find the pill.onclick handler inside renderFilterSummary
    idx = js.find("pill.onclick")
    assert idx != -1
    handler_block = js[idx : idx + 200]
    assert "saveBoardPrefs()" in handler_block


def test_app_js_restore_handles_missing_data():
    """restoreBoardPrefs must handle missing/corrupt localStorage gracefully."""
    js = _read_static("app.js")
    restore_start = js.find("function restoreBoardPrefs()")
    restore_end = js.find("async function loadBoards", restore_start)
    restore_body = js[restore_start:restore_end]
    # Must have try/catch for JSON.parse errors
    assert "try {" in restore_body
    assert "catch" in restore_body
    # Must return early if no saved data
    assert "if (!raw) return" in restore_body or "if (raw === null) return" in restore_body


def test_app_js_save_handles_storage_errors():
    """saveBoardPrefs must handle localStorage errors gracefully."""
    js = _read_static("app.js")
    save_start = js.find("function saveBoardPrefs()")
    save_end = js.find("function restoreBoardPrefs()", save_start)
    save_body = js[save_start:save_end]
    assert "try {" in save_body
    assert "catch" in save_body
