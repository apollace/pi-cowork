import json


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