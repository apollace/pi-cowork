"""pi CLI model discovery with caching."""

import logging
import os
import re
import subprocess
import threading
import time

from flask import Blueprint, jsonify

logger = logging.getLogger(__name__)

pi_models_bp = Blueprint('pi_models', __name__)

# ---------------------------------------------------------------------------
# Cache
# ---------------------------------------------------------------------------

_cache = {}
_cache_lock = threading.Lock()
_CACHE_TTL_SECONDS = 300  # 5 minutes

DEFAULT_THINKING_LEVELS = ('off', 'minimal', 'low', 'medium', 'high', 'xhigh', 'max')
FALLBACK_MODELS = []


# ---------------------------------------------------------------------------
# Parser
# ---------------------------------------------------------------------------

def _parse_pi_list_models() -> dict:
    """Run `pi --list-models` and parse tabular output.

    Returns models with a ``thinking`` boolean field and a top-level
    ``thinking_levels`` array of fixed default levels.
    """
    try:
        result = subprocess.run(
            ['pi', '--list-models'],
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
    cols = re.split(r'\s{2,}', header.strip())
    if len(cols) < 6:
        return {"models": FALLBACK_MODELS, "thinking_levels": list(DEFAULT_THINKING_LEVELS)}

    models = []
    for line in lines[1:]:
        if not line.strip():
            continue
        parts = re.split(r'\s{2,}', line.strip())
        if len(parts) < 6:
            continue
        provider, name, context, max_out, thinking_str, images_str = parts[:6]
        model_id = f"{provider}/{name}"
        thinking_bool = thinking_str.lower() in ('yes', 'true', '1')

        models.append({
            "id": model_id,
            "provider": provider,
            "name": name,
            "context": context,
            "max_out": max_out,
            "thinking": thinking_bool,
            "images": images_str.lower() in ('yes', 'true', '1'),
        })

    return {"models": models, "thinking_levels": list(DEFAULT_THINKING_LEVELS)}


def get_pi_models() -> dict:
    """Return cached pi models data, refreshing if the TTL has expired."""
    with _cache_lock:
        now = time.monotonic()
        if _cache and (now - _cache.get('cached_at', 0)) < _CACHE_TTL_SECONDS:
            return _cache['data']

    data = _parse_pi_list_models()

    with _cache_lock:
        _cache['data'] = data
        _cache['cached_at'] = time.monotonic()

    return data


def get_thinking_levels() -> tuple:
    """Return valid thinking levels."""
    return DEFAULT_THINKING_LEVELS


def get_model_ids() -> tuple:
    """Return valid model ids from pi CLI (or empty tuple if CLI is unavailable)."""
    return tuple(m['id'] for m in get_pi_models()['models'])


# ---------------------------------------------------------------------------
# Route
# ---------------------------------------------------------------------------

@pi_models_bp.route('/api/pi-models', methods=['GET'])
def api_pi_models():
    return jsonify(get_pi_models())
