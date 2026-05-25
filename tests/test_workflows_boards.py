import json


def test_create_workflow(client):
    res = client.post('/api/workflows', json={
        'name': 'My Workflow',
        'description': 'A custom workflow',
    })
    assert res.status_code == 201
    data = json.loads(res.data)
    assert data['id']


def test_create_workflow_duplicate(client):
    client.post('/api/workflows', json={'name': 'Dup', 'description': 'd'})
    res = client.post('/api/workflows', json={'name': 'Dup', 'description': 'd2'})
    assert res.status_code == 409


def test_list_workflows(client):
    client.post('/api/workflows', json={'name': 'W1', 'description': 'd'})
    res = client.get('/api/workflows')
    assert res.status_code == 200
    data = json.loads(res.data)
    names = [w['name'] for w in data]
    assert 'W1' in names
    # Should have seeded default workflow too
    assert any('Default' in n for n in names)


def test_delete_workflow_blocked_by_board(client):
    res = client.post('/api/workflows', json={'name': 'Linked', 'description': 'd'})
    wf_id = json.loads(res.data)['id']
    client.post('/api/boards', json={'name': 'B1', 'workflow_id': wf_id})
    res = client.delete(f'/api/workflows/{wf_id}')
    assert res.status_code == 409


def test_delete_workflow_ok(client):
    res = client.post('/api/workflows', json={'name': 'Orphan', 'description': 'd'})
    wf_id = json.loads(res.data)['id']
    res = client.delete(f'/api/workflows/{wf_id}')
    assert res.status_code == 200


def test_create_board(client, default_workflow):
    res = client.post('/api/boards', json={
        'name': 'My Board',
        'workflow_id': default_workflow['id'],
    })
    assert res.status_code == 201
    data = json.loads(res.data)
    assert data['id']


def test_create_board_duplicate(client, default_workflow):
    client.post('/api/boards', json={'name': 'Dup', 'workflow_id': default_workflow['id']})
    res = client.post('/api/boards', json={'name': 'Dup', 'workflow_id': default_workflow['id']})
    assert res.status_code == 409


def test_list_boards(client, default_workflow):
    client.post('/api/boards', json={'name': 'B1', 'workflow_id': default_workflow['id']})
    res = client.get('/api/boards')
    assert res.status_code == 200
    data = json.loads(res.data)
    names = [b['name'] for b in data]
    assert 'B1' in names
    # Should have seeded default board
    assert any('Default' in n for n in names)
    # Check workflow name is included
    assert all('workflow_name' in b for b in data)


def test_update_board(client, default_workflow, new_workflow):
    res = client.post('/api/boards', json={
        'name': 'B2',
        'workflow_id': default_workflow['id'],
    })
    board_id = json.loads(res.data)['id']
    res = client.put(f'/api/boards/{board_id}', json={
        'name': 'B2 Updated',
        'workflow_id': new_workflow['id'],
    })
    assert res.status_code == 200
    res = client.get(f'/api/boards/{board_id}')
    data = json.loads(res.data)
    assert data['name'] == 'B2 Updated'
    assert data['workflow_id'] == new_workflow['id']


def test_delete_board_destroys_tickets(client, default_workflow, default_board):
    # Create a new board
    res = client.post('/api/boards', json={
        'name': 'DeleteMe',
        'workflow_id': default_workflow['id'],
    })
    board_id = json.loads(res.data)['id']
    
    # Create tickets on that board
    client.post('/api/tickets', json={
        'title': 'T1',
        'board_id': board_id,
    })
    client.post('/api/tickets', json={
        'title': 'T2',
        'board_id': board_id,
    })
    
    # Create a comment
    tickets = json.loads(client.get(f'/api/tickets?board_id={board_id}').data)
    client.post(f'/api/tickets/{tickets[0]["id"]}/comments', json={'body': 'test'})
    
    # Verify tickets exist
    res = client.get(f'/api/tickets?board_id={board_id}')
    assert len(json.loads(res.data)) == 2
    
    # Delete board
    res = client.delete(f'/api/boards/{board_id}')
    assert res.status_code == 200
    
    # Verify tickets are gone
    res = client.get(f'/api/tickets?board_id={board_id}')
    assert len(json.loads(res.data)) == 0


def test_multiple_boards_share_workflow(client, default_workflow):
    # Create two boards using the same workflow
    b1 = client.post('/api/boards', json={
        'name': 'Board 1',
        'workflow_id': default_workflow['id'],
    })
    b1_id = json.loads(b1.data)['id']
    b2 = client.post('/api/boards', json={
        'name': 'Board 2',
        'workflow_id': default_workflow['id'],
    })
    b2_id = json.loads(b2.data)['id']
    
    # Create tickets on each
    client.post('/api/tickets', json={'title': 'On Board 1', 'board_id': b1_id})
    client.post('/api/tickets', json={'title': 'On Board 2', 'board_id': b2_id})
    
    # Verify isolation
    t1 = json.loads(client.get(f'/api/tickets?board_id={b1_id}').data)
    assert len(t1) == 1
    assert t1[0]['title'] == 'On Board 1'
    
    t2 = json.loads(client.get(f'/api/tickets?board_id={b2_id}').data)
    assert len(t2) == 1
    assert t2[0]['title'] == 'On Board 2'


# --- Long-Term Vision tests (Ticket #39) ---


def test_create_board_with_long_term_vision(client, default_workflow):
    res = client.post('/api/boards', json={
        'name': 'Vision Board',
        'workflow_id': default_workflow['id'],
        'long_term_vision': 'Become the leading platform for AI-assisted project management.',
    })
    assert res.status_code == 201
    board_id = json.loads(res.data)['id']
    # Verify returned in GET
    res = client.get(f'/api/boards/{board_id}')
    assert res.status_code == 200
    data = json.loads(res.data)
    assert data['long_term_vision'] == 'Become the leading platform for AI-assisted project management.'


def test_create_board_without_long_term_vision(client, default_workflow):
    res = client.post('/api/boards', json={
        'name': 'No Vision Board',
        'workflow_id': default_workflow['id'],
    })
    assert res.status_code == 201
    board_id = json.loads(res.data)['id']
    # Verify field is null/empty in GET
    res = client.get(f'/api/boards/{board_id}')
    assert res.status_code == 200
    data = json.loads(res.data)
    assert data.get('long_term_vision') is None or data.get('long_term_vision') == ''


def test_update_board_long_term_vision(client, default_workflow):
    res = client.post('/api/boards', json={
        'name': 'Upd Vision Board',
        'workflow_id': default_workflow['id'],
    })
    board_id = json.loads(res.data)['id']
    # Set long_term_vision via PUT
    res = client.put(f'/api/boards/{board_id}', json={
        'long_term_vision': 'Enable seamless human-AI collaboration at scale.',
    })
    assert res.status_code == 200
    # Verify updated in GET
    res = client.get(f'/api/boards/{board_id}')
    data = json.loads(res.data)
    assert data['long_term_vision'] == 'Enable seamless human-AI collaboration at scale.'


def test_clear_board_long_term_vision(client, default_workflow):
    res = client.post('/api/boards', json={
        'name': 'Clear Vision Board',
        'workflow_id': default_workflow['id'],
        'long_term_vision': 'This will be cleared.',
    })
    board_id = json.loads(res.data)['id']
    # Clear via PUT with empty string
    res = client.put(f'/api/boards/{board_id}', json={
        'long_term_vision': '',
    })
    assert res.status_code == 200
    # Verify cleared in GET
    res = client.get(f'/api/boards/{board_id}')
    data = json.loads(res.data)
    assert data.get('long_term_vision') is None or data.get('long_term_vision') == ''
