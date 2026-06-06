import json
from unittest.mock import MagicMock, patch

from pi_cowork.api import pi_models as pi_models_module


def _clear_cache():
    with pi_models_module._cache_lock:
        pi_models_module._cache.clear()


# ---------------------------------------------------------------------------
# _parse_pi_list_models
# ---------------------------------------------------------------------------


def test_parse_pi_list_models_parses_tabular_output():
    _clear_cache()
    mock_output = (
        "Provider  Name        Context  Max Out  Thinking  Images\n"
        "openai    gpt-4o      128k     4096     yes       yes\n"
        "anthropic  claude-3    200k     8192     no        yes\n"
        "openai    gpt-3.5     16k      4096     no        no\n"
    )
    with patch("pi_cowork.api.pi_models.subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(stdout=mock_output, stderr="", returncode=0)
        data = pi_models_module._parse_pi_list_models()

    assert len(data["models"]) == 3
    assert data["models"][0]["id"] == "openai/gpt-4o"
    assert data["models"][0]["thinking"] is True
    assert data["models"][0]["images"] is True
    assert data["models"][0]["thinking_levels"] == list(pi_models_module.DEFAULT_THINKING_LEVELS)
    assert data["models"][1]["id"] == "anthropic/claude-3"
    assert data["models"][1]["thinking"] is False
    assert data["models"][1]["images"] is True
    assert data["models"][1]["thinking_levels"] == ["off"]
    assert data["models"][2]["id"] == "openai/gpt-3.5"
    assert data["models"][2]["thinking"] is False
    assert data["models"][2]["images"] is False
    assert data["models"][2]["thinking_levels"] == ["off"]
    assert data["thinking_levels"] == list(pi_models_module.DEFAULT_THINKING_LEVELS)


def test_parse_pi_list_models_enriches_with_nodejs_map():
    _clear_cache()
    mock_output = (
        "Provider  Name        Context  Max Out  Thinking  Images\n"
        "openai    gpt-4o      128k     4096     yes       yes\n"
        "ollama    deepseek    1.0M     16.4K    yes       no\n"
    )
    fake_map = {
        "openai/gpt-4o": ["off", "minimal", "low", "medium", "high"],
        "ollama/deepseek": ["off", "minimal", "low", "medium", "high"],
    }
    with patch("pi_cowork.api.pi_models.subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(stdout=mock_output, stderr="", returncode=0)
        with patch(
            "pi_cowork.api.pi_models._fetch_thinking_levels_map",
            return_value=fake_map,
        ):
            data = pi_models_module._parse_pi_list_models()

    assert len(data["models"]) == 2
    assert data["models"][0]["thinking_levels"] == ["off", "minimal", "low", "medium", "high"]
    assert data["models"][1]["thinking_levels"] == ["off", "minimal", "low", "medium", "high"]


def test_parse_pi_list_models_enriches_missing_model_fallback():
    """Models not present in the Node.js map fall back to boolean logic."""
    _clear_cache()
    mock_output = (
        "Provider  Name        Context  Max Out  Thinking  Images\n"
        "openai    gpt-4o      128k     4096     yes       yes\n"
        "anthropic  claude-3    200k     8192     no        yes\n"
    )
    fake_map = {
        "openai/gpt-4o": ["off", "minimal", "low", "medium", "high"],
        # claude-3 missing -> should fall back
    }
    with patch("pi_cowork.api.pi_models.subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(stdout=mock_output, stderr="", returncode=0)
        with patch(
            "pi_cowork.api.pi_models._fetch_thinking_levels_map",
            return_value=fake_map,
        ):
            data = pi_models_module._parse_pi_list_models()

    assert data["models"][0]["thinking_levels"] == ["off", "minimal", "low", "medium", "high"]
    assert data["models"][1]["thinking_levels"] == ["off"]


def test_parse_pi_list_models_ignores_malformed_lines():
    _clear_cache()
    mock_output = (
        "Provider  Name        Context  Max Out  Thinking  Images\n"
        "openai    gpt-4o      128k     4096     yes       yes\n"
        "badline\n"
    )
    with patch("pi_cowork.api.pi_models.subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(stdout=mock_output, stderr="", returncode=0)
        data = pi_models_module._parse_pi_list_models()

    assert len(data["models"]) == 1
    assert data["models"][0]["id"] == "openai/gpt-4o"


def test_parse_pi_list_models_falls_back_on_exception():
    _clear_cache()
    with patch("pi_cowork.api.pi_models.subprocess.run", side_effect=FileNotFoundError):
        data = pi_models_module._parse_pi_list_models()
    assert data["models"] == []
    assert data["thinking_levels"] == list(pi_models_module.DEFAULT_THINKING_LEVELS)


def test_parse_pi_list_models_falls_back_on_short_header():
    _clear_cache()
    mock_output = "Provider  Name\nopenai  gpt-4o\n"
    with patch("pi_cowork.api.pi_models.subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(stdout=mock_output, stderr="", returncode=0)
        data = pi_models_module._parse_pi_list_models()
    assert data["models"] == []
    assert data["thinking_levels"] == list(pi_models_module.DEFAULT_THINKING_LEVELS)


def test_parse_pi_list_models_uses_stderr_when_stdout_empty():
    _clear_cache()
    mock_output = (
        "Provider  Name        Context  Max Out  Thinking  Images\n"
        "openai    gpt-4o      128k     4096     yes       yes\n"
    )
    with patch("pi_cowork.api.pi_models.subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(stdout="", stderr=mock_output, returncode=0)
        data = pi_models_module._parse_pi_list_models()
    assert len(data["models"]) == 1
    assert data["models"][0]["id"] == "openai/gpt-4o"


# ---------------------------------------------------------------------------
# _fetch_thinking_levels_map
# ---------------------------------------------------------------------------


def test_fetch_thinking_levels_map_returns_json():
    _clear_cache()
    fake_nodejs_output = json.dumps(
        {
            "openai/gpt-4o": ["off", "minimal", "low", "medium", "high", "xhigh"],
            "ollama/custom": ["off", "minimal"],
        }
    )

    def _fake_isfile(path):
        return True

    with (
        patch(
            "pi_cowork.api.pi_models._get_pi_nodejs_paths",
            return_value={
                "models_js": "/fake/models.js",
                "model_registry_js": "/fake/model-registry.js",
                "auth_storage_js": "/fake/auth-storage.js",
                "config_js": "/fake/config.js",
            },
        ),
        patch("pi_cowork.api.pi_models.os.path.isfile", side_effect=_fake_isfile),
    ):
        with patch("pi_cowork.api.pi_models.subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(
                stdout=fake_nodejs_output,
                stderr="",
                returncode=0,
            )
            result = pi_models_module._fetch_thinking_levels_map()

    assert result == {
        "openai/gpt-4o": ["off", "minimal", "low", "medium", "high", "xhigh"],
        "ollama/custom": ["off", "minimal"],
    }


def test_fetch_thinking_levels_map_returns_empty_on_node_failure():
    _clear_cache()
    with (
        patch(
            "pi_cowork.api.pi_models._get_pi_nodejs_paths",
            return_value={
                "models_js": "/fake/models.js",
                "model_registry_js": "/fake/model-registry.js",
                "auth_storage_js": "/fake/auth-storage.js",
                "config_js": "/fake/config.js",
            },
        ),
        patch("pi_cowork.api.pi_models.subprocess.run") as mock_run,
    ):
        mock_run.return_value = MagicMock(
            stdout="",
            stderr="some error",
            returncode=1,
        )
        result = pi_models_module._fetch_thinking_levels_map()

    assert result == {}


def test_fetch_thinking_levels_map_returns_empty_when_paths_missing():
    _clear_cache()
    with patch("pi_cowork.api.pi_models._get_pi_nodejs_paths", return_value=None):
        result = pi_models_module._fetch_thinking_levels_map()
    assert result == {}


# ---------------------------------------------------------------------------
# get_pi_models caching
# ---------------------------------------------------------------------------


def test_get_pi_models_caches_result():
    _clear_cache()
    call_count = [0]

    def fake_parse():
        call_count[0] += 1
        return {
            "models": [{"id": "test"}],
            "thinking_levels": list(pi_models_module.DEFAULT_THINKING_LEVELS),
        }

    with patch("pi_cowork.api.pi_models._parse_pi_list_models", side_effect=fake_parse):
        d1 = pi_models_module.get_pi_models()
        assert call_count[0] == 1
        assert d1["models"][0]["id"] == "test"

        d2 = pi_models_module.get_pi_models()
        assert call_count[0] == 1
        assert d2 == d1


def test_get_pi_models_refresh_after_ttl(monkeypatch):
    _clear_cache()
    fake_time = [0.0]
    monkeypatch.setattr(pi_models_module.time, "monotonic", lambda: fake_time[0])

    call_count = [0]

    def fake_parse():
        call_count[0] += 1
        return {
            "models": [{"id": f"v{call_count[0]}"}],
            "thinking_levels": list(pi_models_module.DEFAULT_THINKING_LEVELS),
        }

    with patch("pi_cowork.api.pi_models._parse_pi_list_models", side_effect=fake_parse):
        d1 = pi_models_module.get_pi_models()
        assert d1["models"][0]["id"] == "v1"

        fake_time[0] = 10
        d2 = pi_models_module.get_pi_models()
        assert d2["models"][0]["id"] == "v1"

        fake_time[0] = 400
        d3 = pi_models_module.get_pi_models()
        assert d3["models"][0]["id"] == "v2"


# ---------------------------------------------------------------------------
# /api/pi-models endpoint
# ---------------------------------------------------------------------------


def test_api_pi_models_endpoint(client):
    _clear_cache()
    mock_output = (
        "Provider  Name        Context  Max Out  Thinking  Images\n"
        "openai    gpt-4o      128k     4096     yes       yes\n"
    )
    with patch("pi_cowork.api.pi_models.subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(stdout=mock_output, stderr="", returncode=0)
        res = client.get("/api/pi-models")

    assert res.status_code == 200
    data = json.loads(res.data)
    assert "models" in data
    assert "thinking_levels" in data
    assert len(data["models"]) == 1
    assert data["models"][0]["id"] == "openai/gpt-4o"
    assert data["models"][0]["thinking"] is True
    assert data["models"][0]["images"] is True
    assert data["models"][0]["thinking_levels"] == list(pi_models_module.DEFAULT_THINKING_LEVELS)
    assert data["thinking_levels"] == list(pi_models_module.DEFAULT_THINKING_LEVELS)


def test_api_pi_models_fallback_when_pi_missing(client):
    _clear_cache()
    with patch("pi_cowork.api.pi_models.subprocess.run", side_effect=FileNotFoundError):
        res = client.get("/api/pi-models")
    assert res.status_code == 200
    data = json.loads(res.data)
    assert data["models"] == []
    assert data["thinking_levels"] == list(pi_models_module.DEFAULT_THINKING_LEVELS)


# ---------------------------------------------------------------------------
# get_thinking_levels
# ---------------------------------------------------------------------------


def test_get_thinking_levels_returns_tuple():
    _clear_cache()
    with patch("pi_cowork.api.pi_models.subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(stdout="", stderr="", returncode=0)
        levels = pi_models_module.get_thinking_levels()
    assert isinstance(levels, tuple)
    assert set(levels) == set(pi_models_module.DEFAULT_THINKING_LEVELS)


def test_get_model_ids_returns_tuple():
    _clear_cache()
    # Restore original implementation (conftest autouse mocks it for API tests)
    pi_models_module.get_model_ids = lambda: tuple(m["id"] for m in pi_models_module.get_pi_models()["models"])
    mock_output = (
        "Provider  Name        Context  Max Out  Thinking  Images\n"
        "openai    gpt-4o      128k     4096     yes       yes\n"
    )
    with patch("pi_cowork.api.pi_models.subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(stdout=mock_output, stderr="", returncode=0)
        ids = pi_models_module.get_model_ids()
    assert isinstance(ids, tuple)
    assert ids == ("openai/gpt-4o",)
