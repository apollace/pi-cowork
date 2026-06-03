"""Verification test: ensure schema.sql stays in sync with the migration system.

Creates two databases:
  1. schema-only  — built from schema.sql alone (no migrations)
  2. full        — built from schema.sql + _migrate() (the normal init_db flow)

Compares table names, column definitions (via PRAGMA table_info), and indexes.
Ignores the `_migrations` table (only exists after migrations run).
On mismatch, prints a clear diff showing exactly what differs.
"""

import os
import sqlite3
import tempfile

import pytest

from pi_cowork.db import _migrate

SCHEMA_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'schema.sql')


def _open_db(path):
    db = sqlite3.connect(path)
    db.execute('PRAGMA foreign_keys = ON')
    db.execute('PRAGMA journal_mode = WAL')
    return db


def _get_tables(db):
    """Return sorted list of user table names (excluding _migrations)."""
    rows = db.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name != '_migrations' ORDER BY name"
    ).fetchall()
    return [r[0] for r in rows]


def _get_columns(db, table):
    """Return list of column-def tuples: (cid, name, type, notnull, dflt, pk)."""
    rows = db.execute(f'PRAGMA table_info("{table}")').fetchall()
    return [(r[1], r[2], r[3], r[4], r[5]) for r in rows]


def _get_indexes(db):
    """Return sorted list of (name, tbl, sql) for user indexes (excluding auto-indexes)."""
    rows = db.execute(
        "SELECT name, tbl_name, sql FROM sqlite_master "
        "WHERE type='index' AND name NOT LIKE 'sqlite_autoindex%' "
        "ORDER BY name"
    ).fetchall()
    return [(r[0], r[1], r[2]) for r in rows]


def _build_schema_only_db():
    """Create a temp DB from schema.sql only."""
    fd, path = tempfile.mkstemp(suffix='.db')
    os.close(fd)
    db = _open_db(path)
    with open(SCHEMA_PATH, 'r') as f:
        db.cursor().executescript(f.read())
    db.commit()
    return path, db


def _build_full_db():
    """Create a temp DB from schema.sql + _migrate() (mirrors init_db)."""
    fd, path = tempfile.mkstemp(suffix='.db')
    os.close(fd)
    db = _open_db(path)
    with open(SCHEMA_PATH, 'r') as f:
        db.cursor().executescript(f.read())
    db.commit()
    _migrate(db)
    return path, db


class TestSchemaSync:
    """Ensure schema.sql and the migration system produce identical schemas."""

    @pytest.fixture(autouse=True)
    def _dbs(self):
        self.path_schema, self.db_schema = _build_schema_only_db()
        self.path_full, self.db_full = _build_full_db()
        yield
        self.db_schema.close()
        self.db_full.close()
        os.unlink(self.path_schema)
        os.unlink(self.path_full)

    def test_tables_match(self):
        """All tables (except _migrations) exist in both schemas."""
        schema_tables = _get_tables(self.db_schema)
        full_tables = _get_tables(self.db_full)
        missing_in_schema = set(full_tables) - set(schema_tables)
        missing_in_full = set(schema_tables) - set(full_tables)
        msg_parts = []
        if missing_in_schema:
            msg_parts.append(
                f"Tables in full DB but missing from schema.sql: {sorted(missing_in_schema)}"
            )
        if missing_in_full:
            msg_parts.append(
                f"Tables in schema.sql but missing from migrations: {sorted(missing_in_full)}"
            )
        assert not msg_parts, '\n'.join(msg_parts)

    def test_columns_match(self):
        """Every shared table has identical column definitions."""
        schema_tables = set(_get_tables(self.db_schema))
        full_tables = set(_get_tables(self.db_full))
        shared = sorted(schema_tables & full_tables)
        diffs = []
        for table in shared:
            schema_cols = _get_columns(self.db_schema, table)
            full_cols = _get_columns(self.db_full, table)
            if schema_cols != full_cols:
                schema_set = set(schema_cols)
                full_set = set(full_cols)
                missing_in_schema = full_set - schema_set
                missing_in_full = schema_set - full_set
                if missing_in_schema:
                    diffs.append(
                        f"Table '{table}': columns in full DB but missing from schema.sql: "
                        f"{sorted(missing_in_schema)}"
                    )
                if missing_in_full:
                    diffs.append(
                        f"Table '{table}': columns in schema.sql but missing from full DB: "
                        f"{sorted(missing_in_full)}"
                    )
        assert not diffs, '\n'.join(diffs)

    def test_indexes_match(self):
        """All user-created indexes exist in both schemas."""
        schema_indexes = _get_indexes(self.db_schema)
        full_indexes = _get_indexes(self.db_full)
        schema_dict = {name: (tbl, sql) for name, tbl, sql in schema_indexes}
        full_dict = {name: (tbl, sql) for name, tbl, sql in full_indexes}
        missing_in_schema = set(full_dict) - set(schema_dict)
        missing_in_full = set(schema_dict) - set(full_dict)
        mismatched = []
        for name in set(full_dict) & set(schema_dict):
            if full_dict[name] != schema_dict[name]:
                mismatched.append(
                    f"Index '{name}': schema.sql has {schema_dict[name]}, "
                    f"full DB has {full_dict[name]}"
                )
        msg_parts = []
        if missing_in_schema:
            names = sorted(missing_in_schema)
            msg_parts.append(
                f"Indexes in full DB but missing from schema.sql: {names}"
            )
        if missing_in_full:
            names = sorted(missing_in_full)
            msg_parts.append(
                f"Indexes in schema.sql but missing from full DB: {names}"
            )
        if mismatched:
            msg_parts.append(f"Index definitions differ:\n" + '\n'.join(mismatched))
        assert not msg_parts, '\n'.join(msg_parts)