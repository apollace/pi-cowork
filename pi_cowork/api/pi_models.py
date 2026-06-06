"""pi CLI model discovery with caching."""

import json
import logging
import os
import re
import shutil
import subprocess
import threading
import time

from flask import Blueprint, jsonify

logger = logging.getLogger(__name__)

pi_models_bp = Blueprint("pi_models", __name__)

# ---------------------------------------------------------------------------
# Cache
# ---------------------------------------------------------------------------

_cache = {}
_cache_lock = threading.Lock()
_CACHE_TTL_SECONDS = 300  # 5 minutes

DEFAULT_THINKING_LEVELS = ("off", "minimal", "low", "medium", "high", "xhigh")
FALLBACK_MODELS = []


# ---------------------------------------------------------------------------
# Node.js helper to resolve per-model thinking levels
# ---------------------------------------------------------------------------


def _get_pi_nodejs_paths():
    """Resolve absolute paths to pi's internal Node.js modules.

    Returns a dict with keys:
        models_js, model_registry_js, auth_storage_js, config_js
    or None if any required file is missing.
    """
    pi_path = shutil.which("pi")
    if not pi_path:
        return None
    real = os.path.realpath(pi_path)
    current = os.path.dirname(real)
    coding_agent_dir = None
    # Walk upward until we find the pi-coding-agent package root
    # (directory containing dist/core/model-registry.js, dist/core/auth-storage.js, dist/config.js)
    while current and current != os.path.dirname(current):
        if (
            os.path.isfile(os.path.join(current, "dist", "core", "model-registry.js"))
            and os.path.isfile(os.path.join(current, "dist", "core", "auth-storage.js"))
            and os.path.isfile(os.path.join(current, "dist", "config.js"))
        ):
            coding_agent_dir = current
            break
        current = os.path.dirname(current)
    if not coding_agent_dir:
        return None

    # pi-ai may be nested inside pi-coding-agent/node_modules or deduped at the same level
    pi_ai_dist = None
    candidates = [
        os.path.join(coding_agent_dir, "node_modules", "@earendil-works", "pi-ai", "dist"),
        os.path.join(
            os.path.dirname(os.path.dirname(coding_agent_dir)),
            "@earendil-works",
            "pi-ai",
            "dist",
        ),
    ]
    for candidate in candidates:
        if os.path.isfile(os.path.join(candidate, "models.js")):
            pi_ai_dist = candidate
            break
    if not pi_ai_dist:
        return None

    paths = {
        "models_js": os.path.join(pi_ai_dist, "models.js"),
        "model_registry_js": os.path.join(coding_agent_dir, "dist", "core", "model-registry.js"),
        "auth_storage_js": os.path.join(coding_agent_dir, "dist", "core", "auth-storage.js"),
        "config_js": os.path.join(coding_agent_dir, "dist", "config.js"),
    }
    for v in paths.values():
        if not os.path.isfile(v):
            return None
    return paths


def _fetch_thinking_levels_map() -> dict:
    """Run a Node.js subprocess to extract per-model thinking levels.

    Returns a dict mapping ``provider/model_id`` to a list of supported
    thinking level strings.  Returns an empty dict on any failure so callers
    can fall back to boolean-based logic.
    """
    paths = _get_pi_nodejs_paths()
    if not paths:
        return {}

    # Build a one-off Node.js script using absolute require paths so it
    # works regardless of the current working directory.
    script = (
        f'const {{ ModelRegistry }} = require("{paths["model_registry_js"]}");\n'
        f'const {{ AuthStorage }} = require("{paths["auth_storage_js"]}");\n'
        f'const {{ getAgentDir }} = require("{paths["config_js"]}");\n'
        f'const {{ getSupportedThinkingLevels }} = require("{paths["models_js"]}");\n'
        'const path = require("path");\n'
        "const auth = AuthStorage.create(getAgentDir());\n"
        'const registry = ModelRegistry.create(auth, path.join(getAgentDir(), "models.json"));\n'
        "const result = {};\n"
        "for (const m of registry.getAll()) {\n"
        '  result[m.provider + "/" + m.id] = getSupportedThinkingLevels(m);\n'
        "}\n"
        "console.log(JSON.stringify(result));\n"
    )

    try:
        result = subprocess.run(
            ["node", "-e", script],
            capture_output=True,
            text=True,
            timeout=10,
        )
        if result.returncode == 0 and result.stdout.strip():
            return json.loads(result.stdout.strip())
        if result.returncode != 0 and result.stderr.strip():
            logger.warning("Node.js thinking-level helper failed: %s", result.stderr.strip())
    except Exception as e:
        logger.warning("Node.js thinking-level helper failed: %s", e)

    return {}


# ---------------------------------------------------------------------------
# Parser
# ---------------------------------------------------------------------------


def _parse_pi_list_models() -> dict:
    """Run `pi --list-models` and parse tabular output.

    Additionally calls a Node.js helper to resolve exact per-model thinking
    levels. Falls back to the boolean ``thinking`` field from the tabular
    output if the Node.js helper is unavailable.
    """
    try:
        result = subprocess.run(
            ["pi", "--list-models"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        output = result.stdout if result.stdout else result.stderr
    except Exception as e:
        logger.warning("pi --list-models failed: %s", e)
        return {"models": FALLBACK_MODELS, "thinking_levels": list(DEFAULT_THINKING_LEVELS)}

    lines = output.strip().splitlines()
    if not lines:
        return {"models": FALLBACK_MODELS, "thinking_levels": list(DEFAULT_THINKING_LEVELS)}

    header = lines[0]
    cols = re.split(r"\s{2,}", header.strip())
    if len(cols) < 6:
        return {"models": FALLBACK_MODELS, "thinking_levels": list(DEFAULT_THINKING_LEVELS)}

    # Try to enrich with exact per-model thinking levels from pi internals.
    thinking_map = _fetch_thinking_levels_map()
    if thinking_map:
        logger.info(
            "Enriched %d models with exact thinking levels from pi internals",
            len(thinking_map),
        )

    models = []
    for line in lines[1:]:
        if not line.strip():
            continue
        parts = re.split(r"\s{2,}", line.strip())
        if len(parts) < 6:
            continue
        provider, name, context, max_out, thinking_str, images_str = parts[:6]
        model_id = f"{provider}/{name}"
        thinking_bool = thinking_str.lower() in ("yes", "true", "1")

        # Prefer exact thinking levels from Node.js helper; fall back to boolean.
        exact_levels = thinking_map.get(model_id)
        if exact_levels is not None:
            thinking_levels = exact_levels
        elif thinking_bool:
            thinking_levels = list(DEFAULT_THINKING_LEVELS)
        else:
            thinking_levels = ["off"]

        models.append(
            {
                "id": model_id,
                "provider": provider,
                "name": name,
                "context": context,
                "max_out": max_out,
                "thinking": thinking_bool,
                "images": images_str.lower() in ("yes", "true", "1"),
                "thinking_levels": thinking_levels,
            }
        )

    return {"models": models, "thinking_levels": list(DEFAULT_THINKING_LEVELS)}


def get_pi_models() -> dict:
    """Return cached pi models data, refreshing if the TTL has expired."""
    with _cache_lock:
        now = time.monotonic()
        if _cache and (now - _cache.get("cached_at", 0)) < _CACHE_TTL_SECONDS:
            return _cache["data"]

    data = _parse_pi_list_models()

    with _cache_lock:
        _cache["data"] = data
        _cache["cached_at"] = time.monotonic()

    return data


def get_thinking_levels() -> tuple:
    """Return valid thinking levels from pi CLI (or fallback hardcoded list)."""
    return tuple(get_pi_models()["thinking_levels"])


def get_model_ids() -> tuple:
    """Return valid model ids from pi CLI (or empty tuple if CLI is unavailable)."""
    return tuple(m["id"] for m in get_pi_models()["models"])


# ---------------------------------------------------------------------------
# Route
# ---------------------------------------------------------------------------


@pi_models_bp.route("/api/pi-models", methods=["GET"])
def api_pi_models():
    return jsonify(get_pi_models())
