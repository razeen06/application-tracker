import os
import socket
import sys
import tempfile
import threading

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _free_port():
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture(scope="session")
def live_server():
    # Respects a DATABASE_URL already set in the environment -- CI points
    # this at a real Postgres service container, since the migration-drift
    # bugs we've hit repeatedly only ever showed up against Postgres, never
    # against SQLite (SQLite stores enum columns as a plain, unconstrained
    # VARCHAR; Postgres enforces a real native enum type). Falls back to a
    # throwaway SQLite file for local runs, where no DATABASE_URL is set.
    #
    # Either way, tests create their own schema straight from the current
    # models via db.create_all() -- no Alembic involved. The migration
    # chain itself is verified separately (see the "migrations" CI job),
    # applying every migration in order against a fresh Postgres database.
    database_url = os.environ.get("DATABASE_URL")
    sqlite_path = None

    if not database_url:
        db_fd, sqlite_path = tempfile.mkstemp(suffix=".db")
        os.close(db_fd)
        os.remove(sqlite_path)
        database_url = f"sqlite:///{sqlite_path}"

    os.environ["FLASK_DEBUG"] = "true"  # also relaxes SESSION_COOKIE_SECURE for plain-http testing
    os.environ["DATABASE_URL"] = database_url
    for key in ("GOOGLE_CLIENT_ID", "GOOGLE_CLIENT_SECRET", "EXTENSION_ORIGIN", "GEMINI_API_KEY"):
        os.environ.pop(key, None)

    from app import create_app
    from models import db

    app = create_app()
    with app.app_context():
        db.create_all()

    from werkzeug.serving import make_server

    port = _free_port()
    server = make_server("127.0.0.1", port, app, threaded=True)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()

    base_url = f"http://127.0.0.1:{port}"
    yield app, base_url

    server.shutdown()
    thread.join(timeout=5)
    if sqlite_path and os.path.exists(sqlite_path):
        os.remove(sqlite_path)
