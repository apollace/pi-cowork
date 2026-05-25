"""Tests for UI review improvements (Ticket #79).

Tests verify:
- Toast notification system in base.html
- Markdown rendering library in base.html
- Global search input in sidebar
- Two-column ticket detail layout
- Breadcrumb navigation
- Priority toggle buttons instead of checkboxes
- Filter summary pills on board page
- Loading skeleton in board page
- Board assistant removed from board page
- Markdown content area in ticket description and comments
"""

import json


def test_base_html_has_toast_container(client):
    """base.html should include a toast notification container."""
    res = client.get('/board')
    assert res.status_code == 200
    html = res.data.decode('utf-8')
    assert 'toast-container' in html
    assert 'showToast' in html


def test_base_html_has_markdown_library(client):
    """base.html should include marked.js CDN for markdown rendering."""
    res = client.get('/board')
    assert res.status_code == 200
    html = res.data.decode('utf-8')
    assert 'marked' in html


def test_base_html_has_global_search(client):
    """base.html should include a global search input in the sidebar."""
    res = client.get('/board')
    assert res.status_code == 200
    html = res.data.decode('utf-8')
    assert 'global-search' in html


def test_base_html_has_render_markdown(client):
    """base.html should include a renderMarkdown function."""
    res = client.get('/board')
    assert res.status_code == 200
    html = res.data.decode('utf-8')
    assert 'renderMarkdown' in html


def test_board_has_priority_toggles(client):
    """Board page should have priority toggle buttons instead of checkboxes."""
    res = client.get('/board')
    assert res.status_code == 200
    html = res.data.decode('utf-8')
    assert 'priority-toggles' in html
    assert 'priority-toggle' in html
    # Should NOT have old priority-filters checkbox group
    assert 'priority-filters' not in html


def test_board_has_filter_summary(client):
    """Board page should have filter summary area for showing active filter pills."""
    res = client.get('/board')
    assert res.status_code == 200
    html = res.data.decode('utf-8')
    assert 'filter-summary' in html


def test_board_has_loading_skeleton(client):
    """Board page should have a loading skeleton for initial state."""
    res = client.get('/board')
    assert res.status_code == 200
    html = res.data.decode('utf-8')
    assert 'board-skeleton' in html
    assert 'skeleton' in html


def test_board_no_assistant(client):
    """Board page should NOT have the board assistant bubble or panel."""
    res = client.get('/board')
    assert res.status_code == 200
    html = res.data.decode('utf-8')
    assert 'board-assistant-bubble' not in html
    assert 'board-assistant-panel' not in html
    assert 'board_assistant.js' not in html


def test_ticket_detail_has_two_column_layout(client, default_board):
    """Ticket detail page should have a two-column layout with sidebar."""
    res = client.post('/api/tickets', json={
        'title': 'Layout Test',
        'board_id': default_board['id'],
    })
    tid = json.loads(res.data)['id']
    res = client.get(f'/ticket/{tid}')
    assert res.status_code == 200
    html = res.data.decode('utf-8')
    assert 'ticket-layout' in html
    assert 'ticket-main' in html
    assert 'ticket-sidebar' in html
    assert 'sidebar-card' in html
    assert 'sidebar-field-label' in html


def test_ticket_detail_has_breadcrumb(client, default_board):
    """Ticket detail page should have breadcrumb navigation."""
    res = client.post('/api/tickets', json={
        'title': 'Breadcrumb Test',
        'board_id': default_board['id'],
    })
    tid = json.loads(res.data)['id']
    res = client.get(f'/ticket/{tid}')
    assert res.status_code == 200
    html = res.data.decode('utf-8')
    assert 'breadcrumb' in html
    assert 'breadcrumb-sep' in html


def test_ticket_detail_has_markdown_description(client, default_board):
    """Ticket detail page should render description as markdown."""
    res = client.post('/api/tickets', json={
        'title': 'Markdown Test',
        'body': 'Hello **bold** world',
        'board_id': default_board['id'],
    })
    tid = json.loads(res.data)['id']
    res = client.get(f'/ticket/{tid}')
    assert res.status_code == 200
    html = res.data.decode('utf-8')
    assert 'markdown-content' in html
    assert 'ticket-description' in html


def test_ticket_form_has_breadcrumb(client, default_board):
    """New ticket form should have breadcrumb navigation."""
    res = client.get('/ticket/new')
    assert res.status_code == 200
    html = res.data.decode('utf-8')
    assert 'breadcrumb' in html


def test_ticket_edit_has_breadcrumb(client, default_board):
    """Edit ticket form should have breadcrumb navigation."""
    res = client.post('/api/tickets', json={
        'title': 'Edit Test',
        'board_id': default_board['id'],
    })
    tid = json.loads(res.data)['id']
    res = client.get(f'/ticket/{tid}/edit')
    assert res.status_code == 200
    html = res.data.decode('utf-8')
    assert 'breadcrumb' in html


def test_css_has_toast_styles():
    """style.css should include toast notification styles."""
    with open('static/style.css') as f:
        css = f.read()
    assert '.toast-container' in css
    assert '.toast-success' in css
    assert '.toast-error' in css
    assert '.toast-warning' in css
    assert '.toast-info' in css
    assert '@keyframes toast-in' in css
    assert '@keyframes toast-out' in css


def test_css_has_skeleton_styles():
    """style.css should include skeleton/loading state styles."""
    with open('static/style.css') as f:
        css = f.read()
    assert '.skeleton' in css
    assert '@keyframes skeleton-shimmer' in css


def test_css_has_filter_pill_styles():
    """style.css should include filter pill and toggle button styles."""
    with open('static/style.css') as f:
        css = f.read()
    assert '.filter-pill' in css
    assert '.filter-clear-all' in css
    assert '.priority-toggle' in css
    assert '.priority-toggles' in css


def test_css_has_two_column_layout():
    """style.css should include two-column ticket detail layout."""
    with open('static/style.css') as f:
        css = f.read()
    assert '.ticket-layout' in css
    assert '.ticket-main' in css
    assert '.ticket-sidebar' in css
    assert '.sidebar-card' in css


def test_css_has_markdown_styles():
    """style.css should include markdown content rendering styles."""
    with open('static/style.css') as f:
        css = f.read()
    assert '.markdown-content' in css
    assert '.markdown-content code' in css
    assert '.markdown-content pre' in css
    assert '.markdown-content blockquote' in css


def test_css_has_breadcrumb_styles():
    """style.css should include breadcrumb navigation styles."""
    with open('static/style.css') as f:
        css = f.read()
    assert '.breadcrumb' in css
    assert '.breadcrumb-sep' in css
    assert '.breadcrumb-current' in css


def test_css_has_global_search_styles():
    """style.css should include sidebar search input styles."""
    with open('static/style.css') as f:
        css = f.read()
    assert '.sidebar-search' in css


def test_css_has_section_card_styles():
    """style.css should include section card styles for ticket detail."""
    with open('static/style.css') as f:
        css = f.read()
    assert '.section-card' in css


def test_css_has_animation_styles():
    """style.css should include subtle animation styles."""
    with open('static/style.css') as f:
        css = f.read()
    assert '@keyframes fade-in' in css
    assert '@keyframes card-entrance' in css


def test_board_url_search_param(client):
    """Board page should accept a search URL parameter."""
    res = client.get('/board?search=test')
    assert res.status_code == 200