"""Filesystem package helpers for the directory-based skills system.

Skills are stored as directory packages under:
    {skills_folder_path}/{workflow_id}/{skill_name}/

Each package contains:
    - SKILL.md with YAML frontmatter (name, description) + markdown content
    - Optional subdirectories: examples/, tests/, schemas/, templates/, etc.
"""

import io
import os
import re
import shutil
import zipfile
from pathlib import Path

_SKILL_NAME_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")


def get_skills_folder():
    """Return the configured global skills folder path."""
    from pi_cowork.config import get_config

    return get_config("skills_folder_path") or "workspace/skills"


def get_skill_dir(workflow_id, name):
    """Return the filesystem path for a skill package."""
    return os.path.join(get_skills_folder(), str(workflow_id), name)


def _parse_frontmatter(text):
    """Parse simple YAML frontmatter from text.

    Supports basic key: value pairs and quoted strings.
    Returns (metadata_dict, content_str).
    """
    if not text.startswith("---"):
        return {}, text
    parts = text.split("---", 2)
    if len(parts) < 3:
        return {}, text
    fm_text = parts[1].strip()
    content = parts[2].strip()
    meta = {}
    for line in fm_text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if ":" not in line:
            continue
        key, val = line.split(":", 1)
        key = key.strip()
        val = val.strip()
        if val.startswith('"') and val.endswith('"'):
            val = val[1:-1].replace('\\"', '"')
        elif val.startswith("'") and val.endswith("'"):
            val = val[1:-1].replace("\\'", "'")
        meta[key] = val
    return meta, content


def read_skill_package(skill_dir):
    """Read a skill package from disk.

    Returns dict with name, description, content, subdirs, or None if not found.
    """
    skill_md = os.path.join(skill_dir, "SKILL.md")
    if not os.path.isfile(skill_md):
        return None
    try:
        with open(skill_md, encoding="utf-8") as f:
            text = f.read()
    except (OSError, UnicodeDecodeError):
        return None
    meta, content = _parse_frontmatter(text)
    subdirs = []
    if os.path.isdir(skill_dir):
        for entry in sorted(os.listdir(skill_dir)):
            entry_path = os.path.join(skill_dir, entry)
            if os.path.isdir(entry_path) and not entry.startswith("."):
                subdirs.append(entry)
    return {
        "name": meta.get("name"),
        "description": meta.get("description"),
        "content": content,
        "subdirs": subdirs,
    }


def write_skill_package(skill_dir, name, description, content):
    """Write or update a skill package on disk."""
    Path(skill_dir).mkdir(parents=True, exist_ok=True)
    lines = ["---", f"name: {name}"]
    if description:
        safe_desc = description.replace('"', '\\"')
        lines.append(f'description: "{safe_desc}"')
    else:
        lines.append('description: ""')
    lines.append("---")
    lines.append("")
    lines.append(content or "")
    skill_md = os.path.join(skill_dir, "SKILL.md")
    with open(skill_md, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    return skill_md


def delete_skill_package(skill_dir):
    """Remove a skill package directory."""
    if os.path.isdir(skill_dir):
        shutil.rmtree(skill_dir, ignore_errors=True)


def rename_skill_package(skill_dir, new_name):
    """Rename a skill package directory.

    Returns the new path, or None if the target already exists.
    """
    parent = os.path.dirname(skill_dir)
    new_dir = os.path.join(parent, new_name)
    if os.path.exists(new_dir):
        return None
    os.rename(skill_dir, new_dir)
    return new_dir


def validate_skill_dir_name(name):
    """Validate that a skill name matches directory naming conventions."""
    if not name:
        return "name is required"
    if len(name) > 64:
        return "name must be 64 characters or fewer"
    if not _SKILL_NAME_RE.match(name):
        return "name must be lowercase letters, numbers, and single hyphens (no leading/trailing/consecutive hyphens)"
    return None


def copy_skill_to_session(skill_dir, session_skill_dir):
    """Copy a full skill package to a session directory for agent spawn."""
    if os.path.exists(session_skill_dir):
        shutil.rmtree(session_skill_dir, ignore_errors=True)
    if os.path.isdir(skill_dir):
        shutil.copytree(skill_dir, session_skill_dir)
    return session_skill_dir


def import_skill_from_zip(file_storage, workflow_id):
    """Import a skill from an uploaded ZIP file.

    Args:
        file_storage: Flask FileStorage object (request.files['file']).
        workflow_id: Workflow ID to import into.

    Returns:
        (skill_info_dict, error_string).  error_string is None on success.
    """
    import tempfile

    with tempfile.TemporaryDirectory() as tmpdir:
        try:
            with zipfile.ZipFile(io.BytesIO(file_storage.read()), "r") as zf:
                zf.extractall(tmpdir)
        except zipfile.BadZipFile:
            return None, "Invalid ZIP file"

        entries = [e for e in os.listdir(tmpdir) if e != "upload.zip"]
        if not entries:
            return None, "ZIP is empty"

        # If a single top-level directory exists, treat it as the package root
        if len(entries) == 1 and os.path.isdir(os.path.join(tmpdir, entries[0])):
            root_dir = os.path.join(tmpdir, entries[0])
        else:
            root_dir = tmpdir

        skill_md = os.path.join(root_dir, "SKILL.md")
        if not os.path.isfile(skill_md):
            return None, "ZIP must contain a SKILL.md file at the package root"

        with open(skill_md, encoding="utf-8") as f:
            text = f.read()

        meta, content = _parse_frontmatter(text)
        name = meta.get("name")
        if not name:
            return None, "SKILL.md frontmatter must include a name field"

        error = validate_skill_dir_name(name)
        if error:
            return None, error

        target_dir = get_skill_dir(workflow_id, name)
        if os.path.exists(target_dir):
            return None, f"Skill '{name}' already exists in this workflow"

        shutil.copytree(root_dir, target_dir)

        return {
            "name": name,
            "description": meta.get("description"),
            "content": content,
        }, None
