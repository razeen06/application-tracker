"""Read-only database schema health checks shared by CI and production."""

import os

from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import inspect, text

from models import User


def local_migration_head(app_root):
    config = Config(os.path.join(app_root, "migrations", "alembic.ini"))
    config.set_main_option("script_location", os.path.join(app_root, "migrations"))
    heads = ScriptDirectory.from_config(config).get_heads()
    if len(heads) != 1:
        raise RuntimeError(f"Expected one local migration head, found {heads}")
    return heads[0]


def inspect_user_schema(engine, app_root):
    inspector = inspect(engine)
    actual_columns = {
        column["name"]: {
            "type": str(column["type"]),
            "nullable": bool(column["nullable"]),
        }
        for column in inspector.get_columns(User.__tablename__)
    }
    expected_columns = {
        column.name: {
            "type": str(column.type.compile(dialect=engine.dialect)),
            "nullable": bool(column.nullable),
        }
        for column in User.__table__.columns
    }

    with engine.connect() as connection:
        database_heads = [
            row[0]
            for row in connection.execute(
                text("SELECT version_num FROM alembic_version ORDER BY version_num")
            ).all()
        ]

    local_head = local_migration_head(app_root)
    missing = sorted(set(expected_columns) - set(actual_columns))
    unexpected = sorted(set(actual_columns) - set(expected_columns))
    migration_current = database_heads == [local_head]
    ok = not missing and not unexpected and migration_current

    return {
        "ok": ok,
        "model": "User",
        "expected_columns": expected_columns,
        "actual_columns": actual_columns,
        "missing_columns": missing,
        "unexpected_columns": unexpected,
        "local_migration_head": local_head,
        "database_migration_heads": database_heads,
        "migration_current": migration_current,
    }
