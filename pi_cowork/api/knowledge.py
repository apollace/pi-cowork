"""API: Knowledge management — CRUD, search, version history."""

from flask import Blueprint, jsonify, request

from pi_cowork.db import query_db
from pi_cowork.models import (
    get_knowledge_entries, get_knowledge_entry, create_knowledge_entry,
    update_knowledge_entry, delete_knowledge_entry, search_knowledge,
    get_knowledge_versions, get_knowledge_version, restore_knowledge_version,
    get_knowledge_categories, get_all_tags, get_board,
)

knowledge_bp = Blueprint('knowledge', __name__)


# ── CRUD ──

@knowledge_bp.route('/api/knowledge', methods=['GET'])
def api_knowledge_list():
    """List knowledge entries with optional filters.

    Query params: board_id, search, category, auto_context, tags (comma-separated)
    When board_id is provided, returns both global and board-specific entries.
    When board_id is omitted, returns only global entries.
    """
    board_id = request.args.get('board_id', type=int)
    search = request.args.get('search')
    category = request.args.get('category')
    auto_context = request.args.get('auto_context', type=int)
    tags_param = request.args.get('tags')

    # Convert auto_context from query param
    auto_context_val = None
    if auto_context is not None:
        auto_context_val = bool(auto_context)

    # Parse tags
    tags = None
    if tags_param:
        tags = [t.strip() for t in tags_param.split(',') if t.strip()]

    entries = get_knowledge_entries(
        board_id=board_id, search=search, category=category,
        auto_context=auto_context_val, tags=tags
    )
    return jsonify(entries)


@knowledge_bp.route('/api/knowledge/<int:entry_id>', methods=['GET'])
def api_knowledge_get(entry_id):
    """Get a single knowledge entry with tags."""
    entry = get_knowledge_entry(entry_id)
    if not entry:
        return jsonify({"error": "Knowledge entry not found"}), 404
    return jsonify(entry)


@knowledge_bp.route('/api/knowledge', methods=['POST'])
def api_knowledge_create():
    """Create a knowledge entry.

    Fields: title (required), content (required), board_id, category,
    auto_context, tags (array of tag name strings), sort_order, created_by
    """
    data = request.get_json(silent=True) or {}
    title = (data.get('title') or '').strip()
    content = data.get('content')
    if not title:
        return jsonify({"error": "title is required"}), 400
    if content is None or content.strip() == '':
        return jsonify({"error": "content is required"}), 400

    board_id = data.get('board_id')
    if board_id is not None:
        try:
            board_id = int(board_id)
        except (ValueError, TypeError):
            return jsonify({"error": "board_id must be an integer"}), 400
        board = get_board(board_id)
        if not board:
            return jsonify({"error": "Board not found"}), 404

    category = data.get('category') or None
    auto_context = bool(data.get('auto_context', False))
    tags = data.get('tags')
    sort_order = data.get('sort_order', 0)
    try:
        sort_order = int(sort_order)
    except (ValueError, TypeError):
        sort_order = 0
    created_by = data.get('created_by', 'human')
    # Only allow 'human' or 'agent'
    if created_by not in ('human', 'agent'):
        created_by = 'human'

    entry = create_knowledge_entry(
        title=title, content=content, board_id=board_id,
        category=category, auto_context=auto_context,
        tags=tags, sort_order=sort_order, created_by=created_by
    )
    return jsonify(entry), 201


@knowledge_bp.route('/api/knowledge/<int:entry_id>', methods=['PUT'])
def api_knowledge_update(entry_id):
    """Update a knowledge entry. Auto-creates version record.

    Fields: title, content, board_id (0=no change, null=global, int=specific board),
    category, auto_context, tags (array of tag name strings), sort_order, updated_by
    """
    existing = get_knowledge_entry(entry_id)
    if not existing:
        return jsonify({"error": "Knowledge entry not found"}), 404

    data = request.get_json(silent=True) or {}
    title = data.get('title')
    content = data.get('content')
    board_id = data.get('board_id', 0)  # 0 sentinel = not changed
    category = data.get('category')
    auto_context = data.get('auto_context')
    tags = data.get('tags')
    sort_order = data.get('sort_order')
    updated_by = data.get('updated_by', 'human')
    if updated_by not in ('human', 'agent'):
        updated_by = 'human'

    # Validate board_id if explicitly set
    if board_id != 0 and board_id is not None:
        try:
            board_id = int(board_id)
        except (ValueError, TypeError):
            return jsonify({"error": "board_id must be an integer or null"}), 400
        board = get_board(board_id)
        if not board:
            return jsonify({"error": "Board not found"}), 404

    if title is not None:
        title = title.strip()
        if not title:
            return jsonify({"error": "title cannot be empty"}), 400
    if content is not None:
        if content.strip() == '':
            return jsonify({"error": "content cannot be empty"}), 400

    entry = update_knowledge_entry(
        entry_id, title=title, content=content, board_id=board_id,
        category=category, auto_context=auto_context, tags=tags,
        sort_order=sort_order, updated_by=updated_by
    )
    return jsonify(entry)


@knowledge_bp.route('/api/knowledge/<int:entry_id>', methods=['DELETE'])
def api_knowledge_delete(entry_id):
    """Delete a knowledge entry (cascades versions + tags)."""
    existing = get_knowledge_entry(entry_id)
    if not existing:
        return jsonify({"error": "Knowledge entry not found"}), 404
    delete_knowledge_entry(entry_id)
    return jsonify({"success": True})


# ── Search ──

@knowledge_bp.route('/api/knowledge/search', methods=['GET'])
def api_knowledge_search():
    """Full-text search across title + content, filtered by board scope.

    Query params: q (required), board_id (optional)
    Returns global + board-specific matches.
    """
    q = request.args.get('q', '').strip()
    if not q:
        return jsonify({"error": "q parameter is required"}), 400

    board_id = request.args.get('board_id', type=int)
    results = search_knowledge(q, board_id=board_id)
    return jsonify(results)


# ── Version History ──

@knowledge_bp.route('/api/knowledge/<int:entry_id>/versions', methods=['GET'])
def api_knowledge_versions(entry_id):
    """List all versions of a knowledge entry."""
    existing = get_knowledge_entry(entry_id)
    if not existing:
        return jsonify({"error": "Knowledge entry not found"}), 404
    versions = get_knowledge_versions(entry_id)
    return jsonify(versions)


@knowledge_bp.route('/api/knowledge/<int:entry_id>/versions/<int:version_id>', methods=['GET'])
def api_knowledge_version_get(entry_id, version_id):
    """Get a specific version of a knowledge entry."""
    existing = get_knowledge_entry(entry_id)
    if not existing:
        return jsonify({"error": "Knowledge entry not found"}), 404
    version = get_knowledge_version(entry_id, version_id)
    if not version:
        return jsonify({"error": "Version not found"}), 404
    return jsonify(version)


@knowledge_bp.route('/api/knowledge/<int:entry_id>/versions/<int:version_id>/restore', methods=['POST'])
def api_knowledge_version_restore(entry_id, version_id):
    """Restore a previous version as the current entry."""
    existing = get_knowledge_entry(entry_id)
    if not existing:
        return jsonify({"error": "Knowledge entry not found"}), 404
    data = request.get_json(silent=True) or {}
    restored_by = data.get('restored_by', 'human')
    if restored_by not in ('human', 'agent'):
        restored_by = 'human'
    entry = restore_knowledge_version(entry_id, version_id, restored_by=restored_by)
    if not entry:
        return jsonify({"error": "Version not found"}), 404
    return jsonify(entry)


# ── Metadata ──

@knowledge_bp.route('/api/knowledge/categories', methods=['GET'])
def api_knowledge_categories():
    """Get distinct categories for knowledge entries."""
    board_id = request.args.get('board_id', type=int)
    categories = get_knowledge_categories(board_id=board_id)
    return jsonify(categories)


@knowledge_bp.route('/api/knowledge/tags', methods=['GET'])
def api_knowledge_tags():
    """Get all knowledge tags."""
    tags = get_all_tags()
    return jsonify(tags)