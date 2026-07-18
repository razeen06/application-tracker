"""Verify the live database matches the User model and Alembic head.

Run with DATABASE_URL pointed at the database to audit:
    python scripts/verify_schema.py

The output contains schema metadata only and never prints the connection URL
or any row data, so it is safe to retain in CI/deploy logs.
"""

import json
import os
import sys

from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import inspect, text

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import app  # noqa: E402
from models import User, db  # noqa: E402


def _local_head():
    config = Config(os.path.join(app.root_path, "migrations", "alembic.ini"))
    config.set_main_option("script_location", os.path.join(app.root_path, "migrations"))
    heads = ScriptDirectory.from_config(config).get_heads()
    if len(heads) != 1:
        raise RuntimeError(f"Expected one local migration head, found {heads}")
    return heads[0]


def main():
    with app.app_context():
        inspector = inspect(db.engine)
        actual_columns = {
            column["name"]: {
                "type": str(column["type"]),
                "nullable": bool(column["nullable"]),
            }
            for column in inspector.get_columns(User.__tablename__)
        }
        expected_columns = {
            column.name: {
                "type": str(column.type.compile(dialect=db.engine.dialect)),
                "nullable": bool(column.nullable),
            }
            for column in User.__table__.columns
        }

        production_heads = [
            row[0]
            for row in db.session.execute(
                text("SELECT version_num FROM alembic_version ORDER BY version_num")
            ).all()
        ]
        local_head = _local_head()

    missing = sorted(set(expected_columns) - set(actual_columns))
    unexpected = sorted(set(actual_columns) - set(expected_columns))
    migration_current = production_heads == [local_head]
    ok = not missing and not unexpected and migration_current

    print(json.dumps({
        "ok": ok,
        "model": "User",
        "expected_columns": expected_columns,
        "actual_columns": actual_columns,
        "missing_columns": missing,
        "unexpected_columns": unexpected,
        "local_migration_head": local_head,
        "database_migration_heads": production_heads,
        "migration_current": migration_current,
    }, indent=2, sort_keys=True))
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
