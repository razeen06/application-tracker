"""Verify the live database matches the User model and Alembic head.

Run with DATABASE_URL pointed at the database to audit:
    python scripts/verify_schema.py

The output contains schema metadata only and never prints the connection URL
or any row data, so it is safe to retain in CI/deploy logs.
"""

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import app  # noqa: E402
from models import db  # noqa: E402
from schema_health import inspect_user_schema  # noqa: E402


def main():
    with app.app_context():
        result = inspect_user_schema(db.engine, app.root_path)

    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
