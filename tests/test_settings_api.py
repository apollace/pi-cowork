import json


def test_settings_list(client):
    """GET /api/settings returns a list of settings."""
    res = client.get("/api/settings")
    assert res.status_code == 200
    data = json.loads(res.data)
    assert isinstance(data, list)
    for item in data:
        assert "key" in item
        assert "value" in item
        assert "updated_at" in item


def test_get_setting(client):
    """GET /api/settings/<key> returns a single setting after it exists."""
    client.put("/api/settings/my_test_key", json={"value": "hello"})
    res = client.get("/api/settings/my_test_key")
    assert res.status_code == 200
    data = json.loads(res.data)
    assert data["key"] == "my_test_key"
    assert data["value"] == "hello"


def test_get_missing_setting(client):
    """GET /api/settings/<key> returns 404 for unknown keys."""
    res = client.get("/api/settings/nonexistent_key")
    assert res.status_code == 404
    data = json.loads(res.data)
    assert "error" in data


def test_update_setting(client):
    """PUT /api/settings/<key> updates a setting value."""
    res = client.put("/api/settings/my_test_key", json={"value": "text"})
    assert res.status_code == 200
    data = json.loads(res.data)
    assert data["success"] is True

    # Verify the change
    res = client.get("/api/settings/my_test_key")
    assert res.status_code == 200
    data = json.loads(res.data)
    assert data["value"] == "text"


def test_update_setting_missing_value(client):
    """PUT /api/settings/<key> without value returns 400."""
    res = client.put("/api/settings/my_test_key", json={})
    assert res.status_code == 400
    data = json.loads(res.data)
    assert "error" in data


def test_custom_setting_crud(client):
    """Settings API works for arbitrary keys."""
    res = client.put("/api/settings/my_custom_key", json={"value": "hello"})
    assert res.status_code == 200

    res = client.get("/api/settings/my_custom_key")
    assert res.status_code == 200
    data = json.loads(res.data)
    assert data["value"] == "hello"

    res = client.get("/api/settings")
    assert res.status_code == 200
    data = json.loads(res.data)
    keys = {item["key"] for item in data}
    assert "my_custom_key" in keys
