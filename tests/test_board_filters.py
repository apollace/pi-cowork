import json
import os


def _read_static(filename):
    """Read a static asset file from the project."""
    path = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'static', filename)
    with open(path) as f:
        return f.read()


def test_board_page_has_filter_controls(client):
    res = client.get('/board')
    assert res.status_code == 200
    html = res.data.decode('utf-8')
    assert 'ticket-search' in html
    assert 'priority-toggles' in html
    assert 'label-filters' in html
    assert 'Search tickets' in html
    # New dropdown structure
    assert 'filter-dropdown-btn' in html
    assert 'filter-dropdown-panel' in html
    assert 'filter-badge' in html
    assert 'filter-dropdown-section' in html
    # Terminal checkbox moved inside dropdown
    assert 'show-terminal' in html
    assert 'filter-dropdown-checkbox' in html


def test_board_filter_dropdown_sections(client):
    """Verify the dropdown panel contains Priority, Labels, and Display sections."""
    res = client.get('/board')
    assert res.status_code == 200
    html = res.data.decode('utf-8')
    # Section titles inside dropdown
    assert 'filter-dropdown-section-title' in html
    assert '>Priority<' in html
    assert '>Labels<' in html
    assert '>Display<' in html


def test_ticket_list_includes_body_priority_and_labels(client, default_board):
    wf_id = default_board['workflow_id']
    lbl = client.post('/api/labels', json={
        'name': 'Feature',
        'color': '#10b981',
        'workflow_id': wf_id,
    })
    lid = json.loads(lbl.data)['id']
    client.post('/api/tickets', json={
        'title': 'Searchable Ticket',
        'body': 'Look for me in search',
        'board_id': default_board['id'],
        'priority': 'Critical',
        'labels': [lid],
    })
    res = client.get(f'/api/tickets?board_id={default_board["id"]}')
    assert res.status_code == 200
    data = json.loads(res.data)
    assert len(data) == 1
    t = data[0]
    assert t['title'] == 'Searchable Ticket'
    assert t['body'] == 'Look for me in search'
    assert t['priority'] == 'Critical'
    assert 'labels' in t
    assert len(t['labels']) == 1
    assert t['labels'][0]['name'] == 'Feature'


def test_board_page_has_filter_badge_element(client):
    """The filter badge element exists in the HTML (JS updates visibility/count)."""
    res = client.get('/board')
    assert res.status_code == 200
    html = res.data.decode('utf-8')
    # Badge element with id filter-badge is present
    assert 'id="filter-badge"' in html
    # Badge starts hidden
    assert 'style="display:none"' in html


# ── Viewport-aware filter dropdown positioning tests ──

def test_filter_dropdown_css_has_right_alignment_class():
    """The stylesheet must include a .dropdown-right class for right-aligned panels."""
    css = _read_static('style.css')
    assert '.filter-dropdown-panel.dropdown-right' in css
    # Should set left:auto and right:0 to flip to right edge
    assert 'left: auto' in css
    assert 'right: 0' in css


def test_filter_dropdown_css_has_above_positioning_class():
    """The stylesheet must include a .dropdown-above class for above-trigger panels."""
    css = _read_static('style.css')
    assert '.filter-dropdown-panel.dropdown-above' in css
    # Should set top:auto and bottom value to position above trigger
    assert 'bottom: calc(100%' in css


def test_filter_dropdown_js_has_positioning_function():
    """The app.js must include positionFilterDropdown() for viewport-aware repositioning."""
    js = _read_static('app.js')
    assert 'positionFilterDropdown' in js
    # Should add the CSS classes based on overflow detection
    assert 'dropdown-right' in js
    assert 'dropdown-above' in js
    # Should use getBoundingClientRect for position calculation
    assert 'getBoundingClientRect' in js
    # Should check viewport dimensions
    assert 'window.innerWidth' in js
    assert 'window.innerHeight' in js


def test_filter_dropdown_js_repositions_on_open():
    """The toggleFilterDropdown function must call positionFilterDropdown when opening."""
    js = _read_static('app.js')
    # When opening the dropdown, positionFilterDropdown should be called
    # Find the part of toggleFilterDropdown that handles opening
    assert 'positionFilterDropdown()' in js


def test_filter_dropdown_js_handles_max_height():
    """When the panel doesn't fit above or below, max-height should be constrained."""
    js = _read_static('app.js')
    # Should set maxHeight when constrained
    assert 'maxHeight' in js
    # Should ensure overflow-y auto when constrained
    assert 'overflowY' in js


def test_filter_dropdown_js_repositions_on_resize_scroll():
    """The dropdown should reposition when the viewport changes (resize/scroll)."""
    js = _read_static('app.js')
    # Should listen for resize and scroll events
    assert "addEventListener('resize'" in js
    assert "addEventListener('scroll'" in js


def test_filter_dropdown_css_scrollable_class():
    """The stylesheet must include a .scrollable class for constrained panels."""
    css = _read_static('style.css')
    assert '.filter-dropdown-panel.scrollable' in css
    assert 'overflow-y: auto' in css


def test_filter_dropdown_mobile_css_respects_right_alignment():
    """Mobile media query should not override the dropdown-right positioning."""
    css = _read_static('style.css')
    # In mobile media query, dropdown-right should still work
    # Find the mobile media query section
    mobile_start = css.find('@media (max-width: 768px)')
    assert mobile_start != -1
    mobile_section = css[mobile_start:mobile_start + 2000]
    # Should have .dropdown-right rule in mobile
    assert 'dropdown-right' in mobile_section
