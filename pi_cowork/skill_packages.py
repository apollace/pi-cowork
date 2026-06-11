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
import urllib.request
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
    lines = text.splitlines()
    if lines[0].strip() != "---":
        return {}, text
    end_idx = None
    for i in range(1, len(lines)):
        if lines[i].strip() == "---":
            end_idx = i
            break
    if end_idx is None:
        return {}, text
    fm_text = "\n".join(lines[1:end_idx]).strip()
    content = "\n".join(lines[end_idx + 1 :]).strip()
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
            val = val[1:-1]
            # Unescape basic sequences: \\ -> \, \" -> ", \n -> newline, \r -> carriage return
            val = val.replace("\\\\", "\x00").replace('\\"', '"').replace("\\n", "\n").replace("\\r", "\r")
            val = val.replace("\x00", "\\")
        elif val.startswith("'") and val.endswith("'"):
            val = val[1:-1]
            val = val.replace("\\\\", "\x00").replace("\\'", "'").replace("\\n", "\n").replace("\\r", "\r")
            val = val.replace("\x00", "\\")
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
        # Proper YAML inline-string escaping
        safe_desc = description.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n").replace("\r", "\\r")
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


def get_built_in_skills_folder():
    """Return the path to built-in/system skills that ship with the app.

    Resolved relative to this module so it works regardless of cwd.
    """
    return os.path.join(os.path.dirname(os.path.dirname(__file__)), "skills")


def get_built_in_skill_names():
    """Return a sorted list of built-in/system skill names from the repo skills/ directory.

    Returns an empty list if the directory does not exist or is empty.
    """
    folder = get_built_in_skills_folder()
    if not os.path.isdir(folder):
        return []
    names = []
    for entry in sorted(os.listdir(folder)):
        entry_path = os.path.join(folder, entry)
        if os.path.isdir(entry_path) and not entry.startswith("."):
            pkg = read_skill_package(entry_path)
            if pkg is not None:
                names.append(pkg.get("name") or entry)
    return sorted(names)


def get_global_skill_dir(name):
    """Return the filesystem path for a global skill package."""
    return os.path.join(get_skills_folder(), "global", name)


def list_skills(workflow_id=None):
    """Scan filesystem for skill packages.

    Returns list of dicts: name, scope, description, subdirs.
    Scope is 'workflow', 'global', or 'system'.

    When workflow_id is provided, returns workflow + global + system skills
    with workflow scope taking precedence.
    When workflow_id is None, returns only global skills.
    """
    result = []
    seen = set()
    folder = get_skills_folder()
    scopes = []
    if workflow_id is not None:
        scopes.append(("workflow", os.path.join(folder, str(workflow_id))))
    scopes.append(("global", os.path.join(folder, "global")))
    if workflow_id is not None:
        scopes.append(("system", get_built_in_skills_folder()))
    for scope, path in scopes:
        if not os.path.isdir(path):
            continue
        try:
            entries = sorted(os.listdir(path))
        except FileNotFoundError:
            continue
        for entry in entries:
            entry_path = os.path.join(path, entry)
            if not os.path.isdir(entry_path) or entry.startswith("."):
                continue
            pkg = read_skill_package(entry_path)
            if pkg is None:
                continue
            name = pkg.get("name") or entry
            if name in seen:
                continue
            seen.add(name)
            subdirs = []
            for sub in sorted(os.listdir(entry_path)):
                sub_path = os.path.join(entry_path, sub)
                if os.path.isdir(sub_path) and not sub.startswith("."):
                    subdirs.append(sub)
            result.append(
                {
                    "name": name,
                    "scope": scope,
                    "description": pkg.get("description"),
                    "subdirs": subdirs,
                }
            )
    return result


def resolve_skill_dir(workflow_id, name):
    """Resolve a skill name to its filesystem directory.

    Workflow-scoped skills take precedence over global ones,
    which take precedence over built-in/system ones.
    Returns the directory path or None if not found.
    """
    wf_dir = get_skill_dir(workflow_id, name)
    if os.path.isdir(wf_dir):
        return wf_dir
    global_dir = get_global_skill_dir(name)
    if os.path.isdir(global_dir):
        return global_dir
    built_in_dir = os.path.join(get_built_in_skills_folder(), name)
    if os.path.isdir(built_in_dir):
        return built_in_dir
    return None


def is_built_in_skill(name):
    """Check whether a skill name exists in the built-in/system folder."""
    return os.path.isdir(os.path.join(get_built_in_skills_folder(), name))


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


_GITHUB_URL_RE = re.compile(
    r"^(?:https?://)?(?:www\.)?github\.com/"
    r"(?P<owner>[^/]+)/(?P<repo>[^/]+?)(?:\.git)?"
    r"(?:/(?:tree|blob)/[^/]+/(?P<subpath>.+))?"
    r"/?$"
)


def parse_github_url(url):
    """Extract (owner, repo, subpath) from a GitHub URL.

    Supported forms:
        github.com/owner/repo
        https://github.com/owner/repo.git
        https://github.com/owner/repo/tree/branch/sub/path

    Raises ValueError for unsupported URLs.
    """
    match = _GITHUB_URL_RE.match(url.strip())
    if not match:
        raise ValueError("Invalid GitHub URL")
    owner = match.group("owner")
    repo = match.group("repo")
    subpath = match.group("subpath")
    return owner, repo, subpath


def download_github_repo(owner, repo):
    """Download the default-branch zipball for a GitHub repository.

    Returns the raw zipball bytes.
    Raises LookupError for 404 (repo not found).
    Raises PermissionError for 403 (rate limited / forbidden).
    Raises ConnectionError for other network / HTTP errors.
    """
    url = f"https://api.github.com/repos/{owner}/{repo}/zipball"
    if not url.startswith("https://"):
        raise ValueError("Only HTTPS URLs are supported")
    req = urllib.request.Request(  # noqa: S310
        url,
        headers={"User-Agent": "pi-cowork/github-skill-importer"},
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:  # noqa: S310
            return resp.read()
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            raise LookupError(f"Repository {owner}/{repo} not found") from exc
        if exc.code == 403:
            raise PermissionError("GitHub API rate limit or access denied") from exc
        raise ConnectionError(f"GitHub download failed: HTTP {exc.code}") from exc
    except urllib.error.URLError as exc:
        raise ConnectionError(f"Network error: {exc.reason}") from exc


def import_skill_from_github(url, workflow_id=None):
    """Import a skill from a public GitHub repository.

    Args:
        url: GitHub repository or subdirectory URL.
        workflow_id: Workflow ID to import into. If None, imports into global scope.

    Returns:
        (skill_info_dict, error_string).  error_string is None on success.
    """
    try:
        owner, repo, subpath = parse_github_url(url)
    except ValueError as exc:
        return None, str(exc)

    try:
        zip_bytes = download_github_repo(owner, repo)
    except (LookupError, PermissionError, ConnectionError) as exc:
        return None, str(exc)

    import tempfile

    with tempfile.TemporaryDirectory() as tmpdir:
        try:
            with zipfile.ZipFile(io.BytesIO(zip_bytes), "r") as zf:
                zf.extractall(tmpdir)
        except zipfile.BadZipFile:
            return None, "Invalid ZIP file downloaded from GitHub"

        # GitHub zipballs have a single top-level directory like owner-repo-sha/
        entries = [e for e in os.listdir(tmpdir)]
        if not entries:
            return None, "Downloaded ZIP is empty"

        if len(entries) == 1 and os.path.isdir(os.path.join(tmpdir, entries[0])):
            root_dir = os.path.join(tmpdir, entries[0])
        else:
            root_dir = tmpdir

        # If a subpath was specified, navigate into it
        if subpath:
            target = os.path.normpath(os.path.join(root_dir, subpath))
            norm_root = os.path.normpath(root_dir) + os.sep
            if not target.startswith(norm_root) and target != os.path.normpath(root_dir):
                return None, "Invalid subpath"
            if not os.path.isdir(target):
                return None, f"Subpath '{subpath}' not found in repository"
            root_dir = target

        return _import_skill_from_dir(root_dir, workflow_id)


def import_skill_from_bytes(zip_bytes, workflow_id=None):
    """Import a skill from raw ZIP bytes.

    Args:
        zip_bytes: Raw bytes of a ZIP archive.
        workflow_id: Workflow ID to import into. If None, imports into global scope.

    Returns:
        (skill_info_dict, error_string).  error_string is None on success.
    """
    import tempfile

    with tempfile.TemporaryDirectory() as tmpdir:
        try:
            with zipfile.ZipFile(io.BytesIO(zip_bytes), "r") as zf:
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

        return _import_skill_from_dir(root_dir, workflow_id)


def import_skill_from_zip(file_storage, workflow_id=None):
    """Import a skill from an uploaded ZIP file.

    Args:
        file_storage: Flask FileStorage object (request.files['file']).
        workflow_id: Workflow ID to import into. If None, imports into global scope.

    Returns:
        (skill_info_dict, error_string).  error_string is None on success.
    """
    return import_skill_from_bytes(file_storage.read(), workflow_id)


def _import_skill_from_dir(root_dir, workflow_id=None):
    """Import a skill from an extracted directory.

    Returns:
        (skill_info_dict, error_string).  error_string is None on success.
    """
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

    if workflow_id is not None:
        target_dir = get_skill_dir(workflow_id, name)
        exists_msg = f"Skill '{name}' already exists in this workflow"
    else:
        target_dir = get_global_skill_dir(name)
        exists_msg = f"Global skill '{name}' already exists"

    if os.path.exists(target_dir):
        return None, exists_msg

    shutil.copytree(root_dir, target_dir)

    subdirs = []
    for sub in sorted(os.listdir(target_dir)):
        if os.path.isdir(os.path.join(target_dir, sub)) and not sub.startswith("."):
            subdirs.append(sub)

    return {
        "name": name,
        "description": meta.get("description"),
        "content": content,
        "subdirs": subdirs,
    }, None
