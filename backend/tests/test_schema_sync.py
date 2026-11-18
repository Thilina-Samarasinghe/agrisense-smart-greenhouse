"""The database schema is defined twice: Prisma (schema + migrations, the source of truth for
PostgreSQL) and SQLAlchemy (used by the Python backend at runtime). These tests fail as soon as
the two drift apart: tables, columns, types, nullability, indexes and foreign keys."""

import re
from pathlib import Path

import pytest
from sqlalchemy.dialects import postgresql

from app.db.models import Base

DB_DIR = Path(__file__).resolve().parents[2] / "database" / "prisma"
SCHEMA = DB_DIR / "schema.prisma"
MIGRATIONS = DB_DIR / "migrations"

PRISMA_SCALARS = {"Int": "INTEGER", "Float": "FLOAT", "Boolean": "BOOLEAN", "DateTime": "TIMESTAMP"}
SQL_TYPES = {
    "DOUBLE PRECISION": "FLOAT",
    "SERIAL": "INTEGER",
    "INTEGER": "INTEGER",
    "BOOLEAN": "BOOLEAN",
    "TEXT": "TEXT",
}

pytestmark = pytest.mark.skipif(not SCHEMA.exists(), reason="database/ folder not present")


def _sqlalchemy() -> dict:
    dialect = postgresql.dialect()
    tables = {}
    for t in Base.metadata.sorted_tables:
        cols = {}
        for c in t.columns:
            typ = c.type.compile(dialect=dialect)
            typ = "TIMESTAMP" if typ.startswith("TIMESTAMP") else typ
            cols[c.name] = (typ, bool(c.nullable) and not c.primary_key)
        idx = {i.name: (tuple(c.name for c in i.columns), bool(i.unique)) for i in t.indexes}
        fks = {
            (fk.parent.name, fk.column.table.name, fk.ondelete or "NO ACTION")
            for fk in t.foreign_keys
        }
        tables[t.name] = {"columns": cols, "indexes": idx, "fks": fks}
    return tables


def _prisma() -> dict:
    text = SCHEMA.read_text(encoding="utf-8")
    models = dict(re.findall(r"model\s+(\w+)\s*\{(.*?)\n\}", text, re.S))
    tables = {}
    for body in models.values():
        table = re.search(r'@@map\("(\w+)"\)', body).group(1)
        cols, idx, fks = {}, {}, set()
        for line in body.splitlines():
            line = line.split("//")[0].strip()
            m = re.match(r"^(\w+)\s+(\w+)(\[\])?(\?)?(.*)$", line)
            if not m or line.startswith("@@"):
                continue
            name, typ, is_list, optional, rest = m.groups()
            if is_list or typ in models:
                rel = re.search(r"fields:\s*\[(\w+)\].*onDelete:\s*(\w+)", rest)
                if rel:
                    action = {"Cascade": "CASCADE", "SetNull": "SET NULL"}.get(
                        rel.group(2), "NO ACTION"
                    )
                    fks.add((rel.group(1), "runs", action))
                continue
            if typ == "String":
                db = re.search(r"@db\.(VarChar\((\d+)\)|Text)", rest)
                sql = f"VARCHAR({db.group(2)})" if db.group(2) else "TEXT"
            else:
                sql = PRISMA_SCALARS[typ]
            cols[name] = (sql, bool(optional))
        for kind, cols_txt, name in re.findall(
            r'@@(index|unique)\(\[([^\]]+)\],\s*map:\s*"(\w+)"\)', body
        ):
            idx[name] = (tuple(c.strip() for c in cols_txt.split(",")), kind == "unique")
        tables[table] = {"columns": cols, "indexes": idx, "fks": fks}
    return tables


def _migrations() -> dict:
    sql = "\n".join(
        p.read_text(encoding="utf-8") for p in sorted(MIGRATIONS.glob("*/migration.sql"))
    )
    tables = {}
    for name, body in re.findall(r'CREATE TABLE "(\w+)" \((.*?)\n\);', sql, re.S):
        cols = {}
        for line in body.splitlines():
            m = re.match(r'\s*"(\w+)" ([A-Z]+(?: PRECISION)?(?:\(\d+\))?)( NOT NULL)?', line)
            if m:
                raw = m.group(2)
                typ = "TIMESTAMP" if raw.startswith("TIMESTAMP") else SQL_TYPES.get(raw, raw)
                cols[m.group(1)] = (typ, m.group(3) is None)
        tables[name] = {"columns": cols, "indexes": {}, "fks": set()}
    for unique, name, table, cols_txt in re.findall(
        r'CREATE (UNIQUE )?INDEX "(\w+)" ON "(\w+)"\(([^)]+)\)', sql
    ):
        cols = tuple(c.strip().strip('"') for c in cols_txt.split(","))
        tables[table]["indexes"][name] = (cols, bool(unique))
    for table, col, ref, action in re.findall(
        r'ALTER TABLE "(\w+)" ADD CONSTRAINT "\w+" FOREIGN KEY \("(\w+)"\) '
        r'REFERENCES "(\w+)"\("id"\) '
        r"ON DELETE ([A-Z ]+?) ON UPDATE",
        sql,
    ):
        tables[table]["fks"].add((col, ref, action))
    return tables


@pytest.mark.parametrize("source", ["prisma", "migrations"])
def test_schema_matches_sqlalchemy_models(source):
    expected = _sqlalchemy()
    actual = _prisma() if source == "prisma" else _migrations()
    assert set(actual) == set(expected), f"{source}: tables differ"
    for table, exp in expected.items():
        got = actual[table]
        assert got["columns"] == exp["columns"], f"{source}: columns of {table} differ"
        assert got["indexes"] == exp["indexes"], f"{source}: indexes of {table} differ"
        assert got["fks"] == exp["fks"], f"{source}: foreign keys of {table} differ"


def test_foreign_keys_do_not_cascade_updates():
    """Prisma defaults to ON UPDATE CASCADE; the schema must state NoAction like SQLAlchemy."""
    text = SCHEMA.read_text(encoding="utf-8")
    assert text.count("onUpdate: NoAction") == 6
    sql = "\n".join(p.read_text(encoding="utf-8") for p in MIGRATIONS.glob("*/migration.sql"))
    assert "ON UPDATE CASCADE" not in sql
